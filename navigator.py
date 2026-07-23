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
class SkillCooldown:
    """技能冷却管理器 — 4个技能(1/2/3/4键), 各自有冷却时间"""
    def __init__(self):
        self.cooldowns = [3.0, 5.0, 8.0, 12.0]  # a, b, c, d秒
        self.last_used = [0.0, 0.0, 0.0, 0.0]
        self.enabled = True

    def use(self, idx, ctrl=None):
        now = time.time()
        if not self.is_ready(idx, now): return False
        self.last_used[idx] = now
        if ctrl:
            vk = [ctrl.VK_1, ctrl.VK_2, ctrl.VK_3,
                  getattr(ctrl, 'VK_4', ord('4'))][idx]
            try:
                ctrl.press(vk, 0.1)
                print(f"[技能] skill_{idx+1} (冷却{self.cooldowns[idx]}s)")
            except Exception as e:
                print(f"[技能] 失败: {e}"); return False
        return True

    def is_ready(self, idx, now=None):
        if now is None: now = time.time()
        return (now - self.last_used[idx]) >= self.cooldowns[idx]

    def remaining(self, idx, now=None):
        if now is None: now = time.time()
        return max(0, self.cooldowns[idx] - (now - self.last_used[idx]))

    def all_ready(self, now=None):
        return [i for i in range(4) if self.is_ready(i, now)]

    def update(self, idx, val):
        self.cooldowns[idx] = max(0.5, float(val))
# ============================================================

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
        self.waypoints = []         # 中间途径点 [(x,y), ...]
        self.path = None            # 当前段路径 [(x,y)]
        self.grid_path = None       # 网格坐标路径
        self.current_waypoint = 0   # 当前段内途径点索引
        self.wp_index = 0           # 当前在哪个途径点(段索引)
        # 完整路线: start → waypoints[0] → waypoints[1] → ... → goal

        # 返航状态
        self.returning_home = False

        # 显示
        self.scale = min(1000 / self.w, 750 / self.h, 0.5)
        self.offset_x = 0
        self.offset_y = 0
        self.status_msg = "点击地图设定起点和终点"
        self.supply_info = None  # 补给状态
        self.skills = SkillCooldown()  # 技能冷却
        self.yolo_disp = None       # YOLO检测画面 (缩小后)
        self.zombie_counts = {}     # 僵尸种类→数量
        self.last_waypoint_time = 0 # 到达途径点的时间戳

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
    def _plan_segment(self, seg_from, seg_to):
        """规划一段 A* 路径"""
        gs = self.to_grid(*seg_from)
        gg = self.to_grid(*seg_to)
        if self.grid[gs[1], gs[0]] == 0:
            snap = self._snap_to_reachable(gs)
            if snap is None: return None
            gs = snap
        if self.grid[gg[1], gg[0]] == 0:
            snap = self._snap_to_reachable(gg)
            if snap is None: return None
            gg = snap
        gp = astar(self.grid, gs, gg)
        return [self.to_image(*p) for p in gp] if gp else None

    def _plan_next_segment(self):
        """规划当前段: 从当前位置到下一个目标点"""
        if self.wp_index < len(self.waypoints):
            target = self.waypoints[self.wp_index]
            tag = f"WP{self.wp_index+1}"
        else:
            target = self.goal
            tag = "终点"
        cur = self.position if self.position else self.start
        seg = self._plan_segment(cur, target)
        if seg is None:
            print(f"[巡逻] -> {tag} 规划失败!")
            return False
        self.path = seg
        self.current_waypoint = 0
        print(f"[巡逻] -> {tag} ({len(seg)}步)")
        return True

    def _plan_patrol(self):
        """初始化巡逻: 验证可达, 规划第一段"""
        if self.start is None:
            return False
        if not self.waypoints and self.goal is None:
            return False
        self.wp_index = 0
        if not self._plan_next_segment():
            return False
        n = len(self.waypoints)
        if n:
            wps = " -> ".join([f"WP{i+1}" for i in range(n)])
            print(f"[巡逻] 路线: 起点 -> {wps}" +
                  (f" -> 终点" if self.goal else " (循环)"))
        else:
            print(f"[巡逻] 路线: 起点 -> 终点")
        self.state = self.STATE_READY
        return True

    def plan_path(self):
        """兼容旧接口"""
        if self.goal is None:
            return False
        self.waypoints = []
        return self._plan_patrol()

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
        """到达火堆后: YOLO点击火堆 → OCR确认'开' → 补给决策循环"""
        if not self.yolo or not self._game_hwnd:
            self.status_msg = "返航完成 (无YOLO/窗口)"; self.supply_info = None
            print(f"[返航] {self.status_msg}")
            return

        base_dir = os.path.dirname(__file__)

        # 加载偏移
        offset_file = os.path.join(base_dir, 'AImaneuver', 'click_offset.json')
        dx, dy = 0, 0
        if os.path.exists(offset_file):
            off = json.load(open(offset_file))
            dx, dy = off.get('dx', 0), off.get('dy', 0)

        # YOLO检测火堆
        print("[返航] YOLO检测火堆...")
        best_cx, best_cy = None, None
        for _ in range(5):
            ret, frame = self.tracker.cap.read()
            if not ret: continue
            det = self.yolo(frame, verbose=False, conf=0.3)[0]
            for b in det.boxes:
                if self.yolo.names[int(b.cls[0])].lower() == 'campfire':
                    x1, y1, x2, y2 = map(int, b.xyxy[0])
                    best_cx = (x1 + x2) // 2; best_cy = (y1 + y2) // 2
                    break
            if best_cx is not None: break
            time.sleep(0.3)

        if best_cx is None:
            self.status_msg = "返航完成 (YOLO未检测到火堆)"; self.supply_info = None
            print(f"[返航] {self.status_msg}"); return

        # 多点随机点击火堆附近, 直到OCR检测到"开"
        import random
        opened = False
        for i in range(8):
            rx = best_cx + dx + random.randint(-100, 100)
            ry = best_cy + dy + random.randint(-100, 100)
            lp = _wa.MAKELONG(rx, ry)
            _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONDOWN, 0, lp)
            time.sleep(0.05)
            _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONUP, 0, lp)
            print(f"[返航] 点击#{i+1} ({rx},{ry})")
            time.sleep(1.5)
            if self._confirm_open():
                opened = True; break
            print(f"[返航] 点击#{i+1} 未检测到'开', 继续...")

        if not opened:
            self.status_msg = "返航完成 (8次点击未检测到'开')"; self.supply_info = None
            print(f"[返航] {self.status_msg}"); return

        print("=" * 40 + "\n  ✅ 进入火堆, 开始补给决策\n" + "=" * 40)

        # ===== 补给循环 =====
        self._supply_loop(base_dir)

    # ----------------------------------------------------------
    def _confirm_open(self):
        """OCR确认火堆界面'开'字 (使用标定的Open ROI)"""
        if not HAS_TESSERACT: return True  # 无Tesseract则跳过
        ret, f2 = self.tracker.cap.read()
        if not ret: return False
        # 加载标定的Open ROI (默认300,300,40,30)
        ox, oy, ow, oh = 300, 300, 40, 30
        roi_file = os.path.join(os.path.dirname(__file__), 'AImaneuver', 'ocr_reader_roi.json')
        if os.path.exists(roi_file):
            saved = json.load(open(roi_file))
            for r in saved:
                if r[0] == "Open":
                    ox, oy, ow, oh = int(r[1]), int(r[2]), int(r[3]), int(r[4])
                    break
        roi = f2[oy:oy+oh, ox:ox+ow]
        if roi.size == 0: return False
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        big = cv2.resize(gray, (ow*5, oh*5), interpolation=cv2.INTER_CUBIC)
        _, th = cv2.threshold(big, 127, 255, cv2.THRESH_BINARY)
        txt = _pt.image_to_string(th, lang='chi_sim', config='--psm 6').strip()
        print(f"[返航] OCR ROI({ox},{oy},{ow}x{oh}) ='{txt}'")
        return '开' in txt

    # ----------------------------------------------------------
    def _supply_loop(self, base_dir):
        """补给决策主循环: 读状态 → 扫食物 → 决策 → 用户确认 → 吃/离开"""
        import easyocr, re

        # 加载配置
        cp_file = os.path.join(base_dir, 'AImaneuver', 'click_points.json')
        click_pts = json.load(open(cp_file))
        food_roi_file = os.path.join(base_dir, 'AImaneuver', 'food_ocr_roi.json')
        FOOD_ROI = json.load(open(food_roi_file)) if os.path.exists(food_roi_file) else [1016, 436, 298, 164]

        STATUS_REGIONS = [
            ("Hunger", 1713, 1048, 50, 25),
            ("Thirst", 1635, 1048, 50, 25),
        ]
        status_roi_file = os.path.join(base_dir, 'AImaneuver', 'ocr_reader_roi.json')
        if os.path.exists(status_roi_file):
            saved = json.load(open(status_roi_file))
            for r in saved:
                for i, orig in enumerate(STATUS_REGIONS):
                    if orig[0] == r[0]: STATUS_REGIONS[i] = tuple(r[:5]); break

        # 垂直拖拽: C1从y=340下滑, C2从y=460上滑
        FOOD_SLOTS = [
            ("1-1", 885, 383, 340), ("1-2", 900, 383, 340),
            ("1-3", 950, 383, 340), ("1-4", 970, 383, 340),
            ("2-1", 885, 423, 460), ("2-2", 900, 423, 460),
            ("2-3", 950, 423, 460), ("2-4", 970, 423, 460),
        ]
        LEAVE = click_pts.get("leave_campfire", {"x": 920, "y": 313})

        print("[补给] EasyOCR(chinese)...", end=" ")
        ocr_zh = easyocr.Reader(["ch_sim"], gpu=True)
        ocr_en = easyocr.Reader(["en"], gpu=True)
        print("OK")

        obs_w, obs_h = 1920, 1080
        for _ in range(3):
            ret, f = self.tracker.cap.read()
            if ret: obs_w, obs_h = f.shape[1], f.shape[0]; break

        cap = self.tracker.cap  # 快捷引用

        def read_hunger_thirst():
            """读取Hunger/Thirst数值"""
            ret, f = cap.read()
            if not ret: return None, None
            vals = {}
            for name, rx, ry, rw, rh in STATUS_REGIONS:
                roi = f[ry:ry+rh, rx:rx+rw]
                if roi.size == 0: continue
                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                big = cv2.resize(gray, (rw*6, rh*6), interpolation=cv2.INTER_CUBIC)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4,4))
                enhanced = clahe.apply(big)
                r = ocr_en.readtext(enhanced, detail=1, allowlist="0123456789")
                if r:
                    v = r[0][1].strip()
                    if v.isdigit(): vals[name] = int(v)
            return vals.get("Hunger"), vals.get("Thirst")

        def drag_and_ocr(sx, sy, drag_start_y):
            """垂直拖拽 + OBS drain + OCR (验证通过的方案)"""
            # 扫描间清缓冲
            deadline = time.time() + 0.3
            while time.time() < deadline:
                cap.grab(); cv2.waitKey(1)
            cap.retrieve()

            # 垂直拖拽
            lp = _wa.MAKELONG(sx, drag_start_y)
            _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONDOWN, 0, lp)
            time.sleep(0.02)
            for step in range(1, 11):
                cy2 = int(drag_start_y + (sy - drag_start_y) * step / 10)
                lp2 = _wa.MAKELONG(sx, cy2)
                _wa.SendMessage(self._game_hwnd, _wc.WM_MOUSEMOVE, 0, lp2)
                time.sleep(0.03)
            lp3 = _wa.MAKELONG(sx, sy)
            _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONUP, 0, lp3)

            # 持续 drain + 泵消息 (关键!)
            for _ in range(1):
                deadline2 = time.time() + 0.8
                while time.time() < deadline2:
                    cap.grab(); cv2.waitKey(1)
                cap.retrieve()

            # grab 最新帧后 retrieve
            for _ in range(10):
                cap.grab(); cv2.waitKey(1)
            ret, f = cap.retrieve()
            if not ret: return None, None

            # OCR
            rx, ry, rw, rh = [max(1, int(v)) for v in FOOD_ROI]
            rx = min(rx, obs_w-2); ry = min(ry, obs_h-2)
            rw = min(rw, obs_w-rx); rh = min(rh, obs_h-ry)
            roi = f[ry:ry+rh, rx:rx+rw]
            if roi.size == 0: return None, None
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            big = cv2.resize(gray, (rw*3, rh*3), interpolation=cv2.INTER_CUBIC)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4,4))
            enhanced = clahe.apply(big)
            r = ocr_zh.readtext(enhanced, detail=1)
            full_txt = " ".join([line[1] for line in r]) if r else ""

            # OCR 模糊匹配 + 同时提取食物和水
            fm = re.search(r'[食贪饮][物钩饭]\s*[+~-]?\s*(\d+)', full_txt)
            wm = re.search(r'水\s*[+~-]?\s*(\d+)', full_txt)
            food_val = int(fm.group(1)) if fm else None
            water_val = int(wm.group(1)) if wm else None
            return food_val, water_val

        # ===== 虚拟状态追踪 (进入火堆时OCR一次, 后续累加) =====
        init_hunger, init_thirst = read_hunger_thirst()
        virt_hunger = init_hunger or 0
        virt_thirst = init_thirst or 0
        consumed_food_total = 0
        consumed_water_total = 0
        print(f"[补给] 初始状态: Hunger={virt_hunger} Thirst={virt_thirst}")

        # ===== 主循环 =====
        round_num = 0
        while True:
            round_num += 1
            print(f"\n[补给] === 第{round_num}轮 ===")

            # 终止条件 (用虚拟值)
            if virt_hunger > 100 and virt_thirst > 100:
                print(f"[补给] 虚拟饱食+口渴均>100 (H={virt_hunger} T={virt_thirst}), 离开!"); break

            # 扫描食物栏
            items = []
            for slot_name, sx_val, sy_val, drag_start_y in FOOD_SLOTS:
                food_v, water_v = drag_and_ocr(sx_val, sy_val, drag_start_y)
                if food_v is not None or water_v is not None:
                    items.append({
                        "name": slot_name, "food": food_v or 0,
                        "water": water_v or 0,
                        "x": sx_val, "y": sy_val, "drag_start": drag_start_y
                    })
                    parts = []
                    if food_v: parts.append(f"food+{food_v}")
                    if water_v: parts.append(f"water+{water_v}")
                    print(f"  [{slot_name}] {' | '.join(parts)}")
                else:
                    print(f"  [{slot_name}] 空")

            # 决策 (用虚拟值)
            action, choice = self._decide(virt_hunger, virt_thirst, items)
            if action == "leave" or choice is None:
                print(f"[补给] 无可吃食物 (虚拟 H={virt_hunger} T={virt_thirst}), 离开!"); break

            print(f"\n[补给] 推荐: {choice['name']} food+{choice['food']} water+{choice['water']}")
            print(f"[补给] 虚拟饱食={virt_hunger}→{virt_hunger+choice['food']} 口渴={virt_thirst}→{virt_thirst+choice['water']}")
            print(f"[补给] 已消耗总计: food+{consumed_food_total} water+{consumed_water_total}")

            # 更新补给面板显示
            self.supply_info = {
                "init_hunger": init_hunger, "init_thirst": init_thirst,
                "virt_hunger": virt_hunger, "virt_thirst": virt_thirst,
                "consumed_food": consumed_food_total, "consumed_water": consumed_water_total,
                "items": items, "choice": choice, "round": round_num
            }

            # 用户确认 (先刷新窗口显示补给面板)
            canvas = self.render()
            cv2.imshow("Nav", canvas)
            cv2.waitKey(1)
            user_input = input("[补给] 使用此食物? (y=吃 / n=跳过 / q=离开): ").strip().lower()
            if user_input == 'q':
                print("[补给] 用户选择离开"); break
            elif user_input == 'n':
                items = [it for it in items if it["name"] != choice["name"]]
                print(f"[补给] 跳过 {choice['name']}, 重新决策...")
                action2, choice2 = self._decide(virt_hunger, virt_thirst, items)
                if action2 == "leave" or choice2 is None:
                    print("[补给] 无其他可选, 离开!"); break
                choice = choice2
                print(f"[补给] 改用: {choice['name']} food+{choice['food']} water+{choice['water']}")
                canvas2 = self.render()
                cv2.imshow("Nav", canvas2)
                cv2.waitKey(1)
                confirm = input("[补给] 使用此食物? (y/n/q): ").strip().lower()
                if confirm != 'y':
                    print("[补给] 用户取消, 离开!"); break

            # 食用
            print(f"[补给] 食用 {choice['name']}...")
            cx2, cy2 = choice["x"], choice["y"]
            lp = _wa.MAKELONG(cx2, cy2)
            _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONDOWN, 0, lp)
            time.sleep(0.05)
            _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONUP, 0, lp)
            print(f"[补给] 已点击 ({cx2},{cy2}), 等待8秒...")

            # 更新虚拟值
            virt_hunger += choice['food']
            virt_thirst += choice['water']
            consumed_food_total += choice['food']
            consumed_water_total += choice['water']
            time.sleep(8.0)

        # 6. 离开
        lx, ly = LEAVE["x"], LEAVE["y"]
        lp = _wa.MAKELONG(lx, ly)
        _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONDOWN, 0, lp)
        time.sleep(0.05)
        _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONUP, 0, lp)
        self.status_msg = "补给完成, 已离开火堆"
        self.supply_info = None  # 清除补给面板
        print(f"[补给] 点击离开 ({lx},{ly})")
        print("=" * 40 + "\n  ✅ 补给完成!\n" + "=" * 40)

    # ----------------------------------------------------------
    @staticmethod
    def _decide(hunger, thirst, items):
        """补给决策引擎: 返回 ('eat', item) 或 ('leave', None)"""
        if not items:
            return ("leave", None)

        rule1 = []  # 双不超130
        rule2 = []  # 至少一项超130

        for item in items:
            f = item.get("food", 0) or 0
            w = item.get("water", 0) or 0
            if f == 0 and w == 0: continue
            over_h = max(0, hunger + f - 130)
            over_t = max(0, thirst + w - 130)
            total_over = over_h + over_t
            total_benefit = f + w
            if total_over == 0:
                rule1.append((total_benefit, item))
            else:
                rule2.append((total_over, -total_benefit, item))

        if rule1:
            rule1.sort(key=lambda x: -x[0])
            return ("eat", rule1[0][1])
        if rule2:
            rule2.sort(key=lambda x: (x[0], x[1]))
            return ("eat", rule2[0][2])
        return ("leave", None)

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

        # 2. 检查是否到达火堆 (离火堆近就自动交互, 用更大阈值)
        HOME_REACH = int(GOAL_REACH_THRESHOLD * 1.5)
        if self.home:
            hx, hy = self.home
            d_home = np.hypot(px - hx, py - hy)
            if d_home < HOME_REACH:
                tag = "返航" if self.returning_home else "到达火堆"
                print(f"\n{'='*40}\n[{tag}] 距火堆{d_home:.0f}px < {HOME_REACH}px, 触发火堆交互\n{'='*40}")
                self.state = self.STATE_IDLE
                self.returning_home = False
                self._fire_camp_interact()
                return

        # 3. 检查是否到达终点
        gx, gy = self.goal
        d_goal = np.hypot(px - gx, py - gy)
        if d_goal < GOAL_REACH_THRESHOLD:
            # 终点离火堆近? 也触发火堆交互
            if self.home and np.hypot(gx - self.home[0], gy - self.home[1]) < HOME_REACH:
                print(f"\n{'='*40}\n[到达终点] 终点距火堆近, 触发火堆交互\n{'='*40}")
                self.state = self.STATE_IDLE
                self.returning_home = False
                self._fire_camp_interact()
                return
            print(f"[!] 到达终点! (距目标{d_goal:.0f}px)")
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

        # 检查是否到达当前段终点 → 等待3秒 → 切下一段
        if wp_idx >= len(self.path) - 1 and np.hypot(px - wx, py - wy) < WAYPOINT_REACH_THRESHOLD:
            if self.last_waypoint_time == 0:
                self.last_waypoint_time = time.time()
                # 确定当前到达的是哪个目标
                if self.wp_index < len(self.waypoints):
                    tag = f"途径点#{self.wp_index+1}"
                else:
                    tag = "终点"
                print(f"[巡逻] 到达{tag}, 等待3秒...")
            elif time.time() - self.last_waypoint_time >= 3.0:
                self.last_waypoint_time = 0
                # 切到下一个目标
                if self.wp_index < len(self.waypoints):
                    self.wp_index += 1
                    # 如果是循环(无终点)且走完所有途径点: 回到WP0
                    if self.goal is None and self.wp_index >= len(self.waypoints):
                        self.wp_index = 0
                        print("[巡逻] 循环: 回到WP1")
                    self._plan_next_segment()
                else:
                    # 到达终点
                    print(f"[巡逻] 到达终点!")
                    self.state = self.STATE_IDLE
                    self.status_msg = "巡逻完成"
                    return
            self.status_msg = f"等待中 ({time.time()-self.last_waypoint_time:.1f}s/3s)"
            return
        else:
            self.last_waypoint_time = 0

        # 6. YOLO 僵尸检测 (每步检测一次)
        if self.yolo and self.tracker:
            ret, yf = self.tracker.cap.read()
            if ret:
                det = self.yolo(yf, verbose=False, conf=0.3)[0]
                self.yolo_disp = cv2.resize(det.plot(), (200, 120))
                # 统计僵尸
                counts = {}
                for b in det.boxes:
                    name = self.yolo.names[int(b.cls[0])]
                    # 只统计僵尸类 (名字以ZB或Zombie结尾)
                    if 'ZB' in name.upper() or 'ZOMBIE' in name.upper():
                        counts[name] = counts.get(name, 0) + 1
                self.zombie_counts = counts

        # 7. 8方向拟合 + 移动
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

        # 7. 技能自动释放 (冷却好了就放)
        if self.ctrl and self.skills.enabled:
            for idx in self.skills.all_ready():
                self.skills.use(idx, self.ctrl)
                break  # 每步最多放一个技能

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

        # 途径点标记 (蓝色圆点 + 编号)
        for i, wp in enumerate(self.waypoints):
            wpp = self.img2scr(*wp)
            cv2.circle(canvas, wpp, 5, (255, 150, 0), -1)
            cv2.putText(canvas, str(i + 1), (wpp[0] + 8, wpp[1] + 4),
                       FONT, 0.35, (255, 150, 0), 1)

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

        # ---- 补给面板 (火堆补给时显示) ----
        if self.supply_info:
            si = self.supply_info
            # 半透明背景
            bx, by_ = 5, 28
            bw, bh = 280, 220
            overlay = canvas.copy()
            cv2.rectangle(overlay, (bx, by_), (bx + bw, by_ + bh), (30, 30, 30), -1)
            canvas = cv2.addWeighted(canvas, 0.7, overlay, 0.3, 0)
            cv2.rectangle(canvas, (bx, by_), (bx + bw, by_ + bh), (0, 200, 0), 1)

            y = by_ + 16
            cv2.putText(canvas, f"补给 第{si['round']}轮", (bx + 5, y), FONT, 0.45, (0, 255, 0), 1)
            y += 20
            cv2.putText(canvas, f"初始: H={si['init_hunger']} T={si['init_thirst']}",
                       (bx + 5, y), FONT, 0.35, (200, 200, 200), 1)
            y += 16
            cv2.putText(canvas, f"虚拟: H={si['virt_hunger']} T={si['virt_thirst']}",
                       (bx + 5, y), FONT, 0.4, (0, 255, 255), 1)
            y += 16
            cv2.putText(canvas, f"已吃: food+{si['consumed_food']} water+{si['consumed_water']}",
                       (bx + 5, y), FONT, 0.35, (255, 200, 100), 1)
            y += 20

            # 推荐
            ch = si.get('choice')
            if ch:
                cv2.putText(canvas, f"推荐: {ch['name']} f+{ch['food']} w+{ch['water']}",
                           (bx + 5, y), FONT, 0.38, (0, 255, 100), 1)
                y += 18

            # 扫描到的物品
            cv2.putText(canvas, "物品:", (bx + 5, y), FONT, 0.35, (180, 180, 180), 1)
            y += 14
            for it in si.get('items', [])[:8]:
                cv2.putText(canvas,
                           f"  {it['name']}: f+{it['food']} w+{it['water']}",
                           (bx + 5, y), FONT, 0.3,
                           (0, 255, 0) if ch and it['name'] == ch['name'] else (150, 150, 150), 1)
                y += 12

        # ---- 技能冷却面板 ----
        if self.skills:
            sx_, sy_ = VW - 220, 5
            now = time.time()
            cv2.rectangle(canvas, (sx_, sy_), (sx_ + 215, sy_ + 90), (40, 40, 40), -1)
            cv2.rectangle(canvas, (sx_, sy_), (sx_ + 215, sy_ + 90), (0, 200, 200), 1)
            cv2.putText(canvas, "技能冷却", (sx_ + 3, sy_ + 16), FONT, 0.4, (0, 255, 255), 1)
            for i in range(4):
                cd = self.skills.cooldowns[i]
                rem = self.skills.remaining(i, now)
                ready = rem <= 0
                col = (0, 255, 0) if ready else (255, 100, 100)
                bar_w = int(100 * (1 - rem / cd)) if cd > 0 else 100
                cv2.putText(canvas, f"skill_{i+1}:", (sx_ + 3, sy_ + 34 + i * 16),
                           FONT, 0.3, (200, 200, 200), 1)
                # 冷却条
                bx2, by2 = sx_ + 55, sy_ + 37 + i * 16
                cv2.rectangle(canvas, (bx2, by2 - 8), (bx2 + 100, by2), (60, 60, 60), -1)
                if bar_w > 0:
                    cv2.rectangle(canvas, (bx2, by2 - 8), (bx2 + bar_w, by2), col, -1)
                txt2 = "READY" if ready else f"{rem:.1f}s"
                cv2.putText(canvas, txt2, (bx2 + 105, by2 + 1), FONT, 0.28, col, 1)

        # ---- YOLO 僵尸检测画面 ----
        if self.yolo_disp is not None:
            yx, yy = VW - 210, 100
            yd_h, yd_w = self.yolo_disp.shape[:2]
            canvas[yy:yy + yd_h, yx:yx + yd_w] = self.yolo_disp
            cv2.rectangle(canvas, (yx, yy), (yx + yd_w, yy + yd_h), (0, 255, 0), 1)
            cv2.putText(canvas, "YOLO", (yx, yy - 4), FONT, 0.35, (0, 255, 0), 1)

            # 僵尸统计
            zy = yy + yd_h + 5
            cv2.putText(canvas, "僵尸:", (yx, zy), FONT, 0.3, (255, 200, 100), 1)
            zy += 12
            if self.zombie_counts:
                for name_, count_ in sorted(self.zombie_counts.items()):
                    # 简化名称
                    short = name_.replace('ZB', '').replace('Zombie', 'Z')
                    cv2.putText(canvas, f"  {short}: {count_}",
                               (yx, zy), FONT, 0.28, (200, 200, 200), 1)
                    zy += 11
            else:
                cv2.putText(canvas, "  (无)", (yx, zy), FONT, 0.28, (150, 150, 150), 1)

        help_text = "左=起点 右=终点 Enter=导航 空格=暂停 H=返航 IJKL=平移 +/-=缩放 Q=退出"
        cv2.putText(canvas, help_text,
                   (5, VH - 6), FONT, 0.3, (180, 180, 180), 1)

        return canvas

    # ----------------------------------------------------------
    def on_mouse(self, event, sx, sy, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            pt = self.scr2img(sx, sy)
            if self.start is None:
                # 第一次左键 = 起点
                self.start = pt
                self.status_msg = f"起点=({pt[0]},{pt[1]})"
                print(f"[起点] {pt}")
            else:
                # 后续左键 = 添加途径点
                self.waypoints.append(pt)
                i = len(self.waypoints)
                self.status_msg = f"途径点#{i}=({pt[0]},{pt[1]})"
                print(f"[途径点#{i}] {pt}")
        elif event == cv2.EVENT_RBUTTONDOWN:
            self.goal = self.scr2img(sx, sy)
            self.status_msg = f"终点=({self.goal[0]},{self.goal[1]})"
            print(f"[终点] {self.goal}")
            if self.start:
                self._plan_patrol()  # 改为多段规划
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

    # ★ 技能冷却时间配置
    cd_file = os.path.join(os.path.dirname(__file__), 'skill_cooldowns.json')
    default_cds = [3, 5, 8, 12]
    if os.path.exists(cd_file):
        try:
            saved = json.load(open(cd_file))
            default_cds = saved.get('cooldowns', default_cds)
            print(f"[技能] 加载冷却配置: {default_cds}")
        except Exception:
            pass
    print(f"\n当前技能冷却: {default_cds}")
    inp = input("修改冷却时间? (直接回车跳过, 或输入4个数字如 3,5,8,12): ").strip()
    if inp:
        try:
            parts = [float(x.strip()) for x in inp.split(',')]
            if len(parts) == 4:
                default_cds = [max(0.5, p) for p in parts]
                json.dump({'cooldowns': default_cds}, open(cd_file, 'w'))
                print(f"[技能] 已保存: {default_cds}")
        except Exception:
            print("[技能] 格式错误, 使用默认值")
    nav.skills.cooldowns = default_cds[:]
    print(f"[技能] 冷却时间: {default_cds}\n")

    print("\n=== 路径导航闭环 ===")
    print("左键=起点 | 右键=终点(A*规划)")
    print("Enter=开始导航 | 空格=暂停 | Esc=停止 | Q=退出")
    print("H=返航 | R=重置 | 1/2/3/4=释放技能 | E=技能开关 | IJKL=平移 | +/-=缩放\n")

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

        # 1/2/3/4 = 手动释放技能 (测试)
        elif key in (ord('1'), ord('2'), ord('3'), ord('4')):
            idx = key - ord('1')
            if nav.ctrl and nav.skills.enabled:
                if nav.skills.use(idx, nav.ctrl):
                    print(f"[技能] skill_{idx+1} 手动释放!")
                else:
                    rem = nav.skills.remaining(idx)
                    print(f"[技能] skill_{idx+1} 冷却中 ({rem:.1f}s)")

        # E = 切换技能开关
        elif key in (ord('e'), ord('E')):
            nav.skills.enabled = not nav.skills.enabled
            state = "ON" if nav.skills.enabled else "OFF"
            print(f"[技能] 自动释放: {state}")

        # R = 重置 (清除起点/终点/路径)
        elif key in (ord('r'), ord('R')):
            nav.start = None
            nav.goal = None
            nav.waypoints = []
            nav.path = None
            nav.current_waypoint = 0
            nav.wp_index = 0
            nav.last_waypoint_time = 0
            nav.state = nav.STATE_IDLE
            nav.returning_home = False
            nav.status_msg = "已重置, 请重新设定起点/途径点/终点"
            print("[重置] 起点/途径点/终点/路径已清除")

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
