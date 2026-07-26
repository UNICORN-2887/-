"""可达区 + A* 寻路 + 光流实时定位."""

from typing import Optional, Tuple, List
import heapq, json, os
import cv2, numpy as np


# ── 可达图编辑器 ──────────────────────────────
class ReachabilityEditor:
    """二值可达图编辑 (涂刷/描边/HSV/门/火堆)."""
    def __init__(self):
        self.img = None; self.mask = None
        self.campfire = None; self.doors = []
        self._brush_size = 12; self._poly_points = []

    def load_map(self, path):
        self.img = cv2.imread(path)
        if self.img is None: raise FileNotFoundError(path)
        self._init_mask()

    def load_reachable(self, path):
        self.mask = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        self.img = np.zeros((*self.mask.shape, 3), dtype=np.uint8)

    def load_fire(self, path):
        if os.path.exists(path):
            with open(path) as f: self.campfire = tuple(json.load(f))

    def load_doors(self, path):
        if os.path.exists(path):
            with open(path) as f: self.doors = json.load(f)

    def save(self, rpath, cpath=None, dpath=None):
        cv2.imwrite(rpath, self.mask)
        if cpath and self.campfire:
            with open(cpath, "w") as f: json.dump(list(self.campfire), f)
        if dpath and self.doors:
            with open(dpath, "w") as f: json.dump(self.doors, f)

    def _init_mask(self):
        h, w = self.img.shape[:2]
        self.mask = np.full((h, w), 255, dtype=np.uint8)
        cv2.rectangle(self.mask, (0, 0), (w-1, h-1), 0, 3)

    def paint(self, x, y, v):
        cv2.circle(self.mask, (x, y), self._brush_size, v, -1)

    def set_brush(self, s): self._brush_size = s
    def add_poly_point(self, x, y): self._poly_points.append((x, y))

    def fill_poly(self, v):
        if len(self._poly_points) >= 3:
            pts = np.array(self._poly_points, dtype=np.int32).reshape((-1, 1, 2))
            cv2.fillPoly(self.mask, [pts], v)
        self._poly_points.clear()

    def cancel_poly(self): self._poly_points.clear()
    def add_door(self, x, y, t=1): self.doors.append({"x": x, "y": y, "type": t})

    def hsv_guess(self):
        if self.img is None: return
        hsv = cv2.cvtColor(self.img, cv2.COLOR_BGR2HSV)
        rough = cv2.inRange(hsv, np.array([0, 0, 30]), np.array([180, 180, 200]))
        self.mask[rough > 0] = 0

    def render_overlay(self):
        if self.img is None: return self.mask
        ov = self.img.copy()
        ov[self.mask == 0] = (ov[self.mask == 0] * 0.4).astype(np.uint8)
        return ov


# ── A* 寻路 ──────────────────────────────────
def _astar(grid_2d, start_xy, goal_xy):
    """DeadMaze 验证版 A* (255=可达, 0=不可达)."""
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
    """A* 寻路器 (封装 DeadMaze astar).

    Usage: pf = Pathfinder("reachable.png", shrink=8)
           path = pf.plan((1000,500), (2000,800))
    """

    def __init__(self, reachable_path: str, shrink: int = 8):
        self.reachable = cv2.imread(reachable_path, cv2.IMREAD_GRAYSCALE)
        if self.reachable is None:
            raise FileNotFoundError(reachable_path)
        self._h, self._w = self.reachable.shape[:2]
        self._shrink = shrink
        self._ds = 4
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

    def _to_grid(self, ix, iy): return ix // self._ds, iy // self._ds
    def _to_image(self, gx, gy): return gx * self._ds + self._ds // 2, gy * self._ds + self._ds // 2

    def plan(self, start: Tuple[int, int], goal: Tuple[int, int]
             ) -> Optional[List[Tuple[int, int]]]:
        gs = self._to_grid(*start)
        gg = self._to_grid(*goal)
        gh, gw = self._grid.shape
        if not (0 <= gs[0] < gw and 0 <= gs[1] < gh): return None
        if not (0 <= gg[0] < gw and 0 <= gg[1] < gh): return None
        raw = _astar(self._grid, gs, gg)
        if raw is None: return None
        # 转为像素坐标
        px_path = [(self._to_image(x, y)[0], self._to_image(x, y)[1]) for x, y in raw]
        # 先简化(删共线点) 再等距重采样
        return self._simplify_resample(px_path)

    def _simplify_resample(self, path, step=200):
        """简化共线点 + 等距重采样."""
        # 去重
        dedup = [path[0]]
        for p in path[1:]:
            if p != dedup[-1]:
                dedup.append(p)
        if len(dedup) < 2:
            return dedup
        # 直线简化: 保留拐点
        simplified = [dedup[0]]
        for i in range(1, len(dedup) - 1):
            a, b, c = simplified[-1], dedup[i], dedup[i + 1]
            # 如果 a→b→c 方向变化 > 1px 则保留 b
            v1 = (b[0]-a[0], b[1]-a[1])
            v2 = (c[0]-b[0], c[1]-b[1])
            if abs(v1[0] - v2[0]) > 2 or abs(v1[1] - v2[1]) > 2:
                simplified.append(b)
        simplified.append(dedup[-1])
        # 等距重采样
        out = [simplified[0]]
        for i in range(len(simplified) - 1):
            a, b = simplified[i], simplified[i+1]
            seg = np.hypot(b[0]-a[0], b[1]-a[1])
            n = max(1, int(seg / step))
            for t in range(1, n + 1):
                frac = t / n
                out.append((int(a[0]+(b[0]-a[0])*frac), int(a[1]+(b[1]-a[1])*frac)))
        return out

    @property
    def grid_size(self): return (self._gw, self._gh)

    def is_reachable(self, pixel: Tuple[int, int]) -> bool:
        gx, gy = self._to_grid(*pixel)
        if 0 <= gx < self._gw and 0 <= gy < self._gh:
            return self._grid[gy, gx] == 255
        return False


# ── LK 光流实时定位 ───────────────────────────
class PositionTracker:
    """Lucas-Kanade 金字塔光流追踪.

    比 ORB 匹配更稳定: 检测角点特征 → LK 追踪 → 中位数位移.

    Usage:
        tracker = PositionTracker("map.jpg", start_pos=(5000, 6000), crop=(160,60,1600,960))
        tracker.init_tracking(cap.read())
        while True:
            pos, conf = tracker.update(cap.read())
    """

    def __init__(self, map_img_path: str, start_pos: Tuple[int, int],
                 crop: Optional[Tuple[int, int, int, int]] = None):
        self._position = list(start_pos)
        self._crop = crop
        self._prev_gray = None
        self._prev_pts = None
        self._last_conf = 0.0
        self._lk_params = dict(winSize=(21, 21), maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
        self._feature_params = dict(maxCorners=200, qualityLevel=0.3,
            minDistance=15, blockSize=7)

        self._map_img = cv2.imread(map_img_path)
        self._map_gray = cv2.cvtColor(self._map_img, cv2.COLOR_BGR2GRAY) \
            if self._map_img is not None else None

    def _apply_crop(self, frame):
        if self._crop:
            x, y, w, h = self._crop
            return frame[y:y+h, x:x+w]
        return frame

    def init_tracking(self, frame: np.ndarray) -> None:
        frame = self._apply_crop(frame)
        self._prev_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self._prev_pts = cv2.goodFeaturesToTrack(
            self._prev_gray, mask=None, **self._feature_params)

    def update(self, frame: np.ndarray
               ) -> Tuple[Tuple[int, int], float]:
        if self._prev_gray is None or self._prev_pts is None:
            self.init_tracking(frame)
            return (tuple(self._position), 0.0)

        frame = self._apply_crop(frame)
        curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        next_pts, status, _ = cv2.calcOpticalFlowPyrLK(
            self._prev_gray, curr_gray, self._prev_pts, None, **self._lk_params)

        if next_pts is None or len(next_pts) < 4:
            self._prev_gray = curr_gray
            self._prev_pts = cv2.goodFeaturesToTrack(
                curr_gray, mask=None, **self._feature_params)
            return (tuple(self._position), 0.0)

        good_new = next_pts[status == 1]
        good_old = self._prev_pts[status == 1]

        if len(good_new) < 8:
            self._prev_gray = curr_gray
            self._prev_pts = cv2.goodFeaturesToTrack(
                curr_gray, mask=None, **self._feature_params)
            return (tuple(self._position), 0.0)

        dx = np.median(good_new[:, 0] - good_old[:, 0])
        dy = np.median(good_new[:, 1] - good_old[:, 1])
        conf = len(good_new) / max(len(self._prev_pts), 1)

        self._position[0] -= int(dx)
        self._position[1] -= int(dy)

        # 每隔一段或特征点不够时重新检测
        if len(good_new) < 100:
            self._prev_gray = curr_gray
            self._prev_pts = cv2.goodFeaturesToTrack(
                curr_gray, mask=None, **self._feature_params)
        else:
            self._prev_gray = curr_gray
            self._prev_pts = good_new.reshape(-1, 1, 2)

        self._last_conf = conf
        return (tuple(self._position), conf)

    def reset_position(self, new_pos): self._position = list(new_pos)

    @property
    def position(self): return tuple(self._position)
    @property
    def confidence(self): return self._last_conf
