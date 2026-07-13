"""
DeadMaze - A* 寻路工具
在二值可达图上运行 A*，支持缩边（远离墙壁走中间）

原理:
  腐蚀可达区域 → 边缘缩进 → A* 必须走中间宽阔区域
  腐蚀量越大 = 离墙越远

操作:
  左键点击 = 设起点(绿) | 右键点击 = 设终点(红)
  [ ] = 调整缩边距离 | Enter = 执行寻路
  R = 清除路径 | S = 保存路径图
  IJKL = 平移 | +/- = 缩放 | Q = 退出
"""

import os
import sys
import argparse
import heapq
import time

import cv2
import numpy as np


# ============================================================
# A* 算法
# ============================================================
def astar(grid, start, goal):
    """
    A* on a binary grid (255=walkable, 0=obstacle)
    Returns list of (x,y) points or None if no path
    """
    h, w = grid.shape
    visited = np.zeros((h, w), dtype=np.uint8)
    parent = np.zeros((h, w, 2), dtype=np.int32)

    # 8-direction movement
    dirs = [(0, 1), (1, 0), (0, -1), (-1, 0),
            (1, 1), (1, -1), (-1, 1), (-1, -1)]

    def heuristic(p):
        return np.hypot(p[0] - goal[0], p[1] - goal[1])

    heap = [(heuristic(start), 0, start[0], start[1])]
    visited[start[1], start[0]] = 1

    while heap:
        _, cost, x, y = heapq.heappop(heap)

        if (x, y) == goal:
            # 回溯路径
            path = [(x, y)]
            while (x, y) != start:
                px, py = parent[y, x]
                path.append((px, py))
                x, y = px, py
            path.reverse()
            return path

        for dx, dy in dirs:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h:
                if grid[ny, nx] > 0 and not visited[ny, nx]:
                    visited[ny, nx] = 1
                    move_cost = 1.414 if dx != 0 and dy != 0 else 1.0
                    new_cost = cost + move_cost
                    heapq.heappush(heap,
                                   (new_cost + heuristic((nx, ny)),
                                    new_cost, nx, ny))
                    parent[ny, nx] = (x, y)

    return None


# ============================================================
class PathFinder:
    def __init__(self, reachable_path, original_path=None, shrink=8):
        self.reachable = cv2.imread(reachable_path, cv2.IMREAD_GRAYSCALE)
        if self.reachable is None:
            raise FileNotFoundError(f"可达图: {reachable_path}")
        self.h, self.w = self.reachable.shape[:2]
        print(f"[可达图] {self.w}x{self.h}")

        # 加载原图（用于显示）
        if original_path and os.path.exists(original_path):
            self.original = cv2.imread(original_path)
        else:
            self.original = cv2.cvtColor(self.reachable, cv2.COLOR_GRAY2BGR)

        self.shrink = shrink  # 缩边像素
        self._update_grid()

        # 显示
        self.scale = min(1000 / self.w, 750 / self.h, 0.5)
        self.offset_x = 0
        self.offset_y = 0

        self.start = None    # (x, y)
        self.goal = None
        self.path = None     # [(x, y), ...]

    # ----------------------------------------------------------
    def _update_grid(self):
        """腐蚀可达图 + 降采样 → 加速 A*"""
        if self.shrink > 0:
            k = np.ones((self.shrink, self.shrink), np.uint8)
            eroded = cv2.erode(self.reachable, k, iterations=1)
        else:
            eroded = self.reachable.copy()

        # 降采样到 ~1/4 （网格缩小 16 倍，A* 快 16 倍+）
        self.ds = 4  # downsample factor
        h2, w2 = self.h // self.ds, self.w // self.ds
        small = cv2.resize(eroded, (w2, h2), interpolation=cv2.INTER_NEAREST)
        # 二值化回去
        _, small = cv2.threshold(small, 127, 255, cv2.THRESH_BINARY)
        self.grid = small
        self.grid_h, self.grid_w = h2, w2

        walkable = np.sum(self.grid == 255) / self.grid.size * 100
        print(f"[网格] shrink={self.shrink}px "
              f"降采样 1/{self.ds} → {w2}x{h2} "
              f"可行走={walkable:.1f}%")

    def _to_grid(self, ix, iy):
        """原图坐标 → 网格坐标"""
        return ix // self.ds, iy // self.ds

    def _to_image(self, gx, gy):
        """网格坐标 → 原图坐标"""
        return gx * self.ds + self.ds // 2, gy * self.ds + self.ds // 2

    def set_shrink(self, val):
        self.shrink = max(0, min(50, val))
        self._update_grid()
        self.path = None  # 网格变了，清除旧路径

    # ----------------------------------------------------------
    def find_path(self):
        if self.start is None or self.goal is None:
            print("[!] 请先设定起点和终点")
            return
        # 转换到网格坐标系
        gs = self._to_grid(*self.start)
        gg = self._to_grid(*self.goal)
        t0 = time.time()
        grid_path = astar(self.grid, gs, gg)
        elapsed = (time.time() - t0) * 1000
        if grid_path:
            # 映射回原图坐标
            self.path = [self._to_image(*p) for p in grid_path]
            dist = sum(np.hypot(self.path[i][0] - self.path[i-1][0],
                                self.path[i][1] - self.path[i-1][1])
                       for i in range(1, len(self.path)))
            print(f"[A*] 路径={len(self.path)}点 "
                  f"距离≈{dist:.0f}px {elapsed:.0f}ms")
        else:
            print(f"[A*] 无路径 (shrink={self.shrink}可能太大 或 "
                  f"起点/终点在缩边后不可达)")

    # ----------------------------------------------------------
    def screen_to_image(self, sx, sy):
        ix = int((sx - self.offset_x) / self.scale)
        iy = int((sy - self.offset_y) / self.scale)
        return max(0, min(ix, self.w - 1)), max(0, min(iy, self.h - 1))

    def image_to_screen(self, ix, iy):
        return (int(ix * self.scale + self.offset_x),
                int(iy * self.scale + self.offset_y))

    # ----------------------------------------------------------
    def render(self):
        FONT = cv2.FONT_HERSHEY_SIMPLEX
        VW, VH = 1050, 720

        dw = int(self.w * self.scale)
        dh = int(self.h * self.scale)
        orig_s = cv2.resize(self.original, (dw, dh))
        reach_s = cv2.resize(self.reachable, (dw, dh),
                              interpolation=cv2.INTER_NEAREST)
        # grid 是降采样的，需要放大回原图尺寸再缩放到显示
        grid_full = cv2.resize(self.grid, (self.w, self.h),
                                interpolation=cv2.INTER_NEAREST)
        grid_s = cv2.resize(grid_full, (dw, dh),
                             interpolation=cv2.INTER_NEAREST)

        canvas = np.zeros((VH, VW, 3), dtype=np.uint8)
        ox, oy = self.offset_x, self.offset_y

        # 可视区域裁剪
        sx1 = max(0, -ox); sy1 = max(0, -oy)
        sx2 = min(dw, -ox + VW); sy2 = min(dh, -oy + VH)
        dx1 = max(0, ox); dy1 = max(0, oy)
        dx2 = min(VW, ox + dw); dy2 = min(VH, oy + dh)
        pw = min(sx2 - sx1, dx2 - dx1)
        ph = min(sy2 - sy1, dy2 - dy1)

        if pw > 0 and ph > 0:
            # 叠加可达/不可达
            src = orig_s.copy()
            m3 = reach_s[:, :, np.newaxis] / 255.0
            g = np.zeros_like(src); g[:, :, 1] = 100
            src = (src * 0.7 + g * 0.3 * m3).astype(np.uint8)
            r = np.zeros_like(src); r[:, :, 2] = 150
            src = (src * (1 - 0.35*(1-m3))
                   + r * 0.35*(1-m3)).astype(np.uint8)

            # 缩边后的网格边界
            edges = cv2.Canny(grid_s, 50, 150)
            src[edges > 0] = [0, 200, 200]

            canvas[dy1:dy1+ph, dx1:dx1+pw] = src[sy1:sy1+ph, sx1:sx1+pw]

        # 画路径
        if self.path:
            pts = [self.image_to_screen(p[0], p[1]) for p in self.path]
            for i in range(1, len(pts)):
                cv2.line(canvas, pts[i-1], pts[i], (0, 255, 0), 2)
            # 起点大圆
            cv2.circle(canvas, pts[0], 8, (0, 255, 0), -1)
            cv2.circle(canvas, pts[0], 10, (255, 255, 255), 2)
            # 终点大圆
            cv2.circle(canvas, pts[-1], 8, (0, 0, 255), -1)
            cv2.circle(canvas, pts[-1], 10, (255, 255, 255), 2)

        # 起点/终点标记（未寻路时）
        if self.start:
            sp = self.image_to_screen(*self.start)
            cv2.circle(canvas, sp, 7, (0, 255, 0), -1)
            cv2.putText(canvas, "S", (sp[0]+10, sp[1]), FONT, 0.5, (0, 255, 0), 2)
        if self.goal:
            gp = self.image_to_screen(*self.goal)
            cv2.circle(canvas, gp, 7, (0, 0, 255), -1)
            cv2.putText(canvas, "G", (gp[0]+10, gp[1]), FONT, 0.5, (0, 0, 255), 2)

        info = (f"shrink={self.shrink}px | "
                f"缩放={self.scale*100:.0f}% | "
                f"S=起点 G=终点 Enter=寻路 R=清除")
        cv2.putText(canvas, info, (5, 18), FONT, 0.38, (0, 255, 0), 1)
        cv2.putText(canvas,
                    "[ ]=调缩边 | IJKL=平移 | +/-=缩放 | S=保存 | Q=退出",
                    (5, VH - 6), FONT, 0.3, (180, 180, 180), 1)

        return canvas

    # ----------------------------------------------------------
    def on_mouse(self, event, sx, sy, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.start = self.screen_to_image(sx, sy)
            self.path = None
            print(f"[起点] {self.start}")
        elif event == cv2.EVENT_RBUTTONDOWN:
            self.goal = self.screen_to_image(sx, sy)
            self.path = None
            print(f"[终点] {self.goal}")
        elif event == cv2.EVENT_MBUTTONDOWN:
            self.dragging = True
            self.drag_sx, self.drag_sy = sx, sy
            self.drag_ox, self.drag_oy = self.offset_x, self.offset_y
        elif event == cv2.EVENT_MOUSEMOVE and getattr(self, 'dragging', False):
            self.offset_x = self.drag_ox + (sx - self.drag_sx)
            self.offset_y = self.drag_oy + (sy - self.drag_sy)
        elif event == cv2.EVENT_MBUTTONUP:
            self.dragging = False
        elif event == cv2.EVENT_MOUSEWHEEL or event == 10:
            old = self.scale
            self.scale = (min(3.0, self.scale * 1.15) if flags > 0
                          else max(0.03, self.scale / 1.15))
            if old != self.scale:
                r = self.scale / old
                self.offset_x = int(sx - r * (sx - self.offset_x))
                self.offset_y = int(sy - r * (sy - self.offset_y))

    # ----------------------------------------------------------
    def save(self, path="path_output.png"):
        canvas = self.render()
        cv2.imwrite(path, canvas)
        print(f"[保存] {path}")


# ============================================================
def main():
    p = argparse.ArgumentParser(description="DeadMaze A* 寻路")
    p.add_argument("reachable", nargs="?", default="map_output_reachable.png")
    p.add_argument("--map", default="map_output.jpg", help="原图（用于显示）")
    p.add_argument("-s", "--shrink", type=int, default=8, help="缩边像素")
    args = p.parse_args()

    if not os.path.exists(args.reachable):
        print(f"[错误]: {args.reachable}")
        print("请先运行 reachability_map.py 生成二值可达图")
        sys.exit(1)

    pf = PathFinder(args.reachable, args.map, args.shrink)

    print("\n=== A* 寻路 ===")
    print("左键=起点 | 右键=终点 | Enter=寻路")
    print("[ ]=缩边 | IJKL=平移 | R=清除 | S=保存 | Q=退出\n")

    cv2.namedWindow("A* 寻路", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty("A* 寻路", cv2.WND_PROP_TOPMOST, 1)
    cv2.setMouseCallback("A* 寻路", pf.on_mouse)

    while True:
        canvas = pf.render()
        cv2.imshow("A* 寻路", canvas)
        key = cv2.waitKey(30) & 0xFF

        if key == ord('q') or key == ord('Q'):
            break
        elif key == 13:  # Enter
            pf.find_path()
        elif key == ord('r') or key == ord('R'):
            pf.path = None
            pf.start = None
            pf.goal = None
            print("[清除]")
        elif key == ord(']'):
            pf.set_shrink(pf.shrink + 2)
        elif key == ord('['):
            pf.set_shrink(pf.shrink - 2)
        elif key == ord('s') or key == ord('S'):
            pf.save()

        elif key in (ord('+'), ord('=')):
            pf.scale = min(3.0, pf.scale * 1.15)
        elif key in (ord('-'), ord('_')):
            pf.scale = max(0.03, pf.scale / 1.15)

        elif key == ord('i'): pf.offset_y += 30
        elif key == ord('k'): pf.offset_y -= 30
        elif key == ord('j'): pf.offset_x += 30
        elif key == ord('l'): pf.offset_x -= 30

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
