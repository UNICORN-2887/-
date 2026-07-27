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
        import threading
        self._cam_lock = threading.Lock()

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
            self._cap = OBSVideoCapture(cam_id=cam_id, width=640, height=360)
            # 重置tracker状态 (因为分辨率可能变了)
            if hasattr(self, '_obstk'): del self._obstk
            return jsonify({"ok": True, "cam_id": cam_id, "res": "640x360"})

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

        # OBS光流追踪: 直搬 DeadMaze map_tracker.py 的 ORB hybrid 方案
        @self._app.route("/api/track", methods=["POST"])
        def api_track():
            """DeadMaze hybrid: ORB帧间位移预测 → 地图ROI ORB匹配定锚"""
            import cv2, numpy as np
            if self._cap is None:
                return jsonify({"error": "no capture"})
            if self._map_image is None:
                return jsonify({"error": "need --map"})

            # ── 内嵌 DeadMaze _orb_displacement ──
            def _orb_displacement(prev_frame, curr_frame):
                kp1, des1 = self._obstk['orb'].detectAndCompute(prev_frame, None)
                kp2, des2 = self._obstk['orb'].detectAndCompute(curr_frame, None)
                if des1 is None or des2 is None or len(des1) < 10 or len(des2) < 10:
                    return 0, 0, 0
                matches = self._obstk['matcher'].match(des1, des2)
                if len(matches) < 8:
                    return 0, 0, 0
                matches = sorted(matches, key=lambda m: m.distance)[:60]
                dxs, dys = [], []
                for m in matches:
                    dxs.append(kp2[m.trainIdx].pt[0] - kp1[m.queryIdx].pt[0])
                    dys.append(kp2[m.trainIdx].pt[1] - kp1[m.queryIdx].pt[1])
                dx = np.median(dxs); dy = np.median(dys)
                conf = sum(1 for ddx,ddy in zip(dxs,dys) if abs(ddx-dx)<6 and abs(ddy-dy)<6) / len(dxs)
                return dx, dy, conf

            # ── 内嵌 DeadMaze _orb_vs_map ──
            def _orb_vs_map(frame, cx, cy, window=800):
                fh, fw = frame.shape[:2]
                q_scale = fw / self._obstk['fw_raw']
                r = window
                x1 = max(0, int(cx - r))
                y1 = max(0, int(cy - r))
                x2 = min(self._mw, int(cx + r))
                y2 = min(self._mh, int(cy + r))
                if x2-x1 < 100 or y2-y1 < 100:
                    return cx, cy, 0
                map_roi = self._map_full[y1:y2, x1:x2].copy()
                # 加噪底 (跟ServerTrack一样) 创造ORB特征
                if hasattr(self, '_noise'):
                    nr = self._noise[y1:y2, x1:x2]
                    map_roi = np.clip(map_roi.astype(np.int16) + nr[:,:,np.newaxis], 0, 255).astype(np.uint8)
                ms = cv2.resize(map_roi, (int((x2-x1)*q_scale), int((y2-y1)*q_scale)), interpolation=cv2.INTER_AREA)
                kp_m, des_m = self._obstk['orb'].detectAndCompute(ms, None)
                kp_f, des_f = self._obstk['orb'].detectAndCompute(frame, None)
                if des_m is None or des_f is None or len(des_m) < 10 or len(des_f) < 10:
                    return cx, cy, 0
                matches = self._obstk['matcher'].match(des_f, des_m)
                if len(matches) < 8:
                    return cx, cy, 0
                matches = sorted(matches, key=lambda m: m.distance)[:60]
                dxs, dys = [], []
                for m in matches:
                    pf = kp_f[m.queryIdx].pt
                    pm = kp_m[m.trainIdx].pt
                    dxs.append(pm[0] - pf[0])
                    dys.append(pm[1] - pf[1])
                mdx = np.median(dxs); mdy = np.median(dys)
                conf = sum(1 for ddx,ddy in zip(dxs,dys) if abs(ddx-mdx)<8 and abs(ddy-mdy)<8) / len(dxs)
                fx = x1 + int(mdx / q_scale) + self._obstk['fw_raw'] // 2
                fy = y1 + int(mdy / q_scale) + self._obstk['fw_raw'] // 2
                return fx, fy, conf

            data = request.get_json() or {}
            sim_x = int(data.get("x", 0))
            sim_y = int(data.get("y", 0))

            with self._cam_lock:
                # Init (搬自 DeadMaze Tracker.__init__)
                if not hasattr(self, '_obstk'):
                    self._map_full = cv2.imread(self._map_image)
                    self._mh, self._mw = self._map_full.shape[:2]
                    self._obstk = {
                        'pos': [sim_x, sim_y],
                        'prev': None,
                        'orb': cv2.ORB_create(nfeatures=2000),
                        'matcher': cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True),
                        'fw_raw': int(self._cap._cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if self._cap._cap else 640,
                        'fno': 1,
                    }
                    # 首次track: 跟DeadMaze一样做地图ROI匹配建立初始位置
                    for _ in range(5): self._cap.grab()
                    frame = self._cap.read()
                    if frame is None: return jsonify({"error": "OBS frame failed"})
                    self._obstk['fw_raw'] = frame.shape[1]
                    self._obstk['prev'] = cv2.resize(frame, None, fx=0.5, fy=0.5)
                    # 初始地图ROI验证 (搬自 DeadMaze handle_click)
                    fhalf = self._obstk['prev']
                    fx, fy, init_conf = _orb_vs_map(fhalf, sim_x, sim_y, window=800)
                    if init_conf > 0.15:
                        self._obstk['pos'] = [fx, fy]
                        print(f"[OBS-Track] INIT map锚定 ({fx},{fy}) conf={init_conf:.3f}")
                    else:
                        self._obstk['pos'] = [sim_x, sim_y]
                        print(f"[OBS-Track] INIT fallback sim=({sim_x},{sim_y})")
                    return jsonify({"pos": self._obstk['pos'], "dxy": [0,0], "conf": init_conf,
                        "method": f"OBS init conf={init_conf:.2f}"})

                # 读帧 (搬自 DeadMaze _get_frame)
                for _ in range(10): self._cap.grab()
                frame = self._cap.read()
            if frame is None: return jsonify({"error": "OBS frame failed"})

            # DEBUG: 存连续帧做对比
            if self._obstk['fno'] in (1, 5, 10):
                dbg = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    f"obs_track_{self._obstk['fno']:04d}.png")
                cv2.imwrite(dbg, frame)
                print(f"[OBS-Track] SAVED {dbg}")

            curr = cv2.resize(frame, None, fx=0.5, fy=0.5)
            prev = self._obstk['prev']

            # DEBUG: 像素级验证前后帧是否真的不同
            diff = np.abs(curr.astype(np.float32) - prev.astype(np.float32)).mean()
            print(f"[OBS-Track] PIXEL-DIFF prev_vs_curr = {diff:.1f} (0=identical, >5=different)")

            # === Step 1: ORB帧间位移 (搬自 DeadMaze _orb_displacement) ===
            flow_dx, flow_dy, flow_conf = _orb_displacement(prev, curr)
            pred_x = self._obstk['pos'][0] + flow_dx / 0.5
            pred_y = self._obstk['pos'][1] + flow_dy / 0.5

            # === Step 2: 地图ROI ORB匹配定锚 (搬自 DeadMaze _orb_vs_map) ===
            fx, fy, map_conf = _orb_vs_map(curr, pred_x, pred_y, window=800)

            # === Step 3: 选结果 (搬自 DeadMaze track) ===
            if map_conf > 0.30:
                self._obstk['pos'] = [fx, fy]
            elif flow_conf > 0.30:
                self._obstk['pos'] = [int(pred_x), int(pred_y)]
            # clamp
            self._obstk['pos'][0] = max(0, min(self._mw-1, self._obstk['pos'][0]))
            self._obstk['pos'][1] = max(0, min(self._mh-1, self._obstk['pos'][1]))

            self._obstk['prev'] = curr
            self._obstk['fno'] += 1
            print(f"[OBS-Track] raw={frame.shape[1]}x{frame.shape[0]} fw_raw={self._obstk['fw_raw']} "
                  f"pos=({self._obstk['pos'][0]},{self._obstk['pos'][1]}) "
                  f"flow=({flow_dx:.1f},{flow_dy:.1f}) fc={flow_conf:.2f} mc={map_conf:.2f}")
            return jsonify({
                "pos": self._obstk['pos'],
                "dxy": [round(flow_dx/0.5), round(flow_dy/0.5)],
                "conf": round(max(flow_conf, map_conf), 2),
                "method": f"OBS fc={flow_conf:.2f} mc={map_conf:.2f}"
            })

        # 视口追踪: 服务端直接从大地图渲染视口 → ORB光流定位
        @self._app.route("/api/track_frame", methods=["POST"])
        def api_track_frame():
            """服务端从地图渲染视口(640x360于sim处), ORB帧间光流追踪位移 → 返回绝对坐标"""
            import cv2, numpy as np
            if self._map_image is None:
                return jsonify({"error": "need --map"})
            data = request.get_json() or {}
            px = int(data.get("x", 0))
            py = int(data.get("y", 0))
            VW, VH = 640, 360

            # 初始化
            if not hasattr(self, '_stk'):
                self._map_full = cv2.imread(self._map_image)
                self._mh, self._mw = self._map_full.shape[:2]
                # 确定性噪底: 零均值, 避免clip到255导致纹理消失
                rng = np.random.RandomState(42)
                self._noise = rng.randint(-40, 41, (self._mh, self._mw), dtype=np.int16)
                self._stk = {'prev': None, 'fno': 0,
                    'pos': [px, py],
                    'orb': cv2.ORB_create(nfeatures=5000, fastThreshold=5),
                    'matcher': cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)}

            # 从大地图渲染视口: 取(py-H/2 : py+H/2, px-W/2 : px+W/2)区域
            y1, y2 = py - VH//2, py + VH//2
            x1, x2 = px - VW//2, px + VW//2
            # clamp到地图边界
            py1, py2 = max(0,y1), min(self._mh,y2)
            px1, px2 = max(0,x1), min(self._mw,x2)
            viewport = np.zeros((VH, VW, 3), dtype=np.uint8)
            dy_src = py1 - y1  # 源图在viewport中的偏移
            dx_src = px1 - x1
            h = py2 - py1
            w = px2 - px1
            if h > 0 and w > 0:
                viewport[dy_src:dy_src+h, dx_src:dx_src+w] = self._map_full[py1:py2, px1:px2]
                # 混入确定性噪底 (每个地图像素有固定噪声, 随视口移动而移动)
                npatch = self._noise[py1:py2, px1:px2]
                npatch = self._noise[py1:py2, px1:px2]
                for c in range(3):
                    ch = viewport[dy_src:dy_src+h, dx_src:dx_src+w, c].astype(np.int16)
                    viewport[dy_src:dy_src+h, dx_src:dx_src+w, c] = np.clip(ch + npatch, 0, 255).astype(np.uint8)
            frame = viewport

            # 首帧初始化
            if self._stk['prev'] is None:
                self._stk['prev'] = cv2.resize(frame, None, fx=0.5, fy=0.5)
                self._stk['fw'] = VW
                # DEBUG: save first render
                dbg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stk_frame_init.png")
                cv2.imwrite(dbg, frame)
                print(f"[ServerTrack] INIT saved {dbg} viewport=({x1}:{x2},{y1}:{y2}) map_clip=({px1}:{px2},{py1}:{py2}) src_offset=({dx_src},{dy_src})")
                return jsonify({"pos": [px, py], "dxy": [0,0], "conf": 0,
                    "method": "server init"})

            # 相位相关: 频域匹配检测帧间平移 (低纹理比ORB更鲁棒)
            curr = cv2.resize(frame, None, fx=0.5, fy=0.5)
            curr_gray = cv2.cvtColor(curr, cv2.COLOR_BGR2GRAY)
            prev_gray = cv2.cvtColor(self._stk['prev'], cv2.COLOR_BGR2GRAY)
            prev_f = prev_gray.astype(np.float32)
            curr_f = curr_gray.astype(np.float32)
            # Hanning窗口减少边缘效应
            hann_w = np.hanning(prev_f.shape[1])
            hann_h = np.hanning(prev_f.shape[0])
            prev_f *= np.outer(hann_h, hann_w)
            curr_f *= np.outer(hann_h, hann_w)
            shift, response = cv2.phaseCorrelate(prev_f, curr_f)
            dx, dy = shift[0], shift[1]
            flow_conf = min(response, 1.0)
            # DEBUG
            if self._stk['fno'] <= 2:
                print(f"[ServerTrack] phase shift=({dx:.2f},{dy:.2f}) response={response:.3f}")

            # 半分辨率位移 → 全分辨率 → 地图坐标 (viewport 1:1 对地图, 方向取反)
            map_dx = -dx * 2
            map_dy = -dy * 2
            if flow_conf > 0.30:
                self._stk['pos'][0] += round(map_dx)
                self._stk['pos'][1] += round(map_dy)

            self._stk['prev'] = curr
            self._stk['fno'] += 1
            print(f"[ServerTrack] fno={self._stk['fno']} shift=({dx:.2f},{dy:.2f}) resp={flow_conf:.2f} "
                  f"mapD=({map_dx:.0f},{map_dy:.0f}) pos=({self._stk['pos'][0]},{self._stk['pos'][1]})")
            return jsonify({
                "pos": self._stk['pos'],
                "dxy": [round(map_dx), round(map_dy)],
                "conf": round(flow_conf, 2),
                "method": f"server flow c={flow_conf:.2f}"
            })

        # OBS 实时预览
        @self._app.route("/api/capture")
        def api_capture():
            import base64, cv2 as _cv
            if self._cap is None:
                return jsonify({"error": "no OBS camera. Open OBS Studio, add Window Capture of browser, start Virtual Camera"})
            with self._cam_lock:
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

