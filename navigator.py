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
PATH_DEVIATION_THRESHOLD = 100    # 像素，偏离路径多久重规划
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

        # 加载武器ROI标定
        wp_roi_file = os.path.join(os.path.dirname(__file__), 'weapon_roi.json')
        if os.path.exists(wp_roi_file):
            wp_saved = json.load(open(wp_roi_file))
            self.WEAPON_ROI = wp_saved.get("roi", self.WEAPON_ROI)
            self.WEAPON_TOLERANCE = wp_saved.get("tol", self.WEAPON_TOLERANCE)
            self.WEAPON_EMPTY_THRESHOLD = wp_saved.get("thr", self.WEAPON_EMPTY_THRESHOLD)
            print(f"[武器] 加载标定: ROI={self.WEAPON_ROI} Tol={self.WEAPON_TOLERANCE}")

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
        self.status_disp = None     # 状态窗画面(OBS+OCR框)
        self._last_frame = None     # 最新OBS帧
        self.zombie_counts = {}     # 僵尸种类→数量
        self.last_waypoint_time = 0 # 到达途径点的时间戳
        self.loop_patrol = False    # 循环巡逻模式
        self._patrol_start = None   # 巡逻起点(循环时回到这里)

        # ---- 战斗系统 ----
        self.combat_state = None     # None | 'chasing' | 'attacking'
        self.skip_count = 0          # 跳过途径点计数
        self.combat_target = None    # (cx, cy, name) 当前追击僵尸
        self.last_attack_time = 0    # 上次攻击时间
        self.chase_start_time = 0    # 当前目标开始追击时间
        self.waypoint_combat_start = 0  # 途径点战斗开始时间
        self.zombie_list = []        # [(cx, cy, name), ...] 画面中僵尸列表
        self._last_weapon_check = 0  # 上次武器检测时间
        self._weapon_empty = False   # 武器是否耗尽
        self._weapon_stop = False    # 武器耗尽→停止程序
        self._weapon_manual = False  # 手动模式(不自动整理)
        self.hp_pct = 100            # 血量百分比
        self.hunger_val = 0          # 饱食度
        self.thirst_val = 0          # 口渴度
        self.stamina_val = 0         # 耐力
        self.threat_val = 0          # 威胁度
        self._hp_roi = None          # HP检测ROI
        self._hunger_roi = None      # 饱食度ROI
        self._thirst_roi = None      # 口渴度ROI
        self._stamina_roi = None     # 耐力ROI
        self._ocr_en = None          # EasyOCR英文(状态读取)
        self._post_supply_check = False  # 补给后检查标志
        self._low_stat_triggered = False  # 低状态返航已触发
        # ROI 编辑模式
        self._roi_edit = False       # True=编辑模式
        self._roi_sel = 0            # 当前选中的ROI索引
        self._roi_list = []          # [(name,x,y,w,h), ...] 可编辑ROI列表
        self._cfg_sel = 0            # 当前选中的配置参数索引

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
    def _do_plan(self):
        """A*规划: 从当前位置到 self.goal"""
        if self.start is None or self.goal is None:
            return False
        gs = self.to_grid(*self.start)
        gg = self.to_grid(*self.goal)
        if self.grid[gs[1], gs[0]] == 0:
            snap = self._snap_to_reachable(gs)
            if snap is None: return False
            gs = snap
        if self.grid[gg[1], gg[0]] == 0:
            snap = self._snap_to_reachable(gg)
            if snap is None: return False
            gg = snap
        gp = astar(self.grid, gs, gg)
        if gp:
            self.path = [self.to_image(*p) for p in gp]
            self.current_waypoint = 0
            n_wp = len(self.waypoints)
            tag = f"WP{self.wp_index+1}/{n_wp}" if n_wp else "终点"
            print(f"[A*] {len(self.path)}步 -> {tag}")
            self.state = self.STATE_READY
            return True
        return False

    def plan_path(self, to_goal_only=False):
        """规划到 goal(或途径点列表) 的路径"""
        if self.start is None:
            return False
        # 多途径点: 取下一个途径点作为 goal
        if self.waypoints and not to_goal_only:
            self.wp_index = 0
            self.goal = self.waypoints[0]
        elif self.goal is None:
            return False
        return self._do_plan()

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
    def _fire_camp_interact_no_supply(self):
        """武器耗尽进入火堆 — 只进入不补给"""
        import random
        if not self.yolo or not self._game_hwnd: return
        base_dir = os.path.dirname(__file__)
        offset_file = os.path.join(base_dir, 'AImaneuver', 'click_offset.json')
        dx, dy = 0, 0
        if os.path.exists(offset_file):
            off = json.load(open(offset_file))
            dx, dy = off.get('dx', 0), off.get('dy', 0)
        # YOLO检测火堆
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
        if best_cx is None: return
        # 点击直到进入
        for i in range(8):
            rx = best_cx + dx + random.randint(-100, 100)
            ry = best_cy + dy + random.randint(-100, 100)
            lp = _wa.MAKELONG(rx, ry)
            _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONDOWN, 0, lp)
            time.sleep(0.05)
            _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONUP, 0, lp)
            time.sleep(1.5)
            if self._confirm_open():
                print(f"\n{'='*60}")
                print(f"  !! 武器耗尽, 已进入火堆, 程序终止 !!")
                print(f"  请更换武器后重新运行")
                print(f"{'='*60}\n")
                self.status_msg = "!! STOP: 武器耗尽(已在火堆)"
                self.state = self.STATE_IDLE
                self.loop_patrol = False
                return
        print(f"\n{'='*60}")
        print(f"  !! 武器耗尽, 进火堆失败, 程序终止 !!")
        print(f"{'='*60}\n")
        self.status_msg = "!! STOP: 武器耗尽(进火堆失败)"
        self.state = self.STATE_IDLE
        self.loop_patrol = False

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
                r = ocr_en.readtext(big, detail=1, allowlist="0123456789")
                if r:
                    # 拼接所有数字 + 约束到200
                    v = "".join([x[1].strip() for x in r if x[1].strip().isdigit()])
                    if v.isdigit():
                        val = int(v)
                        if val > 200: val = int(str(val)[:2])
                        vals[name] = val
            return vals.get("Hunger"), vals.get("Thirst")

        def drag_and_ocr(sx, sy, drag_start_y):
            """垂直拖拽 + OBS drain + OCR (验证通过的方案)"""
            # 扫描间清缓冲 (1秒, 仿supply_step_test主循环效果)
            deadline = time.time() + 1.0
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

            # 持续 drain + 泵消息
            for _ in range(3):
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
        eat_count = 0  # 连续食用计数(3次后强制重进火堆)
        while True:
            round_num += 1
            print(f"\n[补给] === 第{round_num}轮 (已吃{eat_count}/3) ===")

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

            print(f"\n[补给] Rec: {choice['name']} food+{choice['food']} water+{choice['water']}")
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
            is_simulate = False  # 每轮重置
            canvas = self.render()
            cv2.imshow("Nav", canvas)
            cv2.waitKey(1)
            user_input = input("[补给] 使用? (y=吃 / n=跳过 / s=模拟吃 / q=离开): ").strip().lower()
            if user_input == 'q':
                print("[补给] 用户选择离开"); break
            elif user_input == 's':
                eat_count += 1
                print(f"[补给] [模拟] eat_count={eat_count}/3 (不真吃)")
                is_simulate = True
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

            # 食用 (模拟模式跳过)
            if not is_simulate:
                print(f"[补给] 食用 {choice['name']}...")
                cx2, cy2 = choice["x"], choice["y"]
                lp = _wa.MAKELONG(cx2, cy2)
                _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONDOWN, 0, lp)
                time.sleep(0.05)
                _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONUP, 0, lp)
                print(f"[补给] 已点击 ({cx2},{cy2}), 等待8秒...")
                virt_hunger += choice['food']
                virt_thirst += choice['water']
                consumed_food_total += choice['food']
                consumed_water_total += choice['water']
                eat_count += 1
                time.sleep(8.0)

            # 每3次食用后强制离开火堆再进入(防使用限制)
            if eat_count >= 3:
                import random
                # 加载点击偏移
                offset_file2 = os.path.join(base_dir, 'AImaneuver', 'click_offset.json')
                dx2, dy2 = 0, 0
                if os.path.exists(offset_file2):
                    off2 = json.load(open(offset_file2))
                    dx2, dy2 = off2.get('dx', 0), off2.get('dy', 0)
                print("\n[补给] 已吃3次, 离开火堆再进入...")
                import random
                # 加载偏移 (和_fire_camp_interact完全一致)
                off_f = os.path.join(base_dir, 'AImaneuver', 'click_offset.json')
                dx2, dy2 = 0, 0
                if os.path.exists(off_f):
                    o2 = json.load(open(off_f)); dx2, dy2 = o2.get('dx', 0), o2.get('dy', 0)
                # 点离开
                lx2, ly2 = LEAVE["x"], LEAVE["y"]
                lp2 = _wa.MAKELONG(lx2, ly2)
                _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONDOWN, 0, lp2)
                time.sleep(0.05)
                _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONUP, 0, lp2)
                time.sleep(3.0)
                # === 完全复制_fire_camp_interact的进火堆逻辑 ===
                best_cx2, best_cy2 = None, None
                for _ in range(5):
                    ret2, f2 = cap.read()
                    if not ret2: continue
                    det2 = self.yolo(f2, verbose=False, conf=0.3)[0]
                    for b2 in det2.boxes:
                        if self.yolo.names[int(b2.cls[0])].lower() == 'campfire':
                            x1b, y1b, x2b, y2b = map(int, b2.xyxy[0])
                            best_cx2 = (x1b + x2b) // 2; best_cy2 = (y1b + y2b) // 2
                            break
                    if best_cx2 is not None: break
                    time.sleep(0.3)
                if best_cx2 is None:
                    print("[补给] YOLO未检测到火堆, 重进失败")
                else:
                    opened2 = False
                    for i in range(8):
                        rx2 = best_cx2 + dx2 + random.randint(-100, 100)
                        ry2 = best_cy2 + dy2 + random.randint(-100, 100)
                        lp3 = _wa.MAKELONG(rx2, ry2)
                        _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONDOWN, 0, lp3)
                        time.sleep(0.05)
                        _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONUP, 0, lp3)
                        print(f"[补给] 重进#{i+1} ({rx2},{ry2})")
                        time.sleep(1.5)
                        if self._confirm_open():
                            opened2 = True; break
                        print(f"[补给] 重进#{i+1} 未检测到'开'")
                    if opened2:
                        print("[补给] 重新进入火堆成功!")
                        eat_count = 0
                        consumed_food_total = 0; consumed_water_total = 0
                        h2, t2 = read_hunger_thirst()
                        if h2: virt_hunger = h2
                        if t2: virt_thirst = t2
                        init_hunger = virt_hunger; init_thirst = virt_thirst
                if eat_count > 0:
                    print("[补给] 重进火堆失败, 离开")
                    break

        # 6. 离开
        lx, ly = LEAVE["x"], LEAVE["y"]
        lp = _wa.MAKELONG(lx, ly)
        _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONDOWN, 0, lp)
        time.sleep(0.05)
        _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONUP, 0, lp)
        self.status_msg = "补给完成, 已离开火堆"
        self.supply_info = None
        print(f"[补给] 点击离开 ({lx},{ly})")
        print("=" * 40 + "\n  ✅ 补给完成!\n" + "=" * 40)

        # ★ 自动返航补给后检查
        if self._post_supply_check:
            self._post_supply_check = False
            self._low_stat_triggered = False
            # 等待UI切换 + drain OBS缓冲 (防止读到火堆界面旧帧)
            print("[补给] 等待UI切换...")
            deadline = time.time() + 3.0
            while time.time() < deadline:
                if self.tracker and self.tracker.cap:
                    self.tracker.cap.grab()
                cv2.waitKey(1)
            for _ in range(5):
                if self.tracker and self.tracker.cap:
                    self.tracker.cap.grab(); cv2.waitKey(1)
                self.tracker.cap.retrieve()
            # 现在读到的才是正常HUD
            ret, sf = self.tracker.cap.read() if self.tracker else (False, None)
            if ret: self._read_status_values(sf)
            still_low = []
            if self.hunger_val > 0 and self.hunger_val < self.LOW_STAT_THRESHOLD:
                still_low.append(f"Hunger={self.hunger_val}")
            if self.thirst_val > 0 and self.thirst_val < self.LOW_STAT_THRESHOLD:
                still_low.append(f"Thirst={self.thirst_val}")
            if self.stamina_val > 0 and self.stamina_val < self.LOW_STAT_THRESHOLD:
                still_low.append(f"Stamina={self.stamina_val}")
            if still_low:
                print(f"\n{'='*60}")
                print(f"  !! 补给后状态仍不足, 程序终止 !!")
                print(f"  {', '.join(still_low)}")
                print(f"  请手动补充后重新运行")
                print(f"{'='*60}\n")
                self.status_msg = f"!! STOP: 补给不足 {', '.join(still_low)}"
                self.state = self.STATE_IDLE
                self.loop_patrol = False
            elif (self.hunger_val >= 100 and self.thirst_val >= 100 and
                  self.stamina_val > 0 and self.stamina_val >= 50):
                print(f"[补给完成] 状态恢复 → 返回巡逻起点")
                self.status_msg = "补给完成, 返回巡逻起点"
                if not self.waypoints and hasattr(self, '_saved_waypoints'):
                    self.waypoints = list(self._saved_waypoints)
                if self._patrol_start and self.waypoints:
                    self.start = None  # 让plan_path用当前位置
                    self.goal = self.waypoints[0]
                    self.wp_index = 0
                    self.plan_path()
                    self.state = self.STATE_NAVIGATING
                    self.returning_home = False
            else:
                print(f"[补给完成] 状态一般, 返回巡逻")
                self.status_msg = "补给完成, 返回巡逻"
                if not self.waypoints and hasattr(self, '_saved_waypoints'):
                    self.waypoints = list(self._saved_waypoints)
                if self._patrol_start and self.waypoints:
                    self.goal = self.waypoints[0]; self.wp_index = 0
                    self.plan_path()
                    self.state = self.STATE_NAVIGATING
                    self.returning_home = False

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
    # 战斗系统
    # ----------------------------------------------------------
    ZOMBIE_THRESHOLD = 600      # 作战搜索半径(px)
    ATTACK_RANGE = 130          # 攻击距离(px)
    ATTACK_INTERVAL = 0.7       # 攻击间隔(秒)
    HEAL_THRESHOLD = 80         # 补血阈值(%)
    ESCAPE_THRESHOLD = 20       # 脱战血量(%)
    COMBAT_ENTRY_HP = 70        # 进入战斗最低血量(%)
    COMBAT_ENTRY_MAX_ZOMBIES = 6  # 进入战斗最多僵尸数
    CHASE_TIMEOUT = 7.0           # 追击超时(秒)
    CHASE_ABANDON_DIST = 100      # 超时后距离>此值放弃目标
    WAYPOINT_COMBAT_TIMEOUT = 60  # 单途径点战斗总时长(秒)
    SCREEN_TO_GRID = 3.2          # 屏幕px→网格格比例
    ATTACK_BTN = "leave_campfire"  # 攻击按钮(别名)

    def _read_status_values(self, frame):
        """从OBS帧读取HP/饱食/口渴/耐力"""
        import cv2
        if frame is None: return
        # HP 绿色血条
        hp_file = os.path.join(os.path.dirname(__file__),
                               'AImaneuver', 'hp_detector_roi.json')
        if self._hp_roi is None and os.path.exists(hp_file):
            self._hp_roi = json.load(open(hp_file))
        if self._hp_roi:
            hx, hy, hw, hh = [max(1, int(v)) for v in self._hp_roi]
            hp_roi = frame[hy:hy + hh, hx:hx + hw]
            if hp_roi.size > 0:
                hsv = cv2.cvtColor(hp_roi, cv2.COLOR_BGR2HSV)
                gm = cv2.inRange(hsv, np.array([35, 40, 40]),
                                 np.array([85, 255, 255]))
                self.hp_pct = int(np.count_nonzero(gm) / gm.size * 100)

        # OCR状态(饱食/口渴/耐力) — 每5秒读一次避免性能问题
        if self._ocr_en is None:
            try:
                import easyocr
                self._ocr_en = easyocr.Reader(["en"], gpu=True)
            except Exception:
                return
        if not hasattr(self, '_last_ocr_time'):
            self._last_ocr_time = 0
            self._debug_ocr = False  # OCR调试(看终端)
        if time.time() - self._last_ocr_time > 2.0:
            self._last_ocr_time = time.time()
            roi_file = os.path.join(os.path.dirname(__file__),
                                    'AImaneuver', 'ocr_reader_roi.json')
            if os.path.exists(roi_file):
                saved = json.load(open(roi_file))
                for r in saved:
                    name = r[0]
                    rx, ry, rw, rh = int(r[1]), int(r[2]), int(r[3]), int(r[4])
                    roi = frame[ry:ry+rh, rx:rx+rw]
                    if roi.size == 0: continue
                    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                    big = cv2.resize(gray, (rw*6, rh*6), interpolation=cv2.INTER_CUBIC)
                    rt = self._ocr_en.readtext(big, detail=1, allowlist="0123456789")
                    if rt:
                        parts = [r[1].strip() for r in rt if r[1].strip().isdigit()]
                        v = "".join(parts)
                        if v.isdigit():
                            val = int(v)
                            if val > 200: val = int(str(val)[:2])
                            if name == "Hunger": self.hunger_val = val
                            elif name == "Thirst": self.thirst_val = val
                            elif name == "Stamina": self.stamina_val = val
                            elif name == "Threat": self.threat_val = val
                            elif name == "Exp": pass  # Exp不用于决策
                            # 调试: 打印每个ROI的读取结果
                            if hasattr(self, '_debug_ocr') and self._debug_ocr:
                                print(f"  [OCR:{name}] parts={parts} -> {v}")
            # 终端打印当前状态
            if hasattr(self, '_last_status_print'):
                if time.time() - self._last_status_print > 3.0:
                    print(f"[NavStatus] HP={self.hp_pct}% H={self.hunger_val} T={self.thirst_val} S={self.stamina_val} Thr={self.threat_val} (OCR {time.time()-self._last_ocr_time:.1f}s ago)")
                    self._last_status_print = time.time()
            else:
                self._last_status_print = time.time()

    def _detect_zombies(self, frame):
        """YOLO检测僵尸, 返回[(cx, cy, name, dist), ...]"""
        if not self.yolo or frame is None: return
        det = self.yolo(frame, verbose=False, conf=0.3)[0]
        ydisp = det.plot()
        # 标注当前追击目标 (黄色粗框)
        if self.combat_target:
            tzx, tzy, tzn, tzd = self.combat_target
            for b in det.boxes:
                name = self.yolo.names[int(b.cls[0])]
                x1, y1, x2, y2 = map(int, b.xyxy[0])
                cx = (x1 + x2) // 2; cy = (y1 + y2) // 2
                if abs(cx - tzx) < 30 and abs(cy - tzy) < 30:
                    cv2.rectangle(ydisp, (x1, y1), (x2, y2), (0, 255, 255), 3)
                    short = name.replace('ZB','').replace('Zombie','Z')
                    cv2.putText(ydisp, f"TARGET:{short}", (x1, y1 - 10),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 2)
                    break
        self.yolo_disp = cv2.resize(ydisp, (350, 220))
        counts = {}
        zombies = []
        fh, fw = frame.shape[:2]
        player_cx, player_cy = fw // 2, fh // 2  # 玩家在画面中心
        for b in det.boxes:
            name = self.yolo.names[int(b.cls[0])]
            if 'ZB' in name.upper() or 'ZOMBIE' in name.upper():
                counts[name] = counts.get(name, 0) + 1
                x1, y1, x2, y2 = map(int, b.xyxy[0])
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2  # 僵尸底部(脚部)
                dist = int(np.hypot(cx - player_cx, cy - player_cy))
                zombies.append((cx, cy, name, dist))
        self.zombie_counts = counts
        # 按距离排序 + 过滤墙后僵尸
        if not self.position and not self.start: return
        px, py = self.position if self.position else self.start
        if px and py and hasattr(self, 'grid') and self.grid is not None:
            valid = []
            for z in zombies:
                if not self._is_blocked_by_wall(z[0], z[1], px, py):
                    valid.append(z)
            zombies = valid
        zombies.sort(key=lambda z: z[3])
        self.zombie_list = zombies

    def _is_blocked_by_wall(self, zx, zy, px, py):
        """锥形射线法检测僵尸是否被墙阻挡 — 检查主方向±15度"""
        import math
        dx = zx - 960; dy = zy - 540
        dist = math.hypot(dx, dy)
        if dist < 20: return False
        gx, gy = self.to_grid(int(px), int(py))
        base_angle = math.atan2(dy, dx)
        grid_dist = int(dist * self.SCREEN_TO_GRID)
        step = max(1, grid_dist // 30); max_steps = grid_dist
        # 检查3条射线: 主方向 ±15度
        best_ratio = 1.0
        for offset in [0, -0.26, 0.26]:  # 0, ±15度
            angle = base_angle + offset
            blocked = 0; total = 0
            for i in range(step, max_steps, step):
                wx = int(gx + i * math.cos(angle))
                wy = int(gy + i * math.sin(angle))
                if 0 <= wx < self.grid.shape[1] and 0 <= wy < self.grid.shape[0]:
                    total += 1
                    if self.grid[wy, wx] == 0:
                        blocked += 1
            if total > 2:
                best_ratio = min(best_ratio, blocked / total)
        return best_ratio > 0.5  # >50%不可达=有墙

    def _find_nearest_waypoint_idx(self, px, py):
        """找离当前位置直线距离最近的途径点索引"""
        if not self.waypoints: return -1
        best_i = 0
        best_d = float('inf')
        for i, (wx, wy) in enumerate(self.waypoints):
            d = np.hypot(px - wx, py - wy)
            if d < best_d:
                best_d = d
                best_i = i
        return best_i

    def _force_exit_combat(self, px, py):
        """强制脱战回巡逻"""
        self.combat_state = None
        self.combat_target = None
        self.chase_start_time = 0
        self.waypoint_combat_start = 0
        wp_i = self._find_nearest_waypoint_idx(px, py)
        self.wp_index = wp_i
        self.goal = self.waypoints[wp_i]
        self.start = (px, py)
        self.plan_path(to_goal_only=True)
        if self.state == self.STATE_READY:
            self.state = self.STATE_NAVIGATING
        self.last_waypoint_time = 0
        print(f"[战斗] 强制脱战 → WP{wp_i+1}")

    def _check_weapon(self):
        """检测武器是否耗尽 — 整理背包→颜色匹配第一格"""
        if not self._game_hwnd or not self.tracker: return
        now = time.time()
        if now - self._last_weapon_check < self.WEAPON_CHECK_INTERVAL: return
        self._last_weapon_check = now

        # 自动模式才整理背包
        if not self._weapon_manual:
            cp_file = os.path.join(os.path.dirname(__file__),
                                   'AImaneuver', 'click_points.json')
            if os.path.exists(cp_file):
                pts = json.load(open(cp_file))
                org = pts.get("organize_bag", {"x": 1480, "y": 857})
                lp = _wa.MAKELONG(org["x"], org["y"])
                _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONDOWN, 0, lp)
                time.sleep(0.02)
                _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONUP, 0, lp)
            time.sleep(0.3)

        # drain + 读帧
        for _ in range(5): self.tracker.cap.grab(); cv2.waitKey(1)
        ret, f = self.tracker.cap.read()
        if not ret: return

        rx, ry, rw, rh = [max(1, int(v)) for v in self.WEAPON_ROI]
        roi = f[ry:ry+rh, rx:rx+rw]
        if roi.size == 0: return

        bgr_ref = np.array(self.WEAPON_EMPTY_RGB[::-1])
        diff = np.abs(roi.astype(np.int16) - bgr_ref.astype(np.int16))
        dist = np.sqrt(np.sum(diff ** 2, axis=2))
        match_ratio = np.count_nonzero(dist < self.WEAPON_TOLERANCE) / dist.size

        if match_ratio > self.WEAPON_EMPTY_THRESHOLD:
            self._weapon_empty = True
            print(f"[武器] 检测到空槽! match={match_ratio:.1%}")

    def _escape_to_waypoint(self, px, py):
        """脱战: 空格 → A*回最近途径点 → 跳过模式下5个点"""
        if self.ctrl:
            try:
                self.ctrl.press(_wc.VK_SPACE, 0.15)
            except Exception:
                pass
        wp_i = self._find_nearest_waypoint_idx(px, py)
        self.combat_state = None
        self.combat_target = None
        self.skip_count = 5
        self.wp_index = wp_i
        self.goal = self.waypoints[wp_i]
        self.start = (px, py)
        self.plan_path(to_goal_only=True)
        if self.state == self.STATE_READY:
            self.state = self.STATE_NAVIGATING
        print(f"[战斗] 空格脱战 → WP{wp_i+1} 跳过5点")
        self.last_waypoint_time = 0  # 清除等待状态

    LOW_STAT_THRESHOLD = 15   # 饱食/口渴/耐力低于此值触发返航 (O/P调节)
    # 武器检测
    WEAPON_CHECK_INTERVAL = 15  # 武器检测间隔(秒)
    WEAPON_ROI = [1300, 838, 30, 30]  # 武器第一格区域 (会被weapon_roi.json覆盖)
    WEAPON_EMPTY_RGB = (80, 39, 19)   # 空槽参考色
    WEAPON_TOLERANCE = 20             # 色差容差
    WEAPON_EMPTY_THRESHOLD = 0.3      # 空槽判定阈值

    def _combat_logic(self, px, py):
        """战斗状态机: 规则1补血 > 规则2脱战 > 规则3低状态返航 > 战斗/巡逻"""
        # ---- 规则1: 全局补血 ----
        if self.hp_pct < self.HEAL_THRESHOLD and self.ctrl:
            if self.skills.is_ready(1):  # skill_2 补血
                self.skills.use(1, self.ctrl)

        # ---- 规则2: 血量过低 ----
        if self.hp_pct < self.ESCAPE_THRESHOLD and self.combat_state is None:
            self._escape_to_waypoint(px, py)
            return

        # ---- 规则0: Threat≥2 → 立刻返航补给 ----
        if (self.threat_val >= 2 and self.state == self.STATE_NAVIGATING
                and not self._low_stat_triggered and self.home
                and self.combat_state is None):
            print(f"[自动返航] Threat={self.threat_val} → 返航补给")
            self._low_stat_triggered = True
            self._post_supply_check = True
            self.returning_home = True
            self.goal = self.home
            self._saved_waypoints = list(self.waypoints)
            self.waypoints = []
            self.wp_index = 0
            self.plan_path()
            if self.state == self.STATE_READY:
                self.state = self.STATE_NAVIGATING
            return

        # ---- 规则0: 武器检测 (和补血同优先级) ----
        if self.state == self.STATE_NAVIGATING and not self._weapon_stop:
            self._check_weapon()
            if self._weapon_empty and not self._weapon_stop:
                print(f"\n[武器] 耗尽! 返航 → 停止")
                self._weapon_stop = True
                self.combat_state = None  # 强制退出战斗
                self.combat_target = None
                self.returning_home = True
                self.goal = self.home
                self.waypoints = []
                self.wp_index = 0
                self.plan_path()
                if self.state == self.STATE_READY:
                    self.state = self.STATE_NAVIGATING
                return

        # ---- 规则3: 饱食/口渴/耐力过低 → 自动返航 ----
        if (self.combat_state is None and not self._low_stat_triggered and
                self.home and self.state == self.STATE_NAVIGATING):
            low_stats = []
            if self.hunger_val > 0 and self.hunger_val < self.LOW_STAT_THRESHOLD:
                low_stats.append(f"Hunger={self.hunger_val}")
            if self.thirst_val > 0 and self.thirst_val < self.LOW_STAT_THRESHOLD:
                low_stats.append(f"Thirst={self.thirst_val}")
            if self.stamina_val > 0 and self.stamina_val < self.LOW_STAT_THRESHOLD:
                low_stats.append(f"Stamina={self.stamina_val}")
            if low_stats:
                print(f"[自动返航] 低状态: {', '.join(low_stats)} → 返航补给")
                self._low_stat_triggered = True
                self._post_supply_check = True
                self.returning_home = True
                self.goal = self.home
                self._saved_waypoints = list(self.waypoints)  # 保存途径点
                self.waypoints = []  # 清途径点, 直接回家
                self.wp_index = 0
                self.plan_path()
                if self.state == self.STATE_READY:
                    self.state = self.STATE_NAVIGATING
                return

        # ---- 战斗状态 ----
        if self.combat_state is not None:
            return self._combat_step(px, py)

        # ---- 巡逻中抵达途径点: 判断是否进入战斗 ----
        if self.last_waypoint_time > 0:
            if self.skip_count > 0:
                self.last_waypoint_time = time.time() + 999
            return

    def _combat_step(self, px, py):
        """战斗步进"""
        now = time.time()

        # ---- 途径点总超时检查 ----
        if (self.waypoint_combat_start > 0 and
                now - self.waypoint_combat_start > self.WAYPOINT_COMBAT_TIMEOUT):
            print(f"[战斗] 途径点战斗超时{self.WAYPOINT_COMBAT_TIMEOUT}s, 强制脱战")
            self._force_exit_combat(px, py)
            return

        if self.combat_state == 'chasing':
            # 追最近僵尸
            if self.zombie_list:
                self.combat_target = self.zombie_list[0]
                zx, zy, zname, zdist = self.combat_target
                # 追击超时: >7s且距离>100px → 放弃当前目标
                if (self.chase_start_time > 0 and
                        now - self.chase_start_time > self.CHASE_TIMEOUT and
                        zdist > self.CHASE_ABANDON_DIST):
                    print(f"[战斗] 追击{zname}超时{self.CHASE_TIMEOUT}s dist={zdist}, 切换目标")
                    # 从列表中移除, 换下一个
                    self.zombie_list = self.zombie_list[1:]
                    self.chase_start_time = now
                    if not self.zombie_list:
                        self._force_exit_combat(px, py)
                    return
                if zdist < self.ATTACK_RANGE:
                    self.combat_state = 'attacking'
                    print(f"[战斗] 进入攻击范围 {zname} dist={zdist}")
                else:
                    # WASD朝向僵尸 (画面中心=玩家位置)
                    frame_w = 1920  # OBS宽度
                    frame_h = 1080
                    dx = zx - frame_w // 2
                    dy = zy - frame_h // 2
                    di = best_direction(dx, dy)
                    keys = DIR_VECTORS[di][2:]
                    if self.ctrl:
                        self._move_keys(keys)
                    # 冷却好了就放技能1/3/4
                    for sk in [0, 2, 3]:
                        if self.skills.is_ready(sk):
                            self.skills.use(sk, self.ctrl)
                            break

        elif self.combat_state == 'attacking':
            # 攻击
            now = time.time()
            if now - self.last_attack_time >= self.ATTACK_INTERVAL and self.ctrl:
                cp_file = os.path.join(os.path.dirname(__file__),
                                       'AImaneuver', 'click_points.json')
                try:
                    click_pts = json.load(open(cp_file))
                    atk = click_pts.get(self.ATTACK_BTN, {"x": 920, "y": 313})
                    lp = _wa.MAKELONG(atk["x"], atk["y"])
                    _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONDOWN, 0, lp)
                    time.sleep(0.02)
                    _wa.SendMessage(self._game_hwnd, _wc.WM_LBUTTONUP, 0, lp)
                    self.last_attack_time = now
                    print(f"[攻击] click ({atk['x']},{atk['y']})")
                except Exception:
                    pass
                # 技能1/3/4轮流
                for sk in [0, 2, 3]:
                    if self.skills.is_ready(sk):
                        self.skills.use(sk, self.ctrl)
                        break

            # 检查脱战条件
            self._detect_zombies(self._last_frame if hasattr(self, '_last_frame') else None)
            if self.hp_pct < self.ESCAPE_THRESHOLD:
                self._escape_to_waypoint(px, py)
                return
            # 目标跑出攻击范围但仍<600px → 切回追击
            if (self.zombie_list and self.zombie_list[0][3] > self.ATTACK_RANGE and
                    self.zombie_list[0][3] < self.ZOMBIE_THRESHOLD):
                self.combat_state = 'chasing'
                self.combat_target = self.zombie_list[0]
                self.chase_start_time = time.time()
                print(f"[战斗] 目标跑远 {self.zombie_list[0][3]}px, 继续追击")
                return
            if not self.zombie_list or self.zombie_list[0][3] > self.ZOMBIE_THRESHOLD:
                print("[战斗] 300px内无僵尸, 脱战回巡逻")
                self.combat_state = None
                self.combat_target = None
                wp_i = self._find_nearest_waypoint_idx(px, py)
                self.wp_index = wp_i
                self.goal = self.waypoints[wp_i]
                self.start = (px, py)
                self.plan_path(to_goal_only=True)
                if self.state == self.STATE_READY:
                    self.state = self.STATE_NAVIGATING
                self.last_waypoint_time = 0
                return

    def _move_keys(self, keys):
        """移动按键"""
        all_vks = {'W': self.ctrl.VK_W, 'A': self.ctrl.VK_A,
                   'S': self.ctrl.VK_S, 'D': self.ctrl.VK_D}
        needed = set(keys)
        for name, vk in all_vks.items():
            if name not in needed:
                try: self.ctrl.key_up(vk)
                except Exception: pass
        for k in keys:
            try: self.ctrl.key_down(
                    getattr(self.ctrl, f'VK_{k}', ord(k)))
            except Exception: pass
        time.sleep(0.2)
        for k in keys:
            try: self.ctrl.key_up(
                    getattr(self.ctrl, f'VK_{k}', ord(k)))
            except Exception: pass

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
        if not self.position and not self.start: return
        px, py = self.position if self.position else self.start
        px, py = int(px), int(py)

        # ★ 状态检测 + 僵尸检测 (每步)
        if self.tracker and self.tracker.cap:
            ret, sf = self.tracker.cap.read()
            if ret:
                self._read_status_values(sf)
                self._detect_zombies(sf)
                self._last_frame = sf

        # ★ 战斗逻辑 (规则1补血 > 规则2脱战 > 战斗/巡逻判定)
        if self.hp_pct > 0:
            self._combat_logic(px, py)

        # ★ 补给后检查: 返航补给完成, 检查状态是否恢复
        if self._post_supply_check and self.state != self.STATE_NAVIGATING:
            self._post_supply_check = False
            self._low_stat_triggered = False
            still_low = []
            if self.hunger_val > 0 and self.hunger_val < self.LOW_STAT_THRESHOLD:
                still_low.append(f"Hunger={self.hunger_val}")
            if self.thirst_val > 0 and self.thirst_val < self.LOW_STAT_THRESHOLD:
                still_low.append(f"Thirst={self.thirst_val}")
            if self.stamina_val > 0 and self.stamina_val < self.LOW_STAT_THRESHOLD:
                still_low.append(f"Stamina={self.stamina_val}")
            if still_low:
                print(f"\n{'='*60}")
                print(f"  !! 补给后状态仍不足, 程序终止 !!")
                print(f"  {', '.join(still_low)}")
                print(f"  请手动补充后重新运行")
                print(f"{'='*60}\n")
                self.status_msg = f"!! STOP: 补给不足 {', '.join(still_low)}"
                self.state = self.STATE_IDLE
                self.loop_patrol = False  # 停止循环巡逻
            elif (self.hunger_val >= 100 and self.thirst_val >= 100 and
                  self.stamina_val > 0 and self.stamina_val >= 50):
                print(f"[补给完成] 状态恢复 → 返回巡逻起点")
                self.status_msg = "补给完成, 返回巡逻起点"
                # 恢复途径点 (自动返航时被清掉了)
                if not self.waypoints and hasattr(self, '_saved_waypoints'):
                    self.waypoints = self._saved_waypoints
                if self._patrol_start and self.waypoints:
                    self.start = (px, py)
                    self.goal = self.waypoints[0]
                    self.wp_index = 0
                    self.plan_path(to_goal_only=True)
                    if self.state == self.STATE_READY:
                        self.state = self.STATE_NAVIGATING
                    self.returning_home = False
            else:
                print(f"[补给完成] 状态一般, 返回巡逻")
                self.status_msg = "补给完成, 返回巡逻"
                if not self.waypoints and hasattr(self, '_saved_waypoints'):
                    self.waypoints = list(self._saved_waypoints)
                if self._patrol_start and self.waypoints:
                    self.goal = self.waypoints[0]; self.wp_index = 0
                    self.plan_path()
                    self.state = self.STATE_NAVIGATING
                    self.returning_home = False

        # ★ 战斗中: 完全跳过导航逻辑 (偏离/途径点/寻路)
        if self.combat_state is not None:
            return

        # 2. 返航模式触发火堆交互 (H键或自动返航)
        HOME_REACH = int(GOAL_REACH_THRESHOLD * 1.5)
        if self.returning_home and self.home:
            hx, hy = self.home
            d_home = np.hypot(px - hx, py - hy)
            if d_home < HOME_REACH:
                # 武器耗尽返航: 先进火堆, 再停止
                if self._weapon_stop:
                    print(f"\n{'='*60}")
                    print(f"  !! 武器耗尽, 进入火堆 !!")
                    print(f"{'='*60}\n")
                    self.status_msg = "武器耗尽, 进入火堆..."
                    self.state = self.STATE_IDLE
                    self.returning_home = False
                    # 进入火堆后停止, 不补给
                    self._fire_camp_interact_no_supply()
                    return
                print(f"\n{'='*40}\n[返航] 距火堆{d_home:.0f}px, 触发火堆交互\n{'='*40}")
                self.state = self.STATE_IDLE
                self.returning_home = False
                self._fire_camp_interact()
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
            if not self.plan_path(to_goal_only=True):
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

        # 0. 途径点等待中? 3次检测(0s/0.5s/1.0s)
        if self.last_waypoint_time > 0:
            elapsed = time.time() - self.last_waypoint_time
            check_points = [0, 0.5, 1.0]
            # 确定当前检测轮次
            check_idx = 0
            for cp in check_points:
                if elapsed >= cp:
                    check_idx = check_points.index(cp) + 1
            # 每次检测点: 查僵尸
            if self.combat_state is None and self.skip_count == 0 and check_idx > 0:
                # 在检测点做一次强制重新检测
                if hasattr(self, '_last_check_idx') and self._last_check_idx != check_idx:
                    if self.tracker and self.tracker.cap:
                        ret, sf = self.tracker.cap.read()
                        if ret:
                            self._detect_zombies(sf)
                            self._last_frame = sf
                self._last_check_idx = check_idx
                zombies_near = [z for z in self.zombie_list if z[3] < self.ZOMBIE_THRESHOLD]
                if (self.hp_pct >= self.COMBAT_ENTRY_HP and
                        len(zombies_near) < self.COMBAT_ENTRY_MAX_ZOMBIES and
                        zombies_near):
                    self.combat_state = 'chasing'
                    self.combat_target = zombies_near[0]
                    self.chase_start_time = time.time()
                    self.waypoint_combat_start = time.time()
                    self.last_waypoint_time = 0
                    self._last_check_idx = 0
                    print(f"[战斗] 检测#{check_idx} 发现僵尸, 进入战斗! HP={self.hp_pct}% n={len(zombies_near)}")
                    self.status_msg = "战斗: 追击中"
                    return
                # 打印检测结果
                if check_idx <= 3:
                    self.status_msg = f"WP检测#{check_idx}/3: 僵尸={len(self.zombie_list)}只"
            if elapsed < 1.0:
                return
            # 3次都没检测到, 切下一段
            self._last_check_idx = 0
            print(f"[巡逻] 3次检测无僵尸, 继续巡逻")
            self.last_waypoint_time = 0
            self.wp_index += 1
            if self.wp_index < len(self.waypoints):
                self.goal = self.waypoints[self.wp_index]
            elif self.loop_patrol and self._patrol_start:
                # 途径点走完 → 先回起点
                if self.goal != self._patrol_start:
                    self.goal = self._patrol_start
                    print("[!] -> 起点S")
                else:
                    # 到了起点 → 去WP1
                    self.wp_index = 0
                    self.goal = self.waypoints[0]
                    print("[!] 循环 -> WP1")
            else:
                print("[!] 到达终点!")
                self.state = self.STATE_IDLE
                self.status_msg = "巡逻完成"
                return
            self.start = (px, py)
            self.plan_path(to_goal_only=True)
            if self.state == self.STATE_READY:
                self.state = self.STATE_NAVIGATING
            print(f"[!] -> WP{self.wp_index+1}/{len(self.waypoints)}")
            return

        # 检查是否到达当前goal
        if self.goal:
            gx, gy = self.goal
            d_goal = np.hypot(px - gx, py - gy)
            if d_goal < GOAL_REACH_THRESHOLD:
                has_next = (self.waypoints and
                           (self.wp_index + 1 < len(self.waypoints) or self.loop_patrol))
                if has_next:
                    # 跳过模式: 不等直接走
                    if self.skip_count > 0:
                        self.skip_count -= 1
                        self.last_waypoint_time = time.time() + 999  # 触发跳过
                        self.status_msg = f"跳过WP{self.wp_index+1} (剩余{self.skip_count})"
                        return
                    # 战斗条件: HP>=70% 且 300px内僵尸<6 → 进入战斗
                    zombies_near = [z for z in self.zombie_list if z[3] < self.ZOMBIE_THRESHOLD]
                    if (self.hp_pct >= self.COMBAT_ENTRY_HP and
                            len(zombies_near) < self.COMBAT_ENTRY_MAX_ZOMBIES and
                            zombies_near):
                        self.combat_state = 'chasing'
                        self.combat_target = zombies_near[0]
                        self.chase_start_time = time.time()
                        self.waypoint_combat_start = time.time()
                        print(f"[战斗] 进入战斗! HP={self.hp_pct}% 僵尸={len(zombies_near)}只")
                        self.status_msg = f"战斗: 追击中"
                        return
                    # 正常等待1秒
                    self.last_waypoint_time = time.time()
                    tag = f"途径点#{self.wp_index+1}"
                    print(f"[巡逻] 到达{tag}, 等待1秒...")
                    self.status_msg = f"{tag} 等待中"
                    return
                # 到达终点
                print(f"[!] 到达终点! (距目标{d_goal:.0f}px)")
                self.state = self.STATE_IDLE
                self.status_msg = "巡逻完成"
                return

        # 4. 检查偏离

        # 5. 8方向拟合 + 移动
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
            # 同时按下所有需要的键 (斜向)
            for k in keys:
                try:
                    self.ctrl.key_down(
                        getattr(self.ctrl, f'VK_{k}', ord(k)))
                except Exception:
                    pass
            time.sleep(MOVE_DURATION)
            # 同时释放
            for k in keys:
                try:
                    self.ctrl.key_up(
                        getattr(self.ctrl, f'VK_{k}', ord(k)))
                except Exception:
                    pass
        else:
            pass  # 模拟模式

        # 7. 技能: 战斗中才放1/3/4, 2由补血规则单独控制

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
            cv2.putText(canvas, f"Supply R{si['round']}round", (bx + 5, y), FONT, 0.45, (0, 255, 0), 1)
            y += 20
            cv2.putText(canvas, f"Init: H={si['init_hunger']} T={si['init_thirst']}",
                       (bx + 5, y), FONT, 0.35, (200, 200, 200), 1)
            y += 16
            cv2.putText(canvas, f"Virt: H={si['virt_hunger']} T={si['virt_thirst']}",
                       (bx + 5, y), FONT, 0.4, (0, 255, 255), 1)
            y += 16
            cv2.putText(canvas, f"Ate: food+{si['consumed_food']} water+{si['consumed_water']}",
                       (bx + 5, y), FONT, 0.35, (255, 200, 100), 1)
            y += 20

            # 推荐
            ch = si.get('choice')
            if ch:
                cv2.putText(canvas, f"Rec: {ch['name']} f+{ch['food']} w+{ch['water']}",
                           (bx + 5, y), FONT, 0.38, (0, 255, 100), 1)
                y += 18

            # 扫描到的物品
            cv2.putText(canvas, "Items:", (bx + 5, y), FONT, 0.35, (180, 180, 180), 1)
            y += 14
            for it in si.get('items', [])[:8]:
                cv2.putText(canvas,
                           f"  {it['name']}: f+{it['food']} w+{it['water']}",
                           (bx + 5, y), FONT, 0.3,
                           (0, 255, 0) if ch and it['name'] == ch['name'] else (150, 150, 150), 1)
                y += 12

        # ---- 右侧状态栏 ----
        sbx, sby = VW - 185, 5
        sbw = 180
        now = time.time()

        # 背景
        cv2.rectangle(canvas, (sbx, sby), (sbx + sbw, VH - 5), (35, 35, 35), -1)
        cv2.rectangle(canvas, (sbx, sby), (sbx + sbw, VH - 5), (100, 100, 100), 1)

        y = sby + 15
        cv2.putText(canvas, "Status", (sbx + 3, y), FONT, 0.4, (0, 255, 0), 1)
        y += 18

        # HP 血条
        hp = self.hp_pct
        hp_col = (0, 255, 0) if hp > 50 else (0, 200, 255) if hp > 20 else (0, 0, 255)
        cv2.putText(canvas, f"HP: {hp}%", (sbx + 3, y), FONT, 0.32, hp_col, 1)
        cv2.rectangle(canvas, (sbx + 55, y - 8), (sbx + 170, y + 2), (60, 60, 60), -1)
        cv2.rectangle(canvas, (sbx + 55, y - 8), (sbx + 55 + int(115 * hp / 100), y + 2), hp_col, -1)
        y += 16
        # Hunger / Thirst
        cv2.putText(canvas, f"H: {self.hunger_val}  T: {self.thirst_val}",
                   (sbx + 3, y), FONT, 0.3, (200, 200, 200), 1)
        y += 14
        cv2.putText(canvas, f"Sta: {self.stamina_val}", (sbx + 3, y),
                   FONT, 0.3, (200, 200, 200), 1)
        y += 14
        cv2.putText(canvas, f"Return threshold: <{self.LOW_STAT_THRESHOLD} (O/P)", (sbx + 3, y),
                   FONT, 0.25, (150, 150, 150), 1)
        y += 14
        # 玩家坐标
        if self.position:
            cv2.putText(canvas, f"pos: ({self.position[0]},{self.position[1]})",
                       (sbx + 3, y), FONT, 0.25, (150, 150, 150), 1)
        y += 18

        # 技能
        cv2.putText(canvas, "Skills", (sbx + 3, y), FONT, 0.35, (0, 255, 255), 1)
        y += 14
        for i in range(4):
            cd = self.skills.cooldowns[i]
            rem = self.skills.remaining(i, now)
            ready = rem <= 0
            col = (0, 255, 0) if ready else (255, 100, 100)
            bar_w = int(100 * (1 - rem / cd)) if cd > 0 else 100
            cv2.putText(canvas, f"{i+1}:", (sbx + 3, y), FONT, 0.28, (200, 200, 200), 1)
            cv2.rectangle(canvas, (sbx + 20, y - 7), (sbx + 120, y + 1), (50, 50, 50), -1)
            if bar_w > 0:
                cv2.rectangle(canvas, (sbx + 20, y - 7), (sbx + 20 + bar_w, y + 1), col, -1)
            cv2.putText(canvas, "OK" if ready else f"{rem:.0f}s",
                       (sbx + 123, y + 2), FONT, 0.25, col, 1)
            y += 11
        y += 4

        # 战斗状态 + 目标
        if self.combat_state is None:
            cv2.putText(canvas, "Patrol", (sbx + 3, y), FONT, 0.3, (0, 255, 200), 1)
        else:
            cv2.putText(canvas, f"COMBAT: {self.combat_state}", (sbx + 3, y),
                       FONT, 0.3, (0, 200, 255), 1)
            y += 14
            if self.combat_target:
                zx_, zy_, zn_, zd_ = self.combat_target
                short = zn_.replace('ZB','').replace('Zombie','Z')
                cv2.putText(canvas, f"Target: {short} {zd_}px",
                           (sbx + 3, y), FONT, 0.28, (255, 200, 0), 1)
                y += 14
                # 行动方向
                dx_ = zx_ - 960; dy_ = zy_ - 540
                if abs(dx_) > abs(dy_):
                    dr = "RIGHT" if dx_ > 0 else "LEFT"
                else:
                    dr = "DOWN" if dy_ > 0 else "UP"
                cv2.putText(canvas, f"Dir: {dr}", (sbx + 3, y),
                           FONT, 0.28, (200, 200, 200), 1)
        y += 14
        if self.skip_count > 0:
            cv2.putText(canvas, f"Skip: {self.skip_count}/5", (sbx + 3, y),
                       FONT, 0.3, (255, 150, 0), 1)
            y += 14
        y += 2

        # YOLO 画面
        if self.yolo_disp is not None:
            yd_h, yd_w = self.yolo_disp.shape[:2]
            if yd_w > sbw - 5:  # 缩放到面板宽度
                scale = (sbw - 5) / yd_w
                yd_w = sbw - 5
                yd_h = int(yd_h * scale)
                ydisp = cv2.resize(self.yolo_disp, (yd_w, yd_h))
            else:
                ydisp = self.yolo_disp
            canvas[y:y + yd_h, sbx + 3:sbx + 3 + yd_w] = ydisp
            cv2.rectangle(canvas, (sbx + 2, y - 1), (sbx + 4 + yd_w, y + yd_h), (0, 255, 0), 1)
            y += yd_h + 4

        # 僵尸统计
        cv2.putText(canvas, "Zombies:", (sbx + 3, y), FONT, 0.28, (255, 200, 100), 1)
        y += 12
        if self.zombie_counts:
            for name_, count_ in sorted(self.zombie_counts.items()):
                short = name_.replace('ZB', '').replace('Zombie', 'Z')
                cv2.putText(canvas, f"  {short}: {count_}", (sbx + 3, y),
                           FONT, 0.26, (200, 200, 200), 1)
                y += 10
        else:
            cv2.putText(canvas, "  (none)", (sbx + 3, y), FONT, 0.26, (150, 150, 150), 1)

        help_text = "左=起点/WP 右=终点 M=循环 R=重置 Enter=导航 空格=暂停 H=返航 Q=退出"
        cv2.putText(canvas, help_text,
                   (5, VH - 6), FONT, 0.3, (180, 180, 180), 1)

        return canvas

    # ----------------------------------------------------------
    def render_status(self):
        """渲染第二窗口: 左=大YOLO画面  右=状态栏"""
        SW, SH = 960, 540
        canvas = np.zeros((SH, SW, 3), dtype=np.uint8)
        FONT = cv2.FONT_HERSHEY_SIMPLEX

        # ---- 左侧: YOLO画面(带OCR框) ----
        img_w = 640
        if self._last_frame is not None:
            frame = self._last_frame.copy()
            # HP ROI (黄色)
            hp_file = os.path.join(os.path.dirname(__file__),
                                   'AImaneuver', 'hp_detector_roi.json')
            if os.path.exists(hp_file):
                hp_r = json.load(open(hp_file))
                hx, hy, hw_, hh = [int(v) for v in hp_r]
                cv2.rectangle(frame, (hx, hy), (hx + hw_, hy + hh), (0, 255, 255), 2)
                cv2.putText(frame, "HP", (hx, hy - 5), FONT, 0.5, (0, 255, 255), 2)
            # 状态OCR ROI (绿色框+标签)
            roi_file = os.path.join(os.path.dirname(__file__),
                                    'AImaneuver', 'ocr_reader_roi.json')
            if os.path.exists(roi_file):
                for r in json.load(open(roi_file)):
                    name, rx, ry, rw, rh = r[0], int(r[1]), int(r[2]), int(r[3]), int(r[4])
                    cv2.rectangle(frame, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 2)
                    cv2.putText(frame, name, (rx, ry - 5), FONT, 0.4, (0, 255, 0), 1)
            # Food OCR ROI (蓝色)
            food_file = os.path.join(os.path.dirname(__file__),
                                     'AImaneuver', 'food_ocr_roi.json')
            if os.path.exists(food_file):
                fr = json.load(open(food_file))
                fx, fy, fw_, fh_ = [int(v) for v in fr]
                cv2.rectangle(frame, (fx, fy), (fx + fw_, fy + fh_), (255, 150, 0), 2)
                cv2.putText(frame, "Tooltip", (fx, fy - 5), FONT, 0.4, (255, 150, 0), 1)
            # YOLO检测
            if self.yolo:
                try:
                    det = self.yolo(frame, verbose=False, conf=0.3)[0]
                    frame = det.plot()
                except Exception:
                    pass
            # 缩放到左侧
            fh, fw = frame.shape[:2]
            mh = int(img_w * fh / fw)
            disp = cv2.resize(frame, (img_w, mh))
            canvas[:mh, :img_w] = disp
        else:
            cv2.putText(canvas, "Waiting for OBS...", (200, SH // 2),
                       FONT, 0.6, (150, 150, 150), 1)
            mh = 0

        # ---- 右侧: 状态面板 ----
        rx = img_w + 10
        y = 5
        now = time.time()

        # 状态数值
        cv2.putText(canvas, "Status", (rx, y), FONT, 0.5, (0, 255, 0), 1)
        y += 22
        cv2.putText(canvas, f"HP: {self.hp_pct}%", (rx, y), FONT, 0.45, (0, 255, 100), 1)
        y += 20
        cv2.putText(canvas, f"H: {self.hunger_val}  T: {self.thirst_val}  S: {self.stamina_val}",
                   (rx, y), FONT, 0.4, (200, 200, 200), 1)
        y += 18
        cv2.putText(canvas, f"RetThr: <{self.LOW_STAT_THRESHOLD} (O/P)",
                   (rx, y), FONT, 0.3, (150, 150, 150), 1)
        y += 22

        # 模式
        if self.combat_state:
            cv2.putText(canvas, f"COMBAT: {self.combat_state}", (rx, y),
                       FONT, 0.45, (0, 200, 255), 1)
            y += 20
            if self.combat_target:
                _, _, zn2, zd2 = self.combat_target
                short = zn2.replace('ZB','').replace('Zombie','Z')
                cv2.putText(canvas, f"Target: {short} {zd2}px",
                           (rx, y), FONT, 0.4, (255, 200, 0), 1)
                y += 20
        else:
            cv2.putText(canvas, "Patrol", (rx, y), FONT, 0.45, (0, 255, 0), 1)
            y += 20
        if self.skip_count > 0:
            cv2.putText(canvas, f"Skip: {self.skip_count}/5",
                       (rx, y), FONT, 0.35, (255, 150, 0), 1)
            y += 18
        y += 5

        # 技能
        cv2.putText(canvas, "Skills:", (rx, y), FONT, 0.4, (0, 255, 255), 1)
        y += 18
        for i in range(4):
            cd = self.skills.cooldowns[i]
            rem = self.skills.remaining(i, now)
            ready = rem <= 0
            col = (0, 255, 0) if ready else (255, 100, 100)
            bar_w = int(150 * (1 - rem / cd)) if cd > 0 else 150
            cv2.putText(canvas, f"{i+1}:", (rx, y), FONT, 0.35, (200, 200, 200), 1)
            cv2.rectangle(canvas, (rx + 25, y - 10), (rx + 175, y + 2), (50, 50, 50), -1)
            if bar_w > 0:
                cv2.rectangle(canvas, (rx + 25, y - 10), (rx + 25 + bar_w, y + 2), col, -1)
            cv2.putText(canvas, "OK" if ready else f"{rem:.0f}s",
                       (rx + 180, y + 2), FONT, 0.3, col, 1)
            y += 16

        # 僵尸
        y += 5
        cv2.putText(canvas, "Zombies:", (rx, y), FONT, 0.4, (255, 200, 100), 1)
        y += 16
        if self.zombie_list:
            for zx_, zy_, zname_, zdist_ in self.zombie_list[:6]:
                short = zname_.replace('ZB','').replace('Zombie','Z')
                cv2.putText(canvas, f"  {short}: {zdist_}px",
                           (rx, y), FONT, 0.3, (200, 200, 200), 1)
                y += 14
        else:
            cv2.putText(canvas, "  (none)", (rx, y), FONT, 0.3, (150, 150, 150), 1)

        # ---- 配置参数 ----
        y = SH - 130
        cv2.putText(canvas, "Config (F=sel ,.=adj):", (rx, y),
                   FONT, 0.3, (150, 150, 150), 1)
        y += 12
        cfgs = [
            ("WP Reach", WAYPOINT_REACH_THRESHOLD),
            ("Deviation", PATH_DEVIATION_THRESHOLD),
            ("Move Dur", MOVE_DURATION),
            ("Goal Reach", GOAL_REACH_THRESHOLD),
            ("Lookahead", LOOKAHEAD_DIST),
            ("Zombie Rng", self.ZOMBIE_THRESHOLD),
            ("Attack Rng", self.ATTACK_RANGE),
            ("Chase s", self.CHASE_TIMEOUT),
            ("Low Stat", self.LOW_STAT_THRESHOLD),
        ]
        for i, (cn, cv) in enumerate(cfgs):
            col = (0, 255, 255) if i == self._cfg_sel else (150, 150, 150)
            mark = ">" if i == self._cfg_sel else " "
            cv2.putText(canvas, f"{mark}{cn}: {cv}", (rx, y),
                       FONT, 0.25, col, 1)
            y += 11

        return canvas

    # ----------------------------------------------------------
    def render_config(self):
        """渲染第三窗口: 超参数配置面板"""
        CW, CH = 500, 600
        canvas = np.zeros((CH, CW, 3), dtype=np.uint8)
        FONT = cv2.FONT_HERSHEY_SIMPLEX
        y = 15

        cv2.putText(canvas, "Config Panel", (5, y), FONT, 0.5, (0, 255, 0), 1)
        y += 5
        cv2.putText(canvas, "F=console input  O/P=return thr", (5, y),
                   FONT, 0.3, (150, 150, 150), 1)
        y += 20

        sections = [
            ("-- Navigation --", [
                ("WP Reach", WAYPOINT_REACH_THRESHOLD, "px, waypoint arrival dist"),
                ("Deviation", PATH_DEVIATION_THRESHOLD, "px, replan when off path"),
                ("Move Dur", MOVE_DURATION, "s, key press duration"),
                ("Goal Reach", GOAL_REACH_THRESHOLD, "px, goal arrival dist"),
                ("Lookahead", LOOKAHEAD_DIST, "px, forward waypoint dist"),
            ]),
            ("-- Combat --", [
                ("Zombie Rng", self.ZOMBIE_THRESHOLD, "px, combat search radius"),
                ("Attack Rng", self.ATTACK_RANGE, "px, attack range"),
                ("Chase s", int(self.CHASE_TIMEOUT), "s, chase timeout"),
                ("Combat HP", self.COMBAT_ENTRY_HP, "%, min HP to enter combat"),
            ]),
            ("-- Status --", [
                ("Low Stat", int(self.LOW_STAT_THRESHOLD), "H/T/S below=return"),
                ("Heal HP", self.HEAL_THRESHOLD, "%, HP below=use skill_2"),
                ("Escape HP", self.ESCAPE_THRESHOLD, "%, HP below=escape"),
            ]),
            ("-- Skills --", [
                ("Skill 1 CD", self.skills.cooldowns[0], "s, combat skill"),
                ("Skill 2 CD", self.skills.cooldowns[1], "s, HEAL skill (slot 2!)"),
                ("Skill 3 CD", self.skills.cooldowns[2], "s, combat skill"),
                ("Skill 4 CD", self.skills.cooldowns[3], "s, combat skill"),
            ]),
            ("-- Weapon --", [
                ("Weap ROI", f"({self.WEAPON_ROI[0]},{self.WEAPON_ROI[1]})", "weapon slot pos"),
                ("Weap Tol", self.WEAPON_TOLERANCE, "color tolerance"),
                ("Weap Thr", self.WEAPON_EMPTY_THRESHOLD, "empty threshold"),
            ]),
            ("-- Requirements --", [
                ("Skill 2", "HEAL", "Must be healing skill"),
                ("Cooldowns", "game CD+2s", "Set longer than real CD"),
                ("Max Food", "8 items", ">8 may fail OCR"),
            ]),
        ]

        for title, items in sections:
            cv2.putText(canvas, title, (5, y), FONT, 0.4, (0, 255, 255), 1)
            y += 18
            for name, val, desc in items:
                cv2.putText(canvas, f"  {name}: {val}", (10, y),
                           FONT, 0.3, (200, 200, 200), 1)
                cv2.putText(canvas, desc, (250, y), FONT, 0.25, (120, 120, 120), 1)
                y += 15
            y += 5

        return canvas

    # ----------------------------------------------------------
    def on_mouse(self, event, sx, sy, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            pt = self.scr2img(sx, sy)
            if self.start is None:
                self.start = pt
                self._patrol_start = pt  # 记录巡逻起点
                self.status_msg = f"起点=({pt[0]},{pt[1]})"
                print(f"[起点] {pt}")
            else:
                self.waypoints.append(pt)
                i = len(self.waypoints)
                self.status_msg = f"途径点#{i}=({pt[0]},{pt[1]})"
                print(f"[途径点#{i}] {pt}")
        elif event == cv2.EVENT_RBUTTONDOWN:
            pt = self.scr2img(sx, sy)
            self.goal = pt
            self.waypoints = []
            self.wp_index = 0
            self.loop_patrol = False
            self.status_msg = f"终点=({pt[0]},{pt[1]})"
            print(f"[终点] {pt}")
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
    print("H=返航 | M=循环巡逻 | R=重置 | 1-4=技能 | E=技能开关 | IJKL=平移 | +/-=缩放\n")

    cv2.namedWindow("Nav", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty("Nav", cv2.WND_PROP_TOPMOST, 1)
    cv2.setMouseCallback("Nav", nav.on_mouse)

    cv2.namedWindow("Status", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Status", 960, 540)

    # === Config Web Server ===
    try:
        from config_server import start as start_cfg_server
        start_cfg_server()
    except Exception as e:
        print(f"[Config] Web server failed: {e}")

    # === Config cv2 Window removed (use web panel instead) ===
    CFG_JSON = os.path.join(os.path.dirname(__file__), "navigator_config.json")
    cfg_mouse = {"dragging": False, "idx": -1}

    def cfg_on_mouse(event, sx, sy, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            for i, (_, ypos, _, _, _, _, _, _) in enumerate(cfg_sliders):
                if ypos - 5 <= sy <= ypos + 15:
                    cfg_mouse["dragging"] = True
                    cfg_mouse["idx"] = i
                    break
        elif event == cv2.EVENT_LBUTTONUP:
            cfg_mouse["dragging"] = False
            cfg_mouse["idx"] = -1
        elif event == cv2.EVENT_MOUSEMOVE and cfg_mouse["dragging"]:
            i = cfg_mouse["idx"]
            if 0 <= i < len(cfg_sliders):
                name, ypos, vmin, vmax, bar_x, bar_w, _, _ = cfg_sliders[i]
                pct = max(0, min(1, (sx - bar_x) / bar_w))
                val = vmin + pct * (vmax - vmin)
                # 整数参数
                if name not in ("Move Dur",):
                    val = int(val)
                else:
                    val = round(val, 1)
                cfg_values[name] = max(vmin, min(vmax, val))

    # Config window removed - use web panel at http://127.0.0.1:5050

    # 定义滑块: name, y, min, max, bar_x, bar_w
    cfg_sliders = []
    cfg_values = {}
    sections = [
        ("NAVIGATION", [
            ("WP Reach(px)", 25, 5, 200, "waypoint arrival dist"),
            ("Deviation(px)", 100, 10, 300, "replan when off path"),
            ("Move Dur(s)", 0.5, 0.05, 3.0, "key press duration"),
            ("Goal Reach(px)", 100, 10, 300, "goal arrival dist"),
            ("Lookahead(px)", 90, 10, 300, "forward lookahead dist"),
        ]),
        ("COMBAT", [
            ("Zombie Rng(px)", 600, 100, 2000, "combat search radius"),
            ("Attack Rng(px)", 130, 20, 500, "attack range"),
            ("Chase Time(s)", 7, 1, 30, "chase timeout per target"),
            ("Combat Entry HP%", 70, 20, 100, "min HP to enter combat"),
            ("Max Zombies", 6, 1, 20, "max zombies to enter combat"),
        ]),
        ("STATUS", [
            ("Low Stat Thr", 15, 1, 100, "H/T/S below=return supply"),
            ("Heal HP%", 80, 20, 100, "HP below=use skill_2"),
            ("Escape HP%", 20, 5, 50, "HP below=escape dash"),
            ("Return Thr", 15, 1, 100, "same as Low Stat (O/P key)"),
        ]),
        ("WEAPON", [
            ("W Tol", 20, 5, 100, "color tolerance"),
            ("W Thr", 0.3, 0.05, 0.9, "empty threshold"),
            ("W Check(s)", 15, 5, 60, "weapon check interval"),
        ]),
    ]
    for sec_name, items in sections:
        for name, default, vmin, vmax, desc in items:
            cfg_sliders.append((name, 0, vmin, vmax, 0, 0, desc, sec_name))
            cfg_values[name] = default

    last_nav = 0
    print("[定位] 请在地图上点击你的当前位置作为起点...")

    while True:
        canvas = nav.render()
        cv2.imshow("Nav", canvas)
        # 即使不在导航中也读取OBS帧 (让Status窗口始终有画面)
        if nav.tracker and nav.tracker.cap:
            ret, sf = nav.tracker.cap.read()
            if ret:
                nav._read_status_values(sf)
                nav._detect_zombies(sf)
                nav._last_frame = sf
        status_canvas = nav.render_status()
        cv2.imshow("Status", status_canvas)
        # Config: 从web面板JSON读取最新值
        if os.path.exists(CFG_JSON):
            try:
                with open(CFG_JSON) as f:
                    wcfg = json.load(f)
                if "waypoint_reach" in wcfg:
                    globals()['WAYPOINT_REACH_THRESHOLD'] = int(wcfg["waypoint_reach"])
                    globals()['PATH_DEVIATION_THRESHOLD'] = int(wcfg["deviation"])
                    globals()['MOVE_DURATION'] = float(wcfg["move_dur"])
                    globals()['GOAL_REACH_THRESHOLD'] = int(wcfg["goal_reach"])
                    globals()['LOOKAHEAD_DIST'] = int(wcfg["lookahead"])
                    nav.ZOMBIE_THRESHOLD = int(wcfg["zombie_range"])
                    nav.ATTACK_RANGE = int(wcfg["attack_range"])
                    nav.CHASE_TIMEOUT = int(wcfg["chase_timeout"])
                    nav.COMBAT_ENTRY_HP = int(wcfg["combat_entry_hp"])
                    nav.COMBAT_ENTRY_MAX_ZOMBIES = int(wcfg["max_zombies"])
                    nav.LOW_STAT_THRESHOLD = int(wcfg["low_stat_thr"])
                    nav.HEAL_THRESHOLD = int(wcfg["heal_hp"])
                    nav.ESCAPE_THRESHOLD = int(wcfg["escape_hp"])
                    nav.WEAPON_TOLERANCE = int(wcfg["weapon_tol"])
                    nav.WEAPON_EMPTY_THRESHOLD = float(wcfg["weapon_thr"])
                    nav.WEAPON_CHECK_INTERVAL = int(wcfg["weapon_check"])
            except Exception:
                pass

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

        # Enter = 开始导航 (如果还没规划则自动规划)
        elif key == 13:
            if nav.state != nav.STATE_READY and nav.start and (nav.waypoints or nav.goal):
                nav.plan_path()
            if nav.state == nav.STATE_READY:
                nav.state = nav.STATE_NAVIGATING
                nav.returning_home = False
                print("[导航] 开始!")
                # 预加载状态OCR + 立即读一次
                if nav._ocr_en is None and nav.tracker and nav.tracker.cap:
                    try:
                        import easyocr
                        print("[OCR] 预加载...", end=" ")
                        nav._ocr_en = easyocr.Reader(["en"], gpu=True)
                        print("OK")
                    except Exception:
                        pass

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
                    nav._manual_home = True
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

        # M = 切换循环巡逻
        elif key in (ord('m'), ord('M')):
            if not nav.waypoints:
                print("[巡逻] 需要先添加途径点(左键)")
            else:
                nav.loop_patrol = not nav.loop_patrol
                nav.goal = None
                state = "ON" if nav.loop_patrol else "OFF"
                print(f"[巡逻] 循环: {state}")
                if nav.loop_patrol:
                    nav._patrol_start = nav.start
                    nav.plan_path()
                    n = len(nav.waypoints)
                    wps = " -> ".join([f"WP{i+1}" for i in range(n)])
                    print(f"[巡逻] 循环路线: S -> {wps} -> S -> ...")

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
            nav._low_stat_triggered = False
            nav._post_supply_check = False
            nav.skip_count = 0
            nav.combat_state = None
            nav.status_msg = "Reset, 请重新设定起点/途径点/终点"
            print("[重置] 起点/waypoints/goal/path cleared")

        # W = 切换武器检测模式 (auto/manual)
        elif key in (ord('w'), ord('W')):
            nav._weapon_manual = not nav._weapon_manual
            mode = "MANUAL" if nav._weapon_manual else "AUTO"
            print(f"[武器] 模式: {mode} ({'不' if nav._weapon_manual else ''}自动整理)")
            # 立即做一次检测
            if nav.tracker and nav.tracker.cap:
                for _ in range(3): nav.tracker.cap.grab(); cv2.waitKey(1)
                ret, wf = nav.tracker.cap.read()
                if ret:
                    rxw, ryw, rww, rhw = [max(1, int(v)) for v in nav.WEAPON_ROI]
                    ryw = min(ryw, wf.shape[0]-2)
                    rxw = min(rxw, wf.shape[1]-2)
                    rww = min(rww, wf.shape[1]-rxw)
                    rhw = min(rhw, wf.shape[0]-ryw)
                    roi_w = wf[ryw:ryw+rhw, rxw:rxw+rww]
                    if roi_w.size > 0:
                        bgr_ref = np.array(nav.WEAPON_EMPTY_RGB[::-1])
                        diff_w = np.abs(roi_w.astype(np.int16) - bgr_ref.astype(np.int16))
                        dist_w = np.sqrt(np.sum(diff_w ** 2, axis=2))
                        ratio_w = np.count_nonzero(dist_w < nav.WEAPON_TOLERANCE) / dist_w.size
                        empty_w = ratio_w > nav.WEAPON_EMPTY_THRESHOLD
                        tag = "EMPTY!" if empty_w else "HAS WEAPON"
                        print(f"[武器] 手动检测: {tag} match={ratio_w:.1%}")

        # O/P = 快速调整返航阈值
        elif key in (ord('o'), ord('O')):
            nav.LOW_STAT_THRESHOLD = min(100, nav.LOW_STAT_THRESHOLD + 5)
            print(f"[Thr] Return: <{nav.LOW_STAT_THRESHOLD}")
        elif key in (ord('p'), ord('P')):
            nav.LOW_STAT_THRESHOLD = max(1, nav.LOW_STAT_THRESHOLD - 5)
            print(f"[Thr] Return: <{nav.LOW_STAT_THRESHOLD}")

        # F = 控制台输入调整参数
        elif key in (ord('f'), ord('F')):
            print("\n=== Config ===")
            cfgs = [
                ("WP Reach", WAYPOINT_REACH_THRESHOLD),
                ("Deviation", PATH_DEVIATION_THRESHOLD),
                ("Move Dur", MOVE_DURATION),
                ("Goal Reach", GOAL_REACH_THRESHOLD),
                ("Lookahead", LOOKAHEAD_DIST),
                ("Zombie Rng", nav.ZOMBIE_THRESHOLD),
                ("Attack Rng", nav.ATTACK_RANGE),
                ("Chase s", nav.CHASE_TIMEOUT),
                ("Low Stat", nav.LOW_STAT_THRESHOLD),
            ]
            for i, (n, v) in enumerate(cfgs):
                print(f"  [{i+1}] {n}: {v}")
            inp = input("编号=新值 (如 3=0.3 回车跳过): ").strip()
            if inp and '=' in inp:
                try:
                    idx_str, val_str = inp.split('=', 1)
                    idx = int(idx_str.strip()) - 1
                    val = float(val_str.strip())
                    if 0 <= idx < 9:
                        nm = cfgs[idx][0]
                        if nm == "WP Reach":
                            globals()['WAYPOINT_REACH_THRESHOLD'] = int(val)
                        elif nm == "Deviation":
                            globals()['PATH_DEVIATION_THRESHOLD'] = int(val)
                        elif nm == "Move Dur":
                            globals()['MOVE_DURATION'] = max(0.05, val)
                        elif nm == "Goal Reach":
                            globals()['GOAL_REACH_THRESHOLD'] = int(val)
                        elif nm == "Lookahead":
                            globals()['LOOKAHEAD_DIST'] = int(val)
                        elif nm == "Zombie Rng":
                            nav.ZOMBIE_THRESHOLD = max(1, int(val))
                        elif nm == "Attack Rng":
                            nav.ATTACK_RANGE = max(1, int(val))
                        elif nm == "Chase s":
                            nav.CHASE_TIMEOUT = max(1, int(val))
                        elif nm == "Low Stat":
                            nav.LOW_STAT_THRESHOLD = max(1, int(val))
                        print(f"[CFG] {nm} = {val}")
                except Exception as e:
                    print(f"[CFG] Error: {e}")

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
