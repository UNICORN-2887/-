"""可达区 + A* 寻路 + 光流实时定位."""

from typing import Optional, Tuple, List
import heapq, json, os
import cv2, numpy as np


# ── 可达图编辑器 (直搬 DeadMaze reachability_map.py 完整版) ──
class ReachabilityEditor:
    """二值可达图编辑器: 涂刷/描边/门标记/火堆/HSV/形态学/边界检测."""

    def __init__(self):
        self.original = None
        self.binary = None
        self.h = 0; self.w = 0
        self.base = "map"
        self.scale = 1.0
        self.offset_x = 0; self.offset_y = 0
        self.show_mode = 0  # 0=叠加 1=二值 2=原图
        self.brush_size = 12
        self.drawing = None
        self.drag_sx = 0; self.drag_sy = 0
        self.drag_ox = 0; self.drag_oy = 0
        self.poly_mode = False
        self.poly_points = []
        self.poly_color = 255
        self.door_mode = False
        self.doors = []
        self._pending_door = None
        self._last_mouse = (0, 0)
        self.campfire = None

    # ── 加载 ──
    def load_map(self, path):
        self.original = cv2.imread(path)
        if self.original is None: raise FileNotFoundError(path)
        self.h, self.w = self.original.shape[:2]
        self.base = os.path.splitext(os.path.basename(path))[0]
        self.scale = min(1000 / self.w, 750 / self.h, 1.0)
        self.binary = np.ones((self.h, self.w), dtype=np.uint8) * 255
        print(f"[地图] {self.w}x{self.h}")

    def load_reachable(self, path):
        self.binary = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if self.binary is None:
            self.binary = np.ones((self.h, self.w), dtype=np.uint8) * 255
        else:
            self.h, self.w = self.binary.shape

    # ── 坐标 ──
    def screen_to_image(self, sx, sy):
        ix = int((sx - self.offset_x) / self.scale)
        iy = int((sy - self.offset_y) / self.scale)
        return max(0, min(ix, self.w - 1)), max(0, min(iy, self.h - 1))

    # ── 边界检测: 黑色边缘 = 不可达 ──
    def init_boundary(self):
        if self.original is None: return
        gray = cv2.cvtColor(self.original, cv2.COLOR_BGR2GRAY)
        _, data = cv2.threshold(gray, 25, 255, cv2.THRESH_BINARY)
        data = cv2.morphologyEx(data, cv2.MORPH_CLOSE, np.ones((8, 8), np.uint8))
        contours, _ = cv2.findContours(data, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            largest = max(contours, key=cv2.contourArea)
            interior = np.zeros((self.h, self.w), dtype=np.uint8)
            cv2.drawContours(interior, [largest], -1, 255, -1)
            interior = cv2.dilate(interior, np.ones((5, 5), np.uint8))
            self.binary = interior
            pct = np.sum(interior > 0) / interior.size * 100
            print(f"[边界] 地图内可达={pct:.1f}% 黑色外围=不可达")
        else:
            print("[边界] 未检测到，保持全白")

    # ── HSV 分割 ──
    def hsv_guess(self):
        if self.original is None: return
        hsv = cv2.cvtColor(self.original, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([0, 0, 40]), np.array([180, 255, 255]))
        self.binary = mask
        pct = np.sum(mask > 0) / mask.size * 100
        print(f"[HSV] 可行走≈{pct:.1f}%")

    # ── 涂刷 ──
    def paint(self, ix, iy, color):
        r = max(1, int(self.brush_size / self.scale))
        x1 = max(0, ix - r); y1 = max(0, iy - r)
        x2 = min(self.w, ix + r); y2 = min(self.h, iy + r)
        self.binary[y1:y2, x1:x2] = color

    def set_brush(self, s): self.brush_size = s

    # ── 多边形 ──
    def add_poly_point(self, x, y): self.poly_points.append((x, y))
    def cancel_poly(self): self.poly_points.clear()

    def fill_poly(self, v=255):
        if len(self.poly_points) >= 3:
            pts = np.array(self.poly_points, dtype=np.int32).reshape((-1, 1, 2))
            cv2.fillPoly(self.binary, [pts], v)
            label = "可行走" if v == 255 else "障碍"
            print(f"[描边] 填充{len(self.poly_points)}边形 → {label}")
        self.poly_points.clear()

    # ── 门标记 ──
    def add_door(self, ix, iy, t=1):
        self._pending_door = (ix, iy)
        print(f"[门] 位置({ix},{iy}) 1=左上↔右下 2=右上↔左下")

    def _set_door_dir(self, dir_idx):
        dirs = [(1, 1), (1, -1)]
        if self._pending_door is None: return
        if dir_idx not in [0, 1]: return
        dx, dy = dirs[dir_idx]
        ix, iy = self._pending_door
        self.doors.append((ix, iy, dx, dy))
        print(f"[门] #{len(self.doors)} ({ix},{iy})")
        self._pending_door = None

    # ── 渲染 (搬自 DeadMaze) ──
    def render_overlay(self):
        VW, VH = 1050, 720
        FONT = cv2.FONT_HERSHEY_SIMPLEX
        if self.original is None or self.binary is None:
            return np.zeros((VH, VW, 3), dtype=np.uint8)

        dw = int(self.w * self.scale); dh = int(self.h * self.scale)
        orig_s = cv2.resize(self.original, (dw, dh))
        bin_s = cv2.resize(self.binary, (dw, dh), interpolation=cv2.INTER_NEAREST)
        canvas = np.zeros((VH, VW, 3), dtype=np.uint8)

        ox, oy = self.offset_x, self.offset_y
        sx1 = max(0, -ox); sy1 = max(0, -oy)
        sx2 = min(dw, -ox + VW); sy2 = min(dh, -oy + VH)
        dx1 = max(0, ox); dy1 = max(0, oy)
        dx2 = min(VW, ox + dw); dy2 = min(VH, oy + dh)
        pw = min(sx2 - sx1, dx2 - dx1); ph = min(sy2 - sy1, dy2 - dy1)

        if pw > 0 and ph > 0:
            if self.show_mode == 1:
                src = cv2.cvtColor(bin_s, cv2.COLOR_GRAY2BGR)
            elif self.show_mode == 2:
                src = orig_s.copy()
            else:
                src = orig_s.copy()
                m3 = bin_s[:, :, np.newaxis] / 255.0
                g = np.zeros_like(src); g[:, :, 1] = 128
                src = (src * 0.65 + g * 0.35 * m3).astype(np.uint8)
                r = np.zeros_like(src); r[:, :, 2] = 180
                src = (src * (1 - 0.45*(1-m3)) + r * 0.45*(1-m3)).astype(np.uint8)
                e = cv2.Canny(bin_s, 50, 150)
                src[e > 0] = [0, 255, 255]
            canvas[dy1:dy1+ph, dx1:dx1+pw] = src[sy1:sy1+ph, sx1:sx1+pw]

        # 多边形描边线
        if self.poly_mode and len(self.poly_points) >= 1:
            pts = [(int(p[0]*self.scale + self.offset_x),
                    int(p[1]*self.scale + self.offset_y)) for p in self.poly_points]
            for i in range(len(pts)):
                cv2.circle(canvas, pts[i], 4, (0, 255, 255), -1)
                if i > 0: cv2.line(canvas, pts[i-1], pts[i], (0, 255, 255), 2)

        # 门
        for i, (dx, dy, ddx, ddy) in enumerate(self.doors):
            sx = int(dx * self.scale + self.offset_x)
            sy = int(dy * self.scale + self.offset_y)
            cv2.circle(canvas, (sx, sy), 6, (255, 0, 255), -1)
            cv2.putText(canvas, f"D{i+1}", (sx+8, sy-8), FONT, 0.35, (255, 0, 255), 1)

        walkable = np.sum(self.binary == 255) / self.binary.size * 100
        view_names = ["叠加", "二值", "原图"]
        color_label = "白(可达)" if self.poly_color == 255 else "黑(不可达)"
        mode_str = "门标记" if self.door_mode else ("描边" if self.poly_mode else "涂刷")
        info = (f"[{mode_str}] 可行走={walkable:.1f}% | 缩放={self.scale*100:.0f}% | "
                f"画笔={self.brush_size}px | 视图: {view_names[self.show_mode]}")
        cv2.putText(canvas, info, (5, 18), FONT, 0.38, (0, 255, 0), 1)
        cv2.putText(canvas, "P=描边 D=门 左/右键=操作 F=切换颜色 IJKL=平移 +/-=缩放 1-4画笔 T=视图 S=保存 Q=退出",
                    (5, VH - 6), FONT, 0.3, (180, 180, 180), 1)
        return canvas

    # ── 鼠标回调 ──
    def on_mouse(self, event, sx, sy, flags, param):
        ix, iy = self.screen_to_image(sx, sy)
        self._last_mouse = (ix, iy)

        if self.door_mode:
            if event == cv2.EVENT_LBUTTONDOWN:
                self.add_door(ix, iy)
            return

        if self.poly_mode:
            if event == cv2.EVENT_LBUTTONDOWN:
                self.poly_points.append((ix, iy))
                print(f"[描边] 顶点#{len(self.poly_points)} ({ix},{iy})")
            elif event == cv2.EVENT_RBUTTONDOWN:
                self.fill_poly(self.poly_color)
            return

        if event == cv2.EVENT_LBUTTONDOWN:
            self.drawing = 'white'; self.paint(ix, iy, 255)
        elif event == cv2.EVENT_RBUTTONDOWN:
            self.drawing = 'black'; self.paint(ix, iy, 0)
        elif event == cv2.EVENT_MBUTTONDOWN:
            self.drawing = 'pan'; self.drag_sx, self.drag_sy = sx, sy
            self.drag_ox, self.drag_oy = self.offset_x, self.offset_y
        elif event == cv2.EVENT_MOUSEMOVE:
            if self.drawing == 'white': self.paint(self.screen_to_image(sx, sy)[0], self.screen_to_image(sx, sy)[1], 255)
            elif self.drawing == 'black': self.paint(self.screen_to_image(sx, sy)[0], self.screen_to_image(sx, sy)[1], 0)
            elif self.drawing == 'pan':
                self.offset_x = self.drag_ox + (sx - self.drag_sx)
                self.offset_y = self.drag_oy + (sy - self.drag_sy)
        elif event in (cv2.EVENT_LBUTTONUP, cv2.EVENT_RBUTTONUP, cv2.EVENT_MBUTTONUP):
            self.drawing = None
        elif event == cv2.EVENT_MOUSEWHEEL or event == 10:
            old = self.scale
            self.scale = min(3.0, self.scale * 1.15) if flags > 0 else max(0.03, self.scale / 1.15)
            if old != self.scale:
                r = self.scale / old
                self.offset_x = int(sx - r * (sx - self.offset_x))
                self.offset_y = int(sy - r * (sy - self.offset_y))

    # ── 保存 ──
    def save(self, path=None, cpath=None, dpath=None):
        if self.binary is not None:
            cv2.imwrite(path, self.binary)
            pct = np.sum(self.binary == 255) / self.binary.size * 100
            print(f"[保存] {path} 可行走={pct:.1f}%")
        if cpath and self.campfire:
            with open(cpath, "w") as f: json.dump(list(self.campfire), f)
        if dpath and self.doors:
            with open(dpath, "w") as f: json.dump(self.doors, f)


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
