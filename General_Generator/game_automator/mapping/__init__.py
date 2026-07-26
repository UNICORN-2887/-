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

    def update(self, frame: np.ndarray,
               verbose: bool = False
               ) -> Tuple[Tuple[int, int], float]:
        if self._ref_gray is None:
            self.set_reference(frame)
            return (tuple(self._position), 0.0)

        frame = self._apply_crop(frame)
        curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        kp1, des1 = self._orb.detectAndCompute(self._ref_gray, None)
        kp2, des2 = self._orb.detectAndCompute(curr_gray, None)

        if verbose:
            k1 = len(kp1) if kp1 else 0
            k2 = len(kp2) if kp2 else 0
            d1 = len(des1) if des1 is not None else 0
            d2 = len(des2) if des2 is not None else 0
            print(f"[Tracker] kp1={k1} kp2={k2} des1={d1} des2={d2} "
                  f"crop={self._crop} pos={self._position}")

        dx, dy, conf = 0.0, 0.0, 0.0
        if des1 is not None and des2 is not None and len(des1) >= 8 and len(des2) >= 8:
            matches = self._matcher.knnMatch(des1, des2, k=2)
            good = [m for m, n in matches
                     if m.distance < 0.75 * n.distance]
            if verbose:
                print(f"[Tracker] matches={len(matches)} good={len(good)}")
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
                if verbose:
                    print(f"[Tracker] dx={dx:.1f} dy={dy:.1f} conf={conf:.2f} "
                          f"total={(self._total_dx-dx):.0f},{(self._total_dy-dy):.0f}")

        self._last_conf = conf
        if conf > 0.3:
            self._total_dx += dx
            self._total_dy += dy
            self._position[0] -= int(dx)
            self._position[1] -= int(dy)
        elif verbose:
            print(f"[Tracker] 跳过 (conf={conf:.2f} < 0.3)")

        # 只有实际移动 > 5px 才更新参考帧, 避免静止时 conf=1.0 锁死
        movement = abs(dx) + abs(dy)
        if conf > 0.5 and movement > 5:
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


# ── A* 寻路 (DeadMaze验证版) ─────────────────
def _astar(grid_2d, start_xy, goal_xy):
    """A* on binary grid (255=walkable, 0=obstacle).
    返回 [(x,y), ...] 像素路径 或 None.
    (直接取自 DeadMaze pathfinder.py, 已验证可靠)
    """
    h, w = grid_2d.shape
    visited = np.zeros((h, w), dtype=np.uint8)
    parent = np.zeros((h, w, 2), dtype=np.int32)
    dirs = [(0,1),(1,0),(0,-1),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)]

    def hh(p):
        return np.hypot(p[0]-goal_xy[0], p[1]-goal_xy[1])

    heap = [(hh(start_xy), 0, start_xy[0], start_xy[1])]
    visited[start_xy[1], start_xy[0]] = 1

    while heap:
        _, cost, x, y = heapq.heappop(heap)
        if (x, y) == goal_xy:
            path = [(x, y)]
            while (x, y) != start_xy:
                px, py = parent[y, x]
                path.append((px, py))
                x, y = px, py
            path.reverse()
            return path

        for dx, dy in dirs:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h:
                if grid_2d[ny, nx] > 0 and not visited[ny, nx]:
                    visited[ny, nx] = 1
                    mc = 1.414 if dx and dy else 1.0
                    nc = cost + mc
                    heapq.heappush(heap, (nc + hh((nx, ny)), nc, nx, ny))
                    parent[ny, nx] = (x, y)
    return None


class Pathfinder:
    """A* 寻路器 (封装 DeadMaze 验证过的 astar).

    Usage:
        pf = Pathfinder("reachable.png", shrink=8)
        path = pf.plan((1000, 500), (2000, 800))
    """

    def __init__(self, reachable_path: str, shrink: int = 8):
        self.reachable = cv2.imread(reachable_path, cv2.IMREAD_GRAYSCALE)
        if self.reachable is None:
            raise FileNotFoundError(reachable_path)
        self._h, self._w = self.reachable.shape[:2]
        self._shrink = shrink
        self._ds = 4  # 降采样因子 (同 DeadMaze)
        self._build_grid()

    def _build_grid(self):
        if self._shrink > 0:
            k = np.ones((self._shrink, self._shrink), np.uint8)
            eroded = cv2.erode(self.reachable, k, iterations=1)
        else:
            eroded = self.reachable
        h2, w2 = self._h // self._ds, self._w // self._ds
        small = cv2.resize(eroded, (w2, h2), interpolation=cv2.INTER_NEAREST)
        _, small = cv2.threshold(small, 127, 255, cv2.THRESH_BINARY)
        self._grid = small
        self._gh, self._gw = h2, w2
        pct = np.sum(self._grid == 255) / self._grid.size * 100
        print(f"[Pathfinder] shrink={self._shrink} ds=1/{self._ds} "
              f"grid={w2}x{h2} walkable={pct:.1f}%")

    def _to_grid(self, ix, iy):
        return ix // self._ds, iy // self._ds

    def _to_image(self, gx, gy):
        return gx * self._ds + self._ds // 2, gy * self._ds + self._ds // 2

    def plan(self, start: Tuple[int, int], goal: Tuple[int, int]
             ) -> Optional[List[Tuple[int, int]]]:
        gs = self._to_grid(*start)
        gg = self._to_grid(*goal)
        gh, gw = self._grid.shape
        if not (0 <= gs[0] < gw and 0 <= gs[1] < gh): return None
        if not (0 <= gg[0] < gw and 0 <= gg[1] < gh): return None

        raw = _astar(self._grid, gs, gg)
        if raw is None:
            return None
        # 转回像素坐标
        path = [(self._to_image(x, y)[0], self._to_image(x, y)[1])
                for x, y in raw]
        print(f"[A*] raw_gr={len(raw)}pts pixel={len(path)}pts "
              f"first={path[0]} last={path[-1]}")
        return path  # 直接返回不重采样先

    def _resample(self, path: list, step: int = 200) -> list:
        if len(path) < 2:
            return path
        out = [path[0]]
        for i in range(len(path) - 1):
            a, b = path[i], path[i+1]
            seg = np.hypot(b[0]-a[0], b[1]-a[1])
            n = int(seg / step)
            for t in range(1, n + 1):
                frac = t / (n + 1)
                out.append((int(a[0]+(b[0]-a[0])*frac),
                           int(a[1]+(b[1]-a[1])*frac)))
        out.append(path[-1])
        return out

    @property
    def grid_size(self): return (self._gw, self._gh)

    def is_reachable(self, pixel: Tuple[int, int]) -> bool:
        gx, gy = self._to_grid(*pixel)
        if 0 <= gx < self._gw and 0 <= gy < self._gh:
            return self._grid[gy, gx] == 255
        return False
