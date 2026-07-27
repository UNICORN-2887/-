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
                 goal_reach: int = 100,
                 lookahead: int = 90,
                 move_duration_ms: int = 300):
        self._pf = pathfinder
        self._driver = driver
        self.waypoint_reach = waypoint_reach
        self.goal_reach = goal_reach
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
        if not self._path:
            self.arrived = True
            return None

        # 距终点 < goal_reach → 到达
        last = self._path[-1]
        if np.hypot(current_pos[0]-last[0], current_pos[1]-last[1]) < self.goal_reach:
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

        # 找到路径上距当前位置最近的点 (跳过身后点)
        min_dist = float('inf')
        nearest_idx = self._wp_index
        for i in range(self._wp_index, len(self._path)):
            wx, wy = self._path[i]
            d = np.hypot(wx - current_pos[0], wy - current_pos[1])
            if d < min_dist:
                min_dist = d
                nearest_idx = i
        # current_waypoint 只进不退 (原版有 max(current_waypoint, wpidx-2))
        self._wp_index = nearest_idx

        # 向前找第一个距离 >= lookahead 的点
        for i in range(self._wp_index, len(self._path)):
            wx, wy = self._path[i]
            if np.hypot(wx - current_pos[0], wy - current_pos[1]) >= self.lookahead:
                self._wp_index = i
                break
        target = self._path[min(self._wp_index + 10, len(self._path) - 1)]

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
                 port: int = 5001,
                 map_image: Optional[str] = None):
        from flask import Flask, request, jsonify, render_template_string
        self._nav = Navigator(pathfinder, driver)
        self._port = port
        self._app = Flask(__name__)
        self._tracker_callback: Optional[Callable] = None
        self._map_image = map_image
        self._pf = pathfinder
        self._reachable_path = None
        self._cap = None  # OBS capture (可选)

        # 前端页面 (支持URL参数调参: ?wp=25&gr=100&la=90&sh=8)
        @self._app.route("/api/cameras")
        def api_cameras():
            from game_automator.capture import OBSVideoCapture
            cams = OBSVideoCapture.list_cameras()
            return jsonify({"cameras": [{"id": i, "name": n, "obs": "obs" in n.lower()} for i, n in cams]})

        @self._app.route("/api/set_camera", methods=["POST"])
        def api_set_camera():
            data = request.get_json() or {}
            cam_id = data.get("cam_id", 1)
            from game_automator.capture import OBSVideoCapture
            self._cap = OBSVideoCapture(cam_id=cam_id)
            return jsonify({"ok": True, "cam_id": cam_id})

        @self._app.route("/vbs_template")
        def vbs_template():
            import os
            tp = os.path.join(os.path.dirname(__file__), "vbs_template.txt")
            with open(tp, encoding="utf-8") as f:
                return f.read()

        @self._app.route("/py_template")
        def py_template():
            import os
            tp = os.path.join(os.path.dirname(__file__), "py_template.txt")
            with open(tp, encoding="utf-8") as f:
                return f.read()

        @self._app.route("/")
        def index():
            import base64
            wp = request.args.get("wp", 25, type=int)
            gr = request.args.get("gr", 100, type=int)
            la = request.args.get("la", 90, type=int)
            sh = request.args.get("sh", 8, type=int)
            # 用新参数重建引擎 (保留已有路径)
            old_path = self._nav.path if self._nav and not self._nav.arrived else []
            if self._reachable_path:
                self._pf = Pathfinder(self._reachable_path, shrink=sh)
                self._nav = Navigator(self._pf, waypoint_reach=wp, goal_reach=gr, lookahead=la)
            if old_path:
                self._nav._path = old_path
            map_b64 = ""
            if self._map_image:
                try:
                    with open(self._map_image, "rb") as f:
                        map_b64 = base64.b64encode(f.read()).decode()
                except: pass
            return render_template_string(_NAV_HTML, map_b64=map_b64,
                gw=self._pf.grid_size[0], gh=self._pf.grid_size[1],
                wp=wp, gr=gr, la=la, sh=sh)

        @self._app.route("/api/plan", methods=["POST"])
        def plan():
            data = request.get_json() or {}
            sx, sy = data.get("start", (0, 0))
            gx, gy = data.get("goal", (0, 0))
            # Always plan fresh (don't rely on existing navigator state)
            raw = self._pf.plan((int(sx), int(sy)), (int(gx), int(gy))) or []
            self._nav._path = raw  # sync Navigator for step() calls
            path = [(int(x), int(y)) for x, y in raw]
            return jsonify({"path": path, "length": len(path)})

        @self._app.route("/api/step", methods=["POST"])
        def step():
            data = request.get_json() or {}
            if not self._nav.path:
                return jsonify({"error": "no plan - click Plan Path first", "arrived": False})
            pos = (data.get("x", 0), data.get("y", 0))
            action = self._nav.step(pos)
            wp = self._nav.current_waypoint
            wp_json = (int(wp[0]), int(wp[1])) if wp else None
            return jsonify({
                "action": action.name if action else None,
                "arrived": self._nav.arrived,
                "waypoint": wp_json,
                "waypointX": wp_json[0] if wp_json else 0,
                "waypointY": wp_json[1] if wp_json else 0,
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

        # 外部控制接口: 外部脚本(按键精灵等)推送位置
        self._external_pos = [0, 0]
        @self._app.route("/api/report", methods=["POST"])
        def api_report():
            data = request.get_json() or {}
            self._external_pos = [data.get("x", 0), data.get("y", 0)]
            return jsonify({"ok": True, "pos": self._external_pos})

        @self._app.route("/api/position", methods=["GET", "POST"])
        def api_position():
            return jsonify({"pos": self._external_pos,
                "posX": int(self._external_pos[0]), "posY": int(self._external_pos[1])})

        @self._app.route("/api/status")
        def status():
            return jsonify({
                "arrived": self._nav.arrived,
                "waypoint": self._nav.current_waypoint,
                "path_length": len(self._nav.path),
            })

        # ORB帧间匹配: 整帧跟踪地图位移 (视口模式)
        @self._app.route("/api/track", methods=["POST"])
        def api_track():
            """DeadMaze hybrid: frame-to-frame flow predict + map ROI validate"""
            import cv2, numpy as np
            if self._cap is None:
                return jsonify({"error": "no capture"})
            if self._map_image is None:
                return jsonify({"error": "need --map for tracking"})

            # Init
            if not hasattr(self, '_tk'):
                self._map_full = cv2.imread(self._map_image)
                self._mh, self._mw = self._map_full.shape[:2]
                self._tk = {'prev': None, 'pos': [0,0], 'orb': cv2.ORB_create(nfeatures=2000),
                    'matcher': cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)}
                self._cap.read(); self._cap.read()
                frame = self._cap.read()
                if frame is None: return jsonify({"error": "capture failed"})
                self._tk['prev'] = cv2.resize(frame, None, fx=0.5, fy=0.5)
                self._fw = frame.shape[1]
                return jsonify({"pos":[0,0],"conf":0,"method":"hybrid init"})

            self._cap.read(); self._cap.read()
            frame = self._cap.read()
            if frame is None: return jsonify({"error": "capture failed"})
            curr = cv2.resize(frame, None, fx=0.5, fy=0.5)
            curr_gray = cv2.cvtColor(curr, cv2.COLOR_BGR2GRAY)

            # Step 1: frame-to-frame ORB displacement
            prev_gray = cv2.cvtColor(self._tk['prev'], cv2.COLOR_BGR2GRAY)
            kp1, des1 = self._tk['orb'].detectAndCompute(prev_gray, None)
            kp2, des2 = self._tk['orb'].detectAndCompute(curr_gray, None)
            dx, dy, flow_conf = 0.0, 0.0, 0.0
            if des1 is not None and des2 is not None and len(des1)>=10 and len(des2)>=10:
                matches = self._tk['matcher'].match(des1, des2)
                if len(matches) >= 8:
                    best = sorted(matches, key=lambda m: m.distance)[:60]
                    dxs, dys = [], []
                    for m in best:
                        dxs.append(kp2[m.trainIdx].pt[0]-kp1[m.queryIdx].pt[0])
                        dys.append(kp2[m.trainIdx].pt[1]-kp1[m.queryIdx].pt[1])
                    dx = np.median(dxs); dy = np.median(dys)
                    flow_conf = sum(1 for ddx,ddy in zip(dxs,dys) if abs(ddx-dx)<6 and abs(ddy-dy)<6) / len(dxs)

            # Step 2: predict position from flow
            pred_x = self._tk['pos'][0] + dx / 0.5  # scale back to L0
            pred_y = self._tk['pos'][1] + dy / 0.5

            # Step 3: validate against map ROI
            fh, fw = curr_gray.shape
            q_scale = fw / self._fw
            r = 800
            x1 = max(0, int(pred_x - r))
            y1 = max(0, int(pred_y - r))
            x2 = min(self._mw, int(pred_x + r))
            y2 = min(self._mh, int(pred_y + r))
            map_conf = 0.0

            if x2-x1>=100 and y2-y1>=100:
                map_roi = self._map_full[y1:y2, x1:x2]
                ms = cv2.resize(map_roi, (int((x2-x1)*q_scale), int((y2-y1)*q_scale)), interpolation=cv2.INTER_AREA)
                kp_m, des_m = self._tk['orb'].detectAndCompute(ms, None)
                kp_f, des_f = self._tk['orb'].detectAndCompute(curr_gray, None)
                if des_m is not None and des_f is not None and len(des_m)>=10 and len(des_f)>=10:
                    matches2 = self._tk['matcher'].match(des_f, des_m)
                    if len(matches2) >= 8:
                        best2 = sorted(matches2, key=lambda m: m.distance)[:60]
                        mdxs, mdys = [], []
                        for m in best2:
                            pf = kp_f[m.queryIdx].pt
                            pm = kp_m[m.trainIdx].pt
                            mdxs.append(pm[0] - pf[0])
                            mdys.append(pm[1] - pf[1])
                        mdx = np.median(mdxs); mdy = np.median(mdys)
                        map_conf = sum(1 for ddx,ddy in zip(mdxs,mdys) if abs(ddx-mdx)<8 and abs(ddy-mdy)<8) / len(mdxs)
                        if map_conf > 0.30:
                            fx = x1 + mdx / q_scale
                            fy = y1 + mdy / q_scale
                            self._tk['pos'] = [int(fx), int(fy)]
                            self._tk['prev'] = curr
                            print(f"[Track] flow({dx:.0f},{dy:.0f}) c={flow_conf:.2f} | map=({fx:.0f},{fy:.0f}) c={map_conf:.2f}")
                            return jsonify({"pos": self._tk['pos'], "dxy": [0,0],
                                "conf": round(map_conf,2), "method": f"hybrid map=({fx:.0f},{fy:.0f})"})

            # Fallback: use flow prediction
            if flow_conf > 0.30:
                self._tk['pos'] = [int(pred_x), int(pred_y)]
            self._tk['prev'] = curr
            print(f"[Track] flow({dx:.0f},{dy:.0f}) c={flow_conf:.2f} → pred=({pred_x:.0f},{pred_y:.0f}) map_conf={map_conf:.2f}")
            return jsonify({"pos": self._tk['pos'], "dxy": [0,0],
                "conf": round(flow_conf,2), "method": f"flow pred=({pred_x:.0f},{pred_y:.0f})"})

        # OBS 实时预览
        @self._app.route("/api/capture")
        def api_capture():
            import base64, cv2 as _cv
            if self._cap is None:
                return jsonify({"error": "no OBS camera. Open OBS Studio, add Window Capture of browser, start Virtual Camera"})
            frame = self._cap.read()
            if frame is None:
                return jsonify({"error": "OBS frame read failed. Is OBS Virtual Camera started?"})
            _, buf = _cv.imencode(".jpg", frame, [_cv.IMWRITE_JPEG_QUALITY, 75])
            return jsonify({"ok": True,
                "image": base64.b64encode(buf).decode(),
                "shape": list(frame.shape[:2])})

    def start(self, blocking: bool = True):
        print(f"[NavigationServer] http://127.0.0.1:{self._port}/  (前端)")
        self._app.run(host="127.0.0.1", port=self._port,
                       debug=False, use_reloader=False)

    def start_threaded(self):
        t = Thread(target=self.start, kwargs={"blocking": True}, daemon=True)
        t.start()
        return t

from game_automator.navigation._nav_html import _NAV_HTML as _NAV_HTML
# (HTML模板在独立文件 _nav_html.py 中)

