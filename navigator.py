"""
DeadMaze - 路径导航闭环
实时定位 + A* 路径 + 8方向拟合 + 后台操控

流程:
  1. 在地图上点起点 → 点终点 → A* 规划路径
  2. 自动追踪实时位置 → 找下一个路标 → 8方向拟合 → 按键移动
  3. 偏离路径超过阈值 → 重新规划
  4. 到达终点 → 停止

操作:
  左键 = 起点 | 右键 = 终点 | Enter = 开始导航
  空格 = 暂停/继续 | Esc = 停止 | Q = 退出
  H = 返航到火堆 | IJKL = 平移 | +/- = 缩放
"""

# ============================================================
# 阈值配置（调试时修改这里）
# ============================================================
WAYPOINT_REACH_THRESHOLD = 25     # 像素，到达路标的判定距离
PATH_DEVIATION_THRESHOLD = 60    # 像素，偏离路径多久重规划
MOVE_DURATION = 0.5            # 秒，每次按键时长
TRACK_INTERVAL = 0.3             # 秒，追踪间隔（自动模式）
LOOKAHEAD_DIST = 90           # 像素，向前看多少个像素选路标
SHRINK = 80                   # 缩边像素(0=贴墙)
GOAL_REACH_THRESHOLD = 100     # 终点到达阈值
# ============================================================

import os
import sys
import time
import heapq
import json
import argparse

import cv2
import numpy as np

# 后台操控
try:
    from game_controller import DeadMazeController
    HAS_CONTROLLER = True
except Exception:
    HAS_CONTROLLER = False
    print("[!] game_controller.py 未加载，仅模拟移动")

# 后台点击 (SendMessage)
import win32gui as _wg
import win32api as _wa
import win32con as _wc

# YOLO / OCR (火堆返航用)
try:
    from ultralytics import YOLO
    HAS_YOLO = True
except Exception:
    HAS_YOLO = False
try:
    import pytesseract as _pt
    _pt.pytesseract.tesseract_cmd = r"E:\Tools\tesseract\tesseract.exe"
    HAS_TESSERACT = True
except Exception:
    HAS_TESSERACT = False


# ============================================================
# 8 方向向量 + 对应按键
# ============================================================
DIR_VECTORS = [
    ( 0, -1, 'W'),           # 0: 上
    ( 1, -1, 'W', 'D'),      # 1: 右上
    ( 1,  0, 'D'),           # 2: 右
    ( 1,  1, 'S', 'D'),      # 3: 右下
    ( 0,  1, 'S'),           # 4: 下
    (-1,  1, 'S', 'A'),      # 5: 左下
    (-1,  0, 'A'),           # 6: 左
    (-1, -1, 'W', 'A'),      # 7: 左上
]


def best_direction(dx, dy):
    """向量 (dx, dy) → 最接近的8方向索引"""
    best_i = 0
    best_dot = -999
    for i, (vx, vy, *_) in enumerate(DIR_VECTORS):
        d = vx * dx + vy * dy
        if d > best_dot:
            best_dot = d
            best_i = i
    return best_i


# ============================================================
# A* 寻路
# ============================================================
def astar(grid, start, goal):
    h, w = grid.shape
    visited = np.zeros((h, w), dtype=np.uint8)
    parent = np.zeros((h, w, 2), dtype=np.int32)
    dirs = [(0, 1), (1, 0), (0, -1), (-1, 0),
            (1, 1), (1, -1), (-1, 1), (-1, -1)]

    def hh(p):
        return np.hypot(p[0] - goal[0], p[1] - goal[1])

    heap = [(hh(start), 0, start[0], start[1])]
    visited[start[1], start[0]] = 1

    while heap:
        _, cost, x, y = heapq.heappop(heap)
        if (x, y) == goal:
            path = [(x, y)]
            while (x, y) != start:
                px, py = parent[y, x]
                path.append((px, py))
                x, y = px, py
            path.reverse()
            return path
        for dx, dy in dirs:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and grid[ny, nx] > 0 and not visited[ny, nx]:
                visited[ny, nx] = 1
                mc = 1.414 if dx != 0 and dy != 0 else 1.0
                nc = cost + mc
                heapq.heappush(heap, (nc + hh((nx, ny)), nc, nx, ny))
                parent[ny, nx] = (x, y)
    return None


# ============================================================
# 导航器
# ============================================================
class Navigator:
    def __init__(self, reachable_path, map_path, camera_id=1):
        # 加载可达图
        self.reachable = cv2.imread(reachable_path, cv2.IMREAD_GRAYSCALE)
        if self.reachable is None:
            raise FileNotFoundError(f"可达图: {reachable_path}")
        self.h, self.w = self.reachable.shape[:2]

        # 降采样 A* 网格
        self.DS = 4
        h2, w2 = self.h // self.DS, self.w // self.DS
        small = cv2.resize(self.reachable, (w2, h2),
                           interpolation=cv2.INTER_NEAREST)
        _, small = cv2.threshold(small, 127, 255, cv2.THRESH_BINARY)
        if SHRINK > 0:
            iters = int(np.ceil(SHRINK / self.DS))
            small = cv2.erode(small, np.ones((3, 3), np.uint8), iterations=iters)
        self.grid = small
        pct = np.count_nonzero(self.grid) / (w2 * h2) * 100
        print(f"[网格] {w2}x{h2} shrink={SHRINK}px 可行走={pct:.1f}%")

        # 火堆坐标
        base = os.path.splitext(reachable_path)[0]
        cf_file = base + '_campfire.json'
        if not os.path.exists(cf_file):
            cf_file = 'map_output_campfire.json'
        self.home = None
        if os.path.exists(cf_file):
            with open(cf_file, encoding='utf-8') as f:
                self.home = tuple(json.load(f))
            print(f"[火堆] {self.home}")

        # 原图（显示用）
        self.map_img = cv2.imread(map_path) if os.path.exists(map_path) else None

        # 后台操控
        self.ctrl = None
        if HAS_CONTROLLER:
            try:
                self.ctrl = DeadMazeController()
                self.ctrl.find_window()
            except Exception as e:
                print(f"[!] 控制器: {e}")

        # 自动检测OBS摄像头
        _cfg = os.path.join(os.path.dirname(__file__),
                           'AImaneuver', 'camera_config.json')
        if os.path.exists(_cfg):
            camera_id = json.load(open(_cfg)).get('obs_cam_id', 1)

        # 追踪器
        from map_tracker import Tracker
        self.tracker = Tracker(map_path, camera_id)
        self.position = None  # (cx, cy) 当前位置

        # YOLO (火堆检测)
        self.yolo = None
        if HAS_YOLO:
            yp = os.path.join(os.path.dirname(__file__), 'AImaneuver',
                'runs', 'detect', 'deadmaze_combat', 'weights', 'best.pt')
            if os.path.exists(yp):
                self.yolo = YOLO(yp)
                print(f"[YOLO] 火堆/僵尸检测已加载")

        # 找游戏窗口 (点击用)
        self._game_hwnd = None
        try:
            self._game_hwnd = _wg.FindWindow(None, "Dead Maze")
            if self._game_hwnd:
                print(f"[Game] 窗口 0x{self._game_hwnd:08X}")
        except Exception:
            pass

        # 状态机
        self.STATE_IDLE = 0
        self.STATE_READY = 1       # 路径已规划，等待开始
        self.STATE_NAVIGATING = 2
        self.STATE_PAUSED = 3
        self.state = self.STATE_IDLE

        self.start = None           # 起点 (原图坐标)
        self.goal = None            # 终点
        self.path = None            # [(x,y)] 原图坐标
        self.grid_path = None       # 网格坐标路径
        self.current_waypoint = 0

        # 返航状态
        self.returning_home = False

        # 显示
        self.scale = min(1000 / self.w, 750 / self.h, 0.5)
        self.offset_x = 0
        self.offset_y = 0
        self.status_msg = "点击地图设定起点和终点"

        # 中键拖拽
        self._dragging = False
        self._dsx = self._dsy = 0
        self._dox = self._doy = 0

    # ----------------------------------------------------------
    # 坐标转换
    # ----------------------------------------------------------
    def to_grid(self, ix, iy):
        return int(ix) // self.DS, int(iy) // self.DS

    def to_image(self, gx, gy):
        return int(gx) * self.DS + self.DS // 2, int(gy) * self.DS + self.DS // 2

    def scr2img(self, sx, sy):
        ix = int((sx - self.offset_x) / self.scale)
        iy = int((sy - self.offset_y) / self.scale)
        return max(0, min(ix, self.w - 1)), max(0, min(iy, self.h - 1))

    def img2scr(self, ix, iy):
        return (int(ix * self.scale + self.offset_x),
                int(iy * self.scale + self.offset_y))

    # ----------------------------------------------------------
    def plan_path(self):
        if self.start is None or self.goal is None:
            return False
        gs = self.to_grid(*self.start)
        gg = self.to_grid(*self.goal)

        # 安全检查：起终点必须在可达区，否则找最近可达点
        if self.grid[gs[1], gs[0]] == 0:
            snapped = self._snap_to_reachable(gs)
            if snapped is None:
                print(f"[A*] 起点({self.start[0]},{self.start[1]})在不可达区，且附近无可达点!")
                self.status_msg = "起点在不可达区"
                return False
            print(f"[A*] 起点不在可达区 → 吸附到 ({snapped[0]*self.DS},{snapped[1]*self.DS})")
            gs = snapped
            self.start = self.to_image(*snapped)

        if self.grid[gg[1], gg[0]] == 0:
            snapped = self._snap_to_reachable(gg)
            if snapped is None:
                print(f"[A*] 终点({self.goal[0]},{self.goal[1]})在不可达区，且附近无可达点!")
                self.status_msg = "终点在不可达区"
                return False
            print(f"[A*] 终点不在可达区 → 吸附到 ({snapped[0]*self.DS},{snapped[1]*self.DS})")
            gg = snapped
            self.goal = self.to_image(*snapped)

        print("[A*] 计算中...")
        self.grid_path = astar(self.grid, gs, gg)
        if self.grid_path:
            self.path = [self.to_image(*p) for p in self.grid_path]
            print(f"[A*] {len(self.path)} waypoints")
            self.current_waypoint = 0
            self.state = self.STATE_READY
            return True
        print("[A*] 无路径")
        return False

    # ----------------------------------------------------------
    def get_next_waypoint(self, px, py):
        """找路径上当前位置前方的路标"""
        best = None
        best_dist = 99999
        for i in range(self.current_waypoint, len(self.path)):
            wx, wy = self.path[i]
            d = np.hypot(wx - px, wy - py)
            if d >= LOOKAHEAD_DIST and d < best_dist:
                best = i
                best_dist = d
        if best is None and self.current_waypoint < len(self.path):
            best = len(self.path) - 1
        return best

    def check_deviation(self, px, py):
        """检查是否偏离路径太远"""
        min_dist = 99999
        end = min(self.current_waypoint + 20, len(self.path))
        for i in range(self.current_waypoint, end):
            wx, wy = self.path[i]
            d = np.hypot(wx - px, wy - py)
            if d < min_dist:
                min_dist = d
        return min_dist > PATH_DEVIATION_THRESHOLD

    # ----------------------------------------------------------
    def _snap_to_reachable(self, gpos, max_radius=100):
        """BFS 从不可达点向外找最近的可达网格坐标，找不到返回 None"""
        gx, gy = int(gpos[0]), int(gpos[1])
        gh, gw = self.grid.shape
        if 0 <= gx < gw and 0 <= gy < gh and self.grid[gy, gx] > 0:
            return (gx, gy)  # 已经可达
        from collections import deque
        visited = np.zeros((gh, gw), dtype=np.uint8)
        q = deque()
        q.append((gx, gy, 0))
        visited[gy, gx] = 1
        while q:
            x, y, dist = q.popleft()
            if dist > max_radius:
                continue
            if self.grid[y, x] > 0:
                return (x, y)
            for dx, dy in [(1,0),(-1,0),(0,1),(0,-1)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < gw and 0 <= ny < gh and not visited[ny, nx]:
                    visited[ny, nx] = 1
                    q.append((nx, ny, dist + 1))
        return None

    # ----------------------------------------------------------
    def _fire_camp_interact(self):
        """到达火堆后: YOLO检测火堆 → 加偏移点击 → OCR确认"""
        if not self.yolo or not self._game_hwnd:
            if not self.yolo:
                self.status_msg = "返航完成 (无YOLO)"
            else:
                self.status_msg = "返航完成 (无游戏窗口)"
            print(f"[返航] {self.status_msg}")
            return

        # 加载偏移
        offset_file = os.path.join(os.path.dirname(__file__),
                                   'AImaneuver', 'click_offset.json')
        dx, dy = 0, 0
        if os.path.exists(offset_file):
            saved = json.load(open(offset_file))
            dx, dy = saved.get('dx', 0), saved.get('dy', 0)

        # YOLO检测火堆
        print("[返航] YOLO检测火堆...")
        best_cx, best_cy = None, None
        for _ in range(5):
            ret, frame = self.tracker.cap.read()
            if not ret:
                continue
            det = self.yolo(frame, verbose=False, conf=0.3)[0]
            for b in det.boxes:
                if self.yolo.names[int(b.cls[0])].lower() == 'campfire':
                    x1, y1, x2, y2 = map(int, b.xyxy[0])
                    best_cx = (x1 + x2) // 2
                    best_cy = (y1 + y2) // 2
                    break
            if best_cx is not None:
                break
            time.sleep(0.3)

        if best_cx is None:
            self.status_msg = "返航完成 (YOLO未检测到火堆)"
            print(f"[返航] {self.status_msg}")
            return

        # 加偏移点击
        cx, cy = best_cx + dx, best_cy + dy
        lp = _wa.MAKELONG(cx, cy)
        _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONDOWN, 0, lp)
        time.sleep(0.05)
        _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONUP, 0, lp)
        print(f"[返航] 点击 ({cx},{cy}) 偏移=({dx},{dy})")
        time.sleep(2.0)

        # OCR检测"开"
        self.status_msg = "返航完成"
        if HAS_TESSERACT:
            ret, f2 = self.tracker.cap.read()
            if ret:
                roi = f2[300:330, 300:340]
                if roi.size > 0:
                    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                    big = cv2.resize(gray, (160, 120), interpolation=cv2.INTER_CUBIC)
                    _, th = cv2.threshold(big, 127, 255, cv2.THRESH_BINARY)
                    txt = _pt.image_to_string(th, lang='chi_sim',
                                              config='--psm 6').strip()
                    print(f"[返航] OCR='{txt}'")
                    if '开' in txt:
                        self.status_msg = "返航成功!"
                        print("=" * 40 + "\n  ✅ 返航成功!\n" + "=" * 40)
                    else:
                        self.status_msg = f"返航完成 (OCR='{txt}')"
        print(f"[返航] {self.status_msg}")

    # ----------------------------------------------------------
    def navigate_step(self):
        """单步导航: 定位 → 找路标 → 移动"""
        if self.state != self.STATE_NAVIGATING:
            return

        # 1. 定位
        if self.tracker.last_position is None:
            self.tracker.last_position = self.start
            self.tracker.need_click = False
            self.tracker.prev_frame = None
        self.tracker.track()
        if self.tracker.last_position:
            self.position = self.tracker.last_position
        px, py = self.position if self.position else self.start
        px, py = int(px), int(py)

        # 2. 检查是否到达火堆 (离火堆近就自动交互)
        if self.home:
            hx, hy = self.home
            if np.hypot(px - hx, py - hy) < GOAL_REACH_THRESHOLD:
                tag = "返航" if self.returning_home else "到达火堆"
                print(f"[{tag}] 到达火堆附近!")
                self.state = self.STATE_IDLE
                self.returning_home = False
                self._fire_camp_interact()
                return

        # 3. 检查是否到达终点
        gx, gy = self.goal
        if np.hypot(px - gx, py - gy) < GOAL_REACH_THRESHOLD:
            print("[!] 到达终点!")
            self.state = self.STATE_IDLE
            self.status_msg = "已到达终点"
            self.returning_home = False
            return

        # 4. 检查偏离
        if self.check_deviation(px, py):
            print(f"[!] 偏离路径 > {PATH_DEVIATION_THRESHOLD}px，重规划")
            # 重规划前松开所有键
            if self.ctrl:
                for vk in [self.ctrl.VK_W, self.ctrl.VK_A,
                           self.ctrl.VK_S, self.ctrl.VK_D]:
                    try:
                        self.ctrl.key_up(vk)
                    except Exception:
                        pass
            self.start = (px, py)
            if not self.plan_path():
                self.status_msg = "重规划失败"
                self.state = self.STATE_IDLE
                return
            self.state = self.STATE_NAVIGATING

        # 5. 找下一个路标
        wp_idx = self.get_next_waypoint(px, py)
        if wp_idx is None:
            self.status_msg = "无路标"
            return
        self.current_waypoint = max(self.current_waypoint, wp_idx - 2)
        wx, wy = self.path[wp_idx]

        # 检查是否到达路标
        if np.hypot(px - wx, py - wy) < WAYPOINT_REACH_THRESHOLD:
            self.current_waypoint = wp_idx + 1
            if self.current_waypoint >= len(self.path):
                self.current_waypoint = len(self.path) - 1

        # 6. 8方向拟合 + 移动
        dx = wx - px
        dy = wy - py
        di = best_direction(dx, dy)
        keys = DIR_VECTORS[di][2:]

        if self.ctrl:
            # 先释放不需要的方向键，再按下需要的键
            all_vks = {
                'W': self.ctrl.VK_W, 'A': self.ctrl.VK_A,
                'S': self.ctrl.VK_S, 'D': self.ctrl.VK_D,
            }
            needed = set(keys)
            for name, vk in all_vks.items():
                if name not in needed:
                    try:
                        self.ctrl.key_up(vk)
                    except Exception:
                        pass
            for k in keys:
                try:
                    self.ctrl.press(
                        getattr(self.ctrl, f'VK_{k}', ord(k)),
                        MOVE_DURATION
                    )
                except Exception:
                    pass
        else:
            pass  # 模拟模式

        self.status_msg = (f"→ ({wx},{wy}) dir={di} "
                          f"Δ({dx:.0f},{dy:.0f}) {keys}")

    # ----------------------------------------------------------
    def render(self):
        VW, VH = 1050, 720
        FONT = cv2.FONT_HERSHEY_SIMPLEX

        # 绘制地图
        if self.map_img is None:
            canvas = np.zeros((VH, VW, 3), dtype=np.uint8)
        else:
            dw = int(self.w * self.scale)
            dh = int(self.h * self.scale)
            s = cv2.resize(self.map_img, (dw, dh))
            canvas = np.zeros((VH, VW, 3), dtype=np.uint8)
            ox, oy = self.offset_x, self.offset_y

            # 源图裁剪区域
            sx1 = max(0, -ox)
            sy1 = max(0, -oy)
            sx2 = min(dw, -ox + VW)
            sy2 = min(dh, -oy + VH)
            # 目标区域
            dx1 = max(0, ox)
            dy1 = max(0, oy)
            dx2 = min(VW, ox + dw)
            dy2 = min(VH, oy + dh)

            pw = min(sx2 - sx1, dx2 - dx1)
            ph = min(sy2 - sy1, dy2 - dy1)
            if pw > 0 and ph > 0:
                canvas[dy1:dy1 + ph, dx1:dx1 + pw] = \
                    s[sy1:sy1 + ph, sx1:sx1 + pw]

        # 可达图叠加（向量化，不再逐像素循环）
        rw = int(self.w * self.scale)
        rh = int(self.h * self.scale)
        rs = cv2.resize(self.reachable, (rw, rh),
                       interpolation=cv2.INTER_NEAREST)
        edges = cv2.Canny(rs, 50, 150)

        # 将 edges 对齐到 canvas
        ox, oy = self.offset_x, self.offset_y
        # edge 在 canvas 中的 ROI
        e_x1 = max(0, ox)
        e_y1 = max(0, oy)
        e_x2 = min(VW, ox + rw)
        e_y2 = min(VH, oy + rh)
        # edge 在 edges 中的对应 ROI
        s_ex1 = max(0, -ox)
        s_ey1 = max(0, -oy)
        s_ex2 = s_ex1 + (e_x2 - e_x1)
        s_ey2 = s_ey1 + (e_y2 - e_y1)

        if s_ex2 > s_ex1 and s_ey2 > s_ey1:
            # 向量化: 用 mask 一次性赋值
            edge_roi = edges[s_ey1:s_ey2, s_ex1:s_ex2]
            mask = edge_roi > 0
            # 只给边缘像素着色 (cyan)
            roi = canvas[e_y1:e_y2, e_x1:e_x2]
            roi[mask] = [200, 200, 0]

        # 路径
        if self.path:
            pts = [self.img2scr(*p) for p in self.path]
            for i in range(1, len(pts)):
                cv2.line(canvas, pts[i - 1], pts[i], (0, 255, 0), 2)
            if self.current_waypoint < len(pts):
                cv2.circle(canvas, pts[self.current_waypoint], 8,
                          (255, 255, 0), -1)

        # 起点 S
        if self.start:
            sp = self.img2scr(*self.start)
            cv2.circle(canvas, sp, 7, (0, 255, 0), -1)
            cv2.putText(canvas, "S", (sp[0] + 10, sp[1]),
                       FONT, 0.5, (0, 255, 0), 2)

        # 终点 G
        if self.goal:
            gp = self.img2scr(*self.goal)
            cv2.circle(canvas, gp, 7, (0, 0, 255), -1)
            cv2.putText(canvas, "G", (gp[0] + 10, gp[1]),
                       FONT, 0.5, (0, 0, 255), 2)

        # 火堆标记
        if self.home:
            hp = self.img2scr(*self.home)
            cv2.drawMarker(canvas, hp, (0, 165, 255),
                          cv2.MARKER_TILTED_CROSS, 12, 2)
            cv2.putText(canvas, "Home", (hp[0] + 10, hp[1]),
                       FONT, 0.4, (0, 165, 255), 1)

        # 实时位置 (黄色圆)
        if self.position:
            tp = self.img2scr(*self.position)
            cv2.circle(canvas, tp, 9, (0, 255, 255), -1)
            cv2.circle(canvas, tp, 11, (255, 255, 255), 2)

        # 状态栏
        state_names = ["空闲", "就绪(按Enter开始)", "导航中", "已暂停"]
        cv2.putText(canvas, f"[{state_names[self.state]}] {self.status_msg}",
                   (5, 18), FONT, 0.38, (0, 255, 0), 1)

        help_text = "左=起点 右=终点 Enter=导航 空格=暂停 H=返航 IJKL=平移 +/-=缩放 Q=退出"
        cv2.putText(canvas, help_text,
                   (5, VH - 6), FONT, 0.3, (180, 180, 180), 1)

        return canvas

    # ----------------------------------------------------------
    def on_mouse(self, event, sx, sy, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.start = self.scr2img(sx, sy)
            self.status_msg = f"起点=({self.start[0]},{self.start[1]})"
            print(self.status_msg)
        elif event == cv2.EVENT_RBUTTONDOWN:
            self.goal = self.scr2img(sx, sy)
            self.status_msg = f"终点=({self.goal[0]},{self.goal[1]})"
            print(self.status_msg)
            if self.start:
                self.plan_path()
        elif event == cv2.EVENT_MBUTTONDOWN:
            self._dragging = True
            self._dsx, self._dsy = sx, sy
            self._dox, self._doy = self.offset_x, self.offset_y
        elif event == cv2.EVENT_MOUSEMOVE and self._dragging:
            self.offset_x = self._dox + (sx - self._dsx)
            self.offset_y = self._doy + (sy - self._dsy)
        elif event == cv2.EVENT_MBUTTONUP:
            self._dragging = False
        elif event == cv2.EVENT_MOUSEWHEEL or event == 10:
            old = self.scale
            if flags > 0:
                self.scale = min(3.0, self.scale * 1.15)
            else:
                self.scale = max(0.03, self.scale / 1.15)
            if old != self.scale:
                r = self.scale / old
                self.offset_x = int(sx - r * (sx - self.offset_x))
                self.offset_y = int(sy - r * (sy - self.offset_y))


# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reachable", nargs="?", default="map_output_reachable.png")
    parser.add_argument("--map", default="map_output.jpg")
    parser.add_argument("-c", "--camera", type=int, default=1)
    args = parser.parse_args()

    if not os.path.exists(args.reachable):
        print(f"[错误] {args.reachable} 不存在")
        sys.exit(1)

    # ★ 清理残留窗口（防止双窗口问题）
    cv2.destroyAllWindows()

    nav = Navigator(args.reachable, args.map, args.camera)

    print("\n=== 路径导航闭环 ===")
    print("左键=起点 | 右键=终点(A*规划)")
    print("Enter=开始导航 | 空格=暂停 | Esc=停止 | Q=退出")
    print("H=返航 | IJKL=平移 | +/-=缩放\n")

    cv2.namedWindow("Nav", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty("Nav", cv2.WND_PROP_TOPMOST, 1)
    cv2.setMouseCallback("Nav", nav.on_mouse)

    last_nav = 0
    print("[定位] 请在地图上点击你的当前位置作为起点...")

    while True:
        canvas = nav.render()
        cv2.imshow("Nav", canvas)
        key = cv2.waitKey(30) & 0xFF

        if key == ord('q') or key == ord('Q'):
            break

        # 缩放
        elif key in (ord('+'), ord('=')):
            nav.scale = min(3.0, nav.scale * 1.15)
        elif key in (ord('-'), ord('_')):
            nav.scale = max(0.03, nav.scale / 1.15)

        # 平移
        elif key == ord('i'):
            nav.offset_y += 30
        elif key == ord('k'):
            nav.offset_y -= 30
        elif key == ord('j'):
            nav.offset_x += 30
        elif key == ord('l'):
            nav.offset_x -= 30

        # Enter = 开始导航
        elif key == 13:
            if nav.state == nav.STATE_READY:
                if nav.ctrl:
                    print("[测试] 发送 W 键 0.2s...")
                    nav.ctrl.press(nav.ctrl.VK_W, 0.2)
                    time.sleep(0.3)
                    print("[测试] 发送 D 键 0.2s...")
                    nav.ctrl.press(nav.ctrl.VK_D, 0.2)
                    time.sleep(0.3)
                    print("[测试] 控制器测试完成，观察角色是否移动")
                nav.state = nav.STATE_NAVIGATING
                nav.returning_home = False
                print("[导航] 开始!")

        # 空格 = 暂停/继续
        elif key == ord(' '):
            if nav.state == nav.STATE_NAVIGATING:
                nav.state = nav.STATE_PAUSED
                print("[暂停]")
            elif nav.state == nav.STATE_PAUSED:
                nav.state = nav.STATE_NAVIGATING
                print("[继续]")

        # H = 返航
        elif key == ord('h') or key == ord('H'):
            if nav.home:
                nav.goal = nav.home
                nav.start = nav.position if nav.position else nav.start
                if nav.plan_path():
                    nav.returning_home = True
                    print(f"[返航] → 火堆 {nav.home}")

        # Esc = 停止
        elif key == 27:
            nav.state = nav.STATE_IDLE
            nav.status_msg = "已停止"
            nav.returning_home = False
            print("[停止]")

        # 导航步进
        if nav.state == nav.STATE_NAVIGATING:
            now = time.time()
            if now - last_nav > TRACK_INTERVAL:
                nav.navigate_step()
                last_nav = now

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
