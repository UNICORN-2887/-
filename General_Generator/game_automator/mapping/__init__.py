"""可达区标定 + A* 寻路.

ReachabilityEditor 提供涂刷/描边/HSV初稿/火堆标记功能.
Pathfinder 在可达图上执行 A* 路径规划.
"""

from typing import Optional, Tuple, List
import heapq
import json
import os
import cv2
import numpy as np


# ── 可达图编辑器 ──────────────────────────────
class ReachabilityEditor:
    """二值可达图编辑.

    Usage:
        editor = ReachabilityEditor()
        editor.load_map("map.jpg")
        # 在 cv2 窗口中涂刷 ...
        editor.save("map_reachable.png", "map_campfire.json")
    """

    def __init__(self):
        self.img: Optional[np.ndarray] = None           # 原图
        self.mask: Optional[np.ndarray] = None          # 255=可达, 0=不可达
        self.campfire: Optional[Tuple[int, int]] = None # 火堆坐标
        self.doors: List[dict] = []                     # [{x, y, type}]
        self._brush_size = 12
        self._poly_points: List[Tuple[int, int]] = []

    # ── 加载/保存 ──────────────────────────────
    def load_map(self, img_path: str) -> None:
        self.img = cv2.imread(img_path)
        if self.img is None:
            raise FileNotFoundError(img_path)
        self._init_mask()

    def load_reachable(self, reachable_path: str) -> None:
        """加载已有可达图 (0=不可达, 255=可达)."""
        self.mask = cv2.imread(reachable_path, cv2.IMREAD_GRAYSCALE)
        if self.mask is None:
            raise FileNotFoundError(reachable_path)
        self.img = np.zeros((self.mask.shape[0], self.mask.shape[1], 3), dtype=np.uint8)

    def load_fire(self, json_path: str) -> None:
        if os.path.exists(json_path):
            with open(json_path) as f:
                self.campfire = tuple(json.load(f))

    def load_doors(self, json_path: str) -> None:
        if os.path.exists(json_path):
            with open(json_path) as f:
                self.doors = json.load(f)

    def save(self, reachable_path: str,
             campfire_path: Optional[str] = None,
             doors_path: Optional[str] = None) -> None:
        cv2.imwrite(reachable_path, self.mask)
        if campfire_path and self.campfire:
            with open(campfire_path, "w") as f:
                json.dump(list(self.campfire), f)
        if doors_path and self.doors:
            with open(doors_path, "w") as f:
                json.dump(self.doors, f)

    def _init_mask(self):
        """外墙黑边+内部全白."""
        h, w = self.img.shape[:2]
        self.mask = np.full((h, w), 255, dtype=np.uint8)
        cv2.rectangle(self.mask, (0, 0), (w-1, h-1), 0, 3)

    # ── 涂刷 ──────────────────────────────────
    def paint(self, x: int, y: int, value: int):
        """value: 255=可达, 0=不可达."""
        r = self._brush_size
        cv2.circle(self.mask, (x, y), r, value, -1)

    def set_brush(self, size: int):
        self._brush_size = size

    # ── 描边 ──────────────────────────────────
    def add_poly_point(self, x: int, y: int):
        self._poly_points.append((x, y))

    def fill_poly(self, value: int):
        if len(self._poly_points) >= 3:
            pts = np.array(self._poly_points, dtype=np.int32).reshape((-1, 1, 2))
            cv2.fillPoly(self.mask, [pts], value)
        self._poly_points.clear()

    def cancel_poly(self):
        self._poly_points.clear()

    # ── HSV 初稿 ──────────────────────────────
    def hsv_guess(self):
        """用 HSV 颜色分割生成初稿."""
        if self.img is None:
            return
        hsv = cv2.cvtColor(self.img, cv2.COLOR_BGR2HSV)
        lower = np.array([0, 0, 30])
        upper = np.array([180, 180, 200])
        rough = cv2.inRange(hsv, lower, upper)
        self.mask[rough > 0] = 0

    # ── 门 ────────────────────────────────────
    def add_door(self, x: int, y: int, door_type: int = 1):
        self.doors.append({"x": x, "y": y, "type": door_type})

    # ── 渲染 ──────────────────────────────────
    def render_overlay(self) -> np.ndarray:
        """返回原图+半透明可达区叠加."""
        if self.img is None:
            return self.mask
        overlay = self.img.copy()
        overlay[self.mask == 0] = (overlay[self.mask == 0] * 0.4).astype(np.uint8)
        return overlay


# ── ORB 实时定位 ────────────────────────────
class PositionTracker:
    """ORB 特征匹配实时定位追踪.

    Usage:
        tracker = PositionTracker("map.jpg", start_pos=(5000, 6000))
        tracker.set_reference(cap.read())
        while moving:
            pos, conf = tracker.update(cap.read())
    """

    def __init__(self, map_img_path: str, start_pos: Tuple[int, int],
                 crop: Optional[Tuple[int, int, int, int]] = None):
        """crop: (x, y, w, h) 裁剪区, 排除 HUD/UI 避免干扰追踪."""
        self._position = list(start_pos)
        self._total_dx = 0.0
        self._total_dy = 0.0
        self._ref_gray = None
        self._crop = crop  # (x, y, w, h)
        self._orb = cv2.ORB_create(nfeatures=1500)
        self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        self._last_conf = 0.0

        # 预加载地图
        self._map_img = cv2.imread(map_img_path)
        if self._map_img is not None:
            self._map_gray = cv2.cvtColor(self._map_img, cv2.COLOR_BGR2GRAY)

    def _apply_crop(self, frame):
        if self._crop:
            x, y, w, h = self._crop
            return frame[y:y+h, x:x+w]
        return frame

    # ── 核心 ────────────────────────────────
    def set_reference(self, frame: np.ndarray) -> None:
        frame = self._apply_crop(frame)
        self._ref_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self._total_dx = 0.0
        self._total_dy = 0.0

    def update(self, frame: np.ndarray
               ) -> Tuple[Tuple[int, int], float]:
        if self._ref_gray is None:
            self.set_reference(frame)
            return (tuple(self._position), 0.0)

        frame = self._apply_crop(frame)
        curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # ORB 计算位移
        kp1, des1 = self._orb.detectAndCompute(self._ref_gray, None)
        kp2, des2 = self._orb.detectAndCompute(curr_gray, None)

        dx, dy, conf = 0.0, 0.0, 0.0
        if des1 is not None and des2 is not None and len(des1) >= 8 and len(des2) >= 8:
            matches = self._matcher.knnMatch(des1, des2, k=2)
            good = [m for m, n in matches
                     if m.distance < 0.75 * n.distance]
            if len(good) >= 6:
                dx_list, dy_list = [], []
                for m in good:
                    p1 = kp1[m.queryIdx].pt
                    p2 = kp2[m.trainIdx].pt
                    dx_list.append(p2[0] - p1[0])
                    dy_list.append(p2[1] - p1[1])
                dx = np.median(dx_list)
                dy = np.median(dy_list)
                inliers = sum(1 for ddx, ddy in zip(dx_list, dy_list)
                               if abs(ddx-dx) < 5 and abs(ddy-dy) < 5)
                conf = inliers / len(dx_list) if dx_list else 0.0
                dx, dy = -dx, -dy

        self._last_conf = conf
        if conf > 0.3:
            self._total_dx += dx
            self._total_dy += dy
            self._position[0] -= int(dx)
            self._position[1] -= int(dy)

        # 更新参考帧 (低通防止漂移)
        if conf > 0.5:
            self._ref_gray = curr_gray

        return (tuple(self._position), conf)

    def reset_position(self, new_pos: Tuple[int, int]) -> None:
        """手动重置位置 (用户在地图上点击后)."""
        self._position = list(new_pos)
        self._total_dx = 0.0
        self._total_dy = 0.0

    @property
    def position(self) -> Tuple[int, int]:
        return tuple(self._position)

    def relocalize(self, frame: np.ndarray,
                    search_radius: int = 300) -> Tuple[bool, float]:
        """在当前位置附近搜索地图匹配, 恢复定位.

        当帧间追踪置信度低时调用此方法,
        在当前位置 ±search_radius 范围内金字塔搜索最佳匹配.

        Returns (success, confidence).
        """
        if self._map_gray is None:
            return False, 0.0

        frame = self._apply_crop(frame)
        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        fh, fw = frame_gray.shape
        mh, mw = self._map_gray.shape

        best_score = 0.0
        best_dx, best_dy = 0, 0

        # 金字塔搜索: scale 0.3 ~ 1.0
        for s in [0.3, 0.5, 0.7, 1.0]:
            nw, nh = int(fw * s), int(fh * s)
            if nw < 20 or nh < 20:
                continue
            template = cv2.resize(frame_gray, (nw, nh))
            # 搜索范围
            cx, cy = self._position
            r = search_radius
            x1 = max(0, int(cx - r))
            y1 = max(0, int(cy - r))
            x2 = min(mw - nw, int(cx + r))
            y2 = min(mh - nh, int(cy + r))
            if x2 <= x1 or y2 <= y1:
                continue

            roi = self._map_gray[y1:y2, x1:x2]
            if roi.shape[0] < nh or roi.shape[1] < nw:
                continue

            result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val > best_score:
                best_score = max_val
                best_dx = x1 + max_loc[0] - cx
                best_dy = y1 + max_loc[1] - cy

        if best_score > 0.4:
            self._position[0] += best_dx
            self._position[1] += best_dy
            self._total_dx = 0.0
            self._total_dy = 0.0
            self.set_reference(frame)
            self._last_conf = best_score
            return True, best_score

        return False, best_score

    @property
    def confidence(self) -> float:
        return self._last_conf


# ── A* 寻路 ──────────────────────────────────
class Pathfinder:
    """A* 寻路器.

    Usage:
        pf = Pathfinder("reachable.png", shrink=80)
        path = pf.plan((1000, 500), (2000, 800))  # 返回坐标列表
        if path is None: print("不可达")
    """

    NEIGHBORS = [(1,0),(-1,0),(0,1),(0,-1),(1,1),(-1,1),(1,-1),(-1,-1)]

    def __init__(self, reachable_path: str, shrink: int = 80):
        full = cv2.imread(reachable_path, cv2.IMREAD_GRAYSCALE)
        if full is None:
            raise FileNotFoundError(reachable_path)
        self._original = full
        self._shrink = shrink
        self._build_grid()

    def _build_grid(self):
        s = self._shrink
        h, w = self._original.shape
        self._gh, self._gw = h // s, w // s
        self._grid = np.zeros((self._gh, self._gw), dtype=np.uint8)
        for gy in range(self._gh):
            for gx in range(self._gw):
                sy, sx = gy * s, gx * s
                block = self._original[sy:sy+s, sx:sx+s]
                self._grid[gy, gx] = 255 if np.mean(block) > 200 else 0

    def plan(self, start: Tuple[int, int], goal: Tuple[int, int]
             ) -> Optional[List[Tuple[int, int]]]:
        """返回从 start 到 goal 的路径坐标列表, 不可达返回 None."""
        gs = self._to_grid(start)
        gg = self._to_grid(goal)
        gh, gw = self._grid.shape
        if not (0 <= gs[0] < gw and 0 <= gs[1] < gh): return None
        if not (0 <= gg[0] < gw and 0 <= gg[1] < gh): return None

        open_set = [(0, gs)]
        came_from = {}
        g_score = {gs: 0}

        while open_set:
            _, current = heapq.heappop(open_set)
            if current == gg:
                path = [self._to_pixel(gg)]
                while current in came_from:
                    current = came_from[current]
                    path.append(self._to_pixel(current))
                path.reverse()
                return self._smooth(path)

            for dx, dy in self.NEIGHBORS:
                nb = (current[0]+dx, current[1]+dy)
                if not (0 <= nb[0] < gw and 0 <= nb[1] < gh): continue
                if self._grid[nb[1], nb[0]] == 0: continue
                cost = 1.4 if dx and dy else 1.0
                tentative = g_score[current] + cost
                if nb not in g_score or tentative < g_score[nb]:
                    g_score[nb] = tentative
                    h = np.hypot(nb[0]-gg[0], nb[1]-gg[1])
                    heapq.heappush(open_set, (tentative + h, nb))
        return None

    def _to_grid(self, pixel): return (pixel[0] // self._shrink, pixel[1] // self._shrink)
    def _to_pixel(self, grid): return (grid[0] * self._shrink, grid[1] * self._shrink)

    def _smooth(self, path: list) -> list:
        """贝塞尔平滑中间点."""
        if len(path) <= 2:
            return path
        result = [path[0]]
        i = 1
        while i < len(path) - 1:
            j = i + 1
            while j < len(path) and self._line_clear(path[i-1], path[j]):
                j += 1
            j -= 1
            if j > i:
                result.append(path[j])
                i = j + 1
            else:
                result.append(path[i])
                i += 1
        result.append(path[-1])
        return result

    def _line_clear(self, a, b):
        """射线是否全部可达."""
        steps = max(abs(b[0]-a[0]), abs(b[1]-a[1])) // self._shrink + 1
        for t in range(steps + 1):
            px = int(a[0] + (b[0]-a[0]) * t / steps)
            py = int(a[1] + (b[1]-a[1]) * t / steps)
            gx, gy = px // self._shrink, py // self._shrink
            if not (0 <= gx < self._gw and 0 <= gy < self._gh): return False
            if self._grid[gy, gx] == 0: return False
        return True

    @property
    def grid_size(self): return (self._gw, self._gh)

    def is_reachable(self, pixel: Tuple[int, int]) -> bool:
        gx, gy = pixel[0] // self._shrink, pixel[1] // self._shrink
        if 0 <= gx < self._gw and 0 <= gy < self._gh:
            return self._grid[gy, gx] == 255
        return False
