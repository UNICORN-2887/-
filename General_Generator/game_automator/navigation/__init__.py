"""导航控制器 + Flask REST API.

Navigator: Python SDK 直接调用.
NavigationServer: Flask HTTP API, 非 Python 用户通过 REST 调用.
"""

from typing import Optional, Tuple, List, Callable
from queue import Queue
from threading import Thread
import time
import os
import json

import numpy as np

from game_automator.driver import Actions, AbstractDriver
from game_automator.mapping import Pathfinder


# ── 8方向 + 最佳匹配 (直搬 DeadMaze best_direction) ──
_DIR_VECTORS = [
    ( 0, -1, Actions.MOVE_N),        # 0: N
    ( 1, -1, Actions.MOVE_NE),       # 1: NE
    ( 1,  0, Actions.MOVE_E),        # 2: E
    ( 1,  1, Actions.MOVE_SE),       # 3: SE
    ( 0,  1, Actions.MOVE_S),        # 4: S
    (-1,  1, Actions.MOVE_SW),       # 5: SW
    (-1,  0, Actions.MOVE_W),        # 6: W
    (-1, -1, Actions.MOVE_NW),       # 7: NW
]


def compute_direction(from_pos: Tuple[int, int],
                      to_pos: Tuple[int, int]) -> Actions:
    """向量 (dx, dy) → 最接近的8方向 (内积最大)."""
    dx = to_pos[0] - from_pos[0]
    dy = to_pos[1] - from_pos[1]
    if dx == 0 and dy == 0:
        return None
    best_i, best_dot = 0, -999
    for i, (vx, vy, _) in enumerate(_DIR_VECTORS):
        d = vx * dx + vy * dy
        if d > best_dot:
            best_dot = d
            best_i = i
    return _DIR_VECTORS[best_i][2]


# ── 导航控制器 ────────────────────────────────
class Navigator:
    """Python SDK 导航控制器.

    Usage:
        nav = Navigator(pathfinder, driver)
        nav.set_route(start, goal)
        while not nav.arrived:
            pos = tracker.get_position()   # 用户提供定位回调
            action = nav.step(pos)
            if action: driver.execute(action)
    """

    def __init__(self,
                 pathfinder: Pathfinder,
                 driver: Optional[AbstractDriver] = None,
                 waypoint_reach: int = 25,
                 lookahead: int = 90,
                 move_duration_ms: int = 300):
        self._pf = pathfinder
        self._driver = driver
        self.waypoint_reach = waypoint_reach
        self.lookahead = lookahead
        self.move_duration_ms = move_duration_ms

        self._path: List[Tuple[int, int]] = []
        self._wp_index = 0
        self._goal: Optional[Tuple[int, int]] = None
        self.arrived = False

    # ── 设置 ──────────────────────────────────
    def set_route(self, start: Tuple[int, int],
                  goal: Tuple[int, int]) -> List[Tuple[int, int]]:
        self._path = self._pf.plan(start, goal) or []
        self._wp_index = 0
        self._goal = goal
        self.arrived = False
        return self._path

    def set_waypoints(self, waypoints: List[Tuple[int, int]]) -> None:
        """设置途径点列表用于巡逻."""
        self._path = waypoints
        self._wp_index = 0
        self._goal = waypoints[-1] if waypoints else None
        self.arrived = False

    def step(self, current_pos: Tuple[int, int]) -> Optional[Actions]:
        """传入当前位置, 返回应执行的动作 (None=到达)."""
        if not self._path or self._wp_index >= len(self._path):
            self.arrived = True
            return None

        # 跳过已到达的路标
        while self._wp_index < len(self._path):
            tgt = self._path[self._wp_index]
            if np.hypot(current_pos[0]-tgt[0], current_pos[1]-tgt[1]) < self.waypoint_reach:
                self._wp_index += 1
            else:
                break

        if self._wp_index >= len(self._path):
            self.arrived = True
            return None

        # 原版 get_next_waypoint: 向前扫找第一个距当前位置 >= lookahead 的点
        best = self._wp_index
        for i in range(self._wp_index, len(self._path)):
            wx, wy = self._path[i]
            if np.hypot(wx - current_pos[0], wy - current_pos[1]) >= self.lookahead:
                best = i
                break
        if best < len(self._path) - 1:
            best = min(best + 1, len(self._path) - 1)  # look ahead a bit more
        target = self._path[best]

        return compute_direction(current_pos, target)

    def _deviation_distance(self, pos):
        if self._wp_index >= len(self._path):
            return 0.0
        seg_start = self._path[max(0, self._wp_index - 1)]
        seg_end = self._path[self._wp_index]
        return self._point_to_segment_dist(pos, seg_start, seg_end)

    @staticmethod
    def _point_to_segment_dist(p, a, b):
        ax, ay = a; bx, by = b
        abx, aby = bx - ax, by - ay
        if abx == 0 and aby == 0:
            return np.hypot(p[0] - ax, p[1] - ay)
        t = max(0, min(1, ((p[0]-ax)*abx + (p[1]-ay)*aby) / (abx*abx + aby*aby)))
        px = ax + t * abx
        py = ay + t * aby
        return np.hypot(p[0] - px, p[1] - py)

    @property
    def current_waypoint(self) -> Optional[Tuple[int, int]]:
        if self._wp_index < len(self._path):
            return self._path[self._wp_index]
        return None

    @property
    def path(self) -> List[Tuple[int, int]]:
        return list(self._path)

    def cancel(self) -> None:
        self._path = []
        self._wp_index = 0
        self.arrived = True


# ── Flask API 服务 ────────────────────────────
class NavigationServer:
    """REST API 导航服务 (非 Python 用户通过 HTTP 调用)."""

    def __init__(self, pathfinder: Pathfinder,
                 driver: Optional[AbstractDriver] = None,
                 port: int = 5001):
        from flask import Flask, request, jsonify
        self._nav = Navigator(pathfinder, driver)
        self._port = port
        self._app = Flask(__name__)
        self._tracker_callback: Optional[Callable] = None

        @self._app.route("/api/plan", methods=["POST"])
        def plan():
            data = request.get_json() or {}
            sx, sy = data.get("start", (0, 0))
            gx, gy = data.get("goal", (0, 0))
            path = self._nav.set_route((sx, sy), (gx, gy))
            return jsonify({"path": path, "length": len(path)})

        @self._app.route("/api/step", methods=["POST"])
        def step():
            data = request.get_json() or {}
            pos = (data.get("x", 0), data.get("y", 0))
            action = self._nav.step(pos)
            return jsonify({
                "action": action.name if action else None,
                "arrived": self._nav.arrived,
                "waypoint": self._nav.current_waypoint,
            })

        @self._app.route("/api/position", methods=["POST"])
        def set_pos():
            """外部推送当前位置 (替代 tracker)."""
            data = request.get_json() or {}
            self._tracker_callback = lambda: (data["x"], data["y"])
            return jsonify({"ok": True})

        @self._app.route("/api/cancel", methods=["POST"])
        def cancel():
            self._nav.cancel()
            return jsonify({"ok": True})

        @self._app.route("/api/status")
        def status():
            return jsonify({
                "arrived": self._nav.arrived,
                "waypoint": self._nav.current_waypoint,
                "path_length": len(self._nav.path),
            })

    def start(self, blocking: bool = True):
        print(f"[NavigationServer] http://127.0.0.1:{self._port}")
        self._app.run(host="127.0.0.1", port=self._port,
                       debug=False, use_reloader=False)

    def start_threaded(self):
        t = Thread(target=self.start, kwargs={"blocking": True}, daemon=True)
        t.start()
        return t
