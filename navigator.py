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
"""

# ============================================================
# 阈值配置（调试时修改这里）
# ============================================================
WAYPOINT_REACH_THRESHOLD = 17     # 像素，到达路标的判定距离
GOAL_REACH_THRESHOLD = 60         # 像素，到达终点的判定距离(比路标宽松)
PATH_DEVIATION_THRESHOLD = 120    # 像素，偏离路径多久重规划
MOVE_DURATION = 0.5            # 秒，每次按键时长
TRACK_INTERVAL = 0.1             # 秒，追踪间隔（自动模式）
LOOKAHEAD_DIST =100           # 像素，向前看多少个像素选路标
SHRINK = 80

# 门附近参数 (距门 DOOR_PROXIMITY px 内自动切换)
DOOR_PROXIMITY = 200
DOOR_MOVE_DURATION = 0.2
DOOR_WAYPOINT_REACH = 20
DOOR_PATH_DEVIATION = 80
DOOR_LOOKAHEAD = 60
MIN_8DIR_SEGMENT = 110  # 8方向拟合最小段长(px),短于此不拟合
# ============================================================

import os
import sys
import time
import heapq
import argparse
import threading

import cv2
import numpy as np

# 后台操控
try:
    from game_controller import DeadMazeController
    HAS_CONTROLLER = True
except Exception:
    HAS_CONTROLLER = False
    print("[!] game_controller.py 未加载，仅模拟移动")


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
# A* (同 pathfinder)
# ============================================================
def _remove_backtracks(path):
    """去掉路径中的回头路 (A→B→C→B→D → A→B→D)"""
    if len(path) < 4:
        return path
    # 贪心移除: 从后往前找最近的重复点
    seen = {}
    for i, p in enumerate(path):
        key = (p[0], p[1])
        if key in seen:
            # 找到回头路，切除 seen[key]..i 这一段
            prev = seen[key]
            path = path[:prev] + path[i:]
            return _remove_backtracks(path)  # 递归直到干净
        seen[key] = i
    return path


def _snap_to_8dir(path, grid):
    """将A*路径拟合为8方向线段序列, 每段纯一个方向"""
    if len(path) < 2:
        return path
    h, w = grid.shape
    result = [path[0]]
    i = 0
    while i < len(path) - 1:
        best_dir = None
        best_j = i + 1
        # 对每个8方向找能延伸到的最远点
        for dx, dy, *_ in DIR_VECTORS:
            j = i + 1
            while j < len(path):
                ex = path[j][0] - path[i][0]
                ey = path[j][1] - path[i][1]
                proj = ex * dx + ey * dy
                perp = abs(ex * dy - ey * dx)
                if proj > 0 and perp < 40:  # 垂直偏差<40px
                    j += 1
                else:
                    break
            if j > best_j:
                best_j = j
                best_dir = (dx, dy)
        # 用最佳方向延伸到最远点
        if best_dir and best_j > i + 2:
            ex = path[best_j - 1][0] - path[i][0]
            ey = path[best_j - 1][1] - path[i][1]
            proj = ex * best_dir[0] + ey * best_dir[1]
            if proj >= MIN_8DIR_SEGMENT:
                end_x = int(path[i][0] + best_dir[0] * proj)
                end_y = int(path[i][1] + best_dir[1] * proj)
                result.append((end_x, end_y))
                i = best_j - 1
                continue
        result.append(path[i + 1])
        i += 1
    return result


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
        # 缩边腐蚀: 3×3核多次迭代, 每次缩1格(4px)
        if SHRINK > 0:
            iters = int(np.ceil(SHRINK / self.DS))
            small = cv2.erode(small, np.ones((3, 3), np.uint8), iterations=iters)
        self.grid = small
        pct = np.sum(self.grid > 0) / self.grid.size * 100
        print(f"[网格] {w2}x{h2} shrink={SHRINK}px 可行走={pct:.1f}%")

        # 原图（显示用）
        self.map_img = cv2.imread(map_path) if os.path.exists(map_path) else None

        # 加载门（仅用于近门检测）
        import json as _json
        door_file = reachable_path.replace('_reachable.png','_doors.json').replace('_reachable.jpg','_doors.json')
        if not os.path.exists(door_file):
            door_file = os.path.splitext(reachable_path)[0] + '_doors.json'
        self.doors = []
        if os.path.exists(door_file):
            with open(door_file,'r') as f:
                self.doors = _json.load(f)
            print(f"[门] {len(self.doors)} 个门")

        # 后台操控
        self.ctrl = None
        if HAS_CONTROLLER:
            try:
                self.ctrl = DeadMazeController()
                self.ctrl.find_window()
            except Exception as e:
                print(f"[!] 控制器: {e}")

        # 追踪器
        from map_tracker import Tracker
        self.tracker = Tracker(map_path, camera_id)
        self.position = None  # (cx, cy) 当前位置，由用户点击设定

        # 状态机
        self.STATE_IDLE = 0
        self.STATE_READY = 1     # 路径已规划，等待开始
        self.STATE_NAVIGATING = 2
        self.STATE_PAUSED = 3
        self.state = self.STATE_IDLE

        self.start = None          # 起点 (原图坐标)
        self.goal = None           # 终点
        self.path = None           # [(x,y)] 原图坐标
        self.grid_path = None      # 网格坐标路径
        self.current_waypoint = 0

        # 显示
        self.scale = min(1000 / self.w, 750 / self.h, 0.5)
        self.offset_x = 0
        self.offset_y = 0

        self.status_msg = "点击地图设定起点和终点"

    # ----------------------------------------------------------
    # 坐标转换
    # ----------------------------------------------------------
    def to_grid(self, ix, iy):
        return ix // self.DS, iy // self.DS

    def to_image(self, gx, gy):
        return gx * self.DS + self.DS // 2, gy * self.DS + self.DS // 2

    def scr2img(self, sx, sy):
        ix = int((sx - self.offset_x) / self.scale)
        iy = int((sy - self.offset_y) / self.scale)
        return max(0, min(ix, self.w - 1)), max(0, min(iy, self.h - 1))

    def img2scr(self, ix, iy):
        return (int(ix * self.scale + self.offset_x),
                int(iy * self.scale + self.offset_y))

    # ----------------------------------------------------------
    def _snap_grid(self, gx, gy):
        """吸附到最近的可行走网格点（缩边后起点可能不可达）"""
        if self.grid[gy, gx] > 0:
            return gx, gy
        gh, gw = self.grid.shape
        from collections import deque
        vis = np.zeros((gh, gw), np.uint8)
        q = deque([(gx, gy, 0)])
        vis[gy, gx] = 1
        dirs = [(0,1),(1,0),(0,-1),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)]
        while q:
            cx, cy, d = q.popleft()
            if self.grid[cy, cx] > 0:
                return cx, cy
            if d > 30: break
            for dx, dy in dirs:
                nx, ny = cx+dx, cy+dy
                if 0<=nx<gw and 0<=ny<gh and not vis[ny,nx]:
                    vis[ny,nx]=1; q.append((nx,ny,d+1))
        return gx, gy  # 找不到就返回原值

    def plan_path(self):
        if self.start is None or self.goal is None:
            return False
        gs = self._snap_grid(*self.to_grid(*self.start))
        gg = self._snap_grid(*self.to_grid(*self.goal))
        self.grid_path = astar(self.grid, gs, gg)
        if self.grid_path:
            self.path = [self.to_image(*p) for p in self.grid_path]
            self.path = _remove_backtracks(self.path)
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
            if d >= getattr(self,'_la',LOOKAHEAD_DIST) and d < best_dist:
                best = i
                best_dist = d
        if best is None and self.current_waypoint < len(self.path):
            best = len(self.path) - 1  # 最后一个点
        return best

    def check_deviation(self, px, py):
        """检查是否偏离路径太远"""
        min_dist = 99999
        for i in range(self.current_waypoint, min(self.current_waypoint + 20, len(self.path))):
            wx, wy = self.path[i]
            d = np.hypot(wx - px, wy - py)
            if d < min_dist:
                min_dist = d
        return min_dist > getattr(self,'_pd',PATH_DEVIATION_THRESHOLD)

    # ----------------------------------------------------------
    def _near_door(self, px, py):
        for dx, dy, _, _ in self.doors:
            if np.hypot(px-dx, py-dy) < DOOR_PROXIMITY:
                return True
        return False

    def _params(self, px, py):
        if self._near_door(px, py):
            return (DOOR_MOVE_DURATION, DOOR_WAYPOINT_REACH,
                    DOOR_PATH_DEVIATION, DOOR_LOOKAHEAD)
        return (MOVE_DURATION, WAYPOINT_REACH_THRESHOLD,
                PATH_DEVIATION_THRESHOLD, LOOKAHEAD_DIST)

    def navigate_step(self):
        """单步导航: 定位 → 找路标 → 移动"""
        if self.state != self.STATE_NAVIGATING:
            return

        # 1. 定位（ORB 追踪更新位置）
        if self.tracker.last_position is None:
            # 首次：用点击的起点作为初始位置
            self.tracker.last_position = self.start
            self.tracker.need_click = False
            self.tracker.prev_frame = None
        self.tracker.track()
        if self.tracker.last_position:
            self.position = self.tracker.last_position
        px, py = self.position if self.position else self.start

        # 动态参数（近门时切换）
        md, wr, pd, la = self._params(px, py)
        self._md, self._wr, self._pd, self._la = md, wr, pd, la

        # 2. 检查是否到达终点
        gx, gy = self.goal
        if np.hypot(px - gx, py - gy) < GOAL_REACH_THRESHOLD:
            print("[!] 到达终点!")
            self.state = self.STATE_IDLE
            self.status_msg = "已到达终点"
            return

        # 3. 检查偏离（用动态阈值）
        if self.check_deviation(px, py):
            print(f"[!] 偏离路径 > {pd}px，重规划")
            self.start = (px, py)
            self.plan_path()
            if self.state != self.STATE_READY:
                self.status_msg = "重规划失败"
                self.state = self.STATE_IDLE
                return
            self.state = self.STATE_NAVIGATING

        # 4. 找下一个路标（用动态 lookahead）
        wp_idx = self.get_next_waypoint(px, py)
        if wp_idx is None:
            self.status_msg = "无路标"
            return
        self.current_waypoint = max(self.current_waypoint, wp_idx - 2)
        wx, wy = self.path[wp_idx]

        # 检查是否到达路标（用动态阈值）
        if np.hypot(px - wx, py - wy) < wr:
            self.current_waypoint = wp_idx + 1
            if self.current_waypoint >= len(self.path):
                self.current_waypoint = len(self.path) - 1

        # 5. 8方向拟合 + 移动（用动态步长）
        dx = wx - px
        dy = wy - py
        di = best_direction(dx, dy)
        keys = DIR_VECTORS[di][2:]

        if self.ctrl:
            for k in keys:
                self.ctrl.key_down(
                    getattr(self.ctrl, f'VK_{k}', ord(k)))
            time.sleep(md)
            for k in keys:
                self.ctrl.key_up(
                    getattr(self.ctrl, f'VK_{k}', ord(k)))

        self.status_msg = (f"→ ({wx},{wy}) dir={di} "
                           f"Δ({dx:.0f},{dy:.0f}) {keys}")

    # ----------------------------------------------------------
    def render(self):
        VW, VH = 1050, 720
        FONT = cv2.FONT_HERSHEY_SIMPLEX

        if self.map_img is None:
            canvas = np.zeros((VH, VW, 3), dtype=np.uint8)
        else:
            dw = int(self.w * self.scale)
            dh = int(self.h * self.scale)
            s = cv2.resize(self.map_img, (dw, dh))
            canvas = np.zeros((VH, VW, 3), dtype=np.uint8)
            ox, oy = self.offset_x, self.offset_y
            sx1 = max(0, -ox); sy1 = max(0, -oy)
            sx2 = min(dw, -ox+VW); sy2 = min(dh, -oy+VH)
            dx1 = max(0, ox); dy1 = max(0, oy)
            dx2 = min(VW, ox+dw); dy2 = min(VH, oy+dh)
            pw = min(sx2-sx1, dx2-dx1)
            ph = min(sy2-sy1, dy2-dy1)
            if pw > 0 and ph > 0:
                canvas[dy1:dy1+ph, dx1:dx1+pw] = s[sy1:sy1+ph, sx1:sx1+pw]

        # 可达图叠加
        rs = cv2.resize(self.reachable, (int(self.w*self.scale),
                        int(self.h*self.scale)),
                        interpolation=cv2.INTER_NEAREST)
        edges = cv2.Canny(rs, 50, 150)
        ox, oy = self.offset_x, self.offset_y
        sy1 = max(0, -oy); sy2 = min(rs.shape[0], -oy+VH)
        sx1 = max(0, -ox); sx2 = min(rs.shape[1], -ox+VW)
        dx1 = max(0, ox); dy1 = max(0, oy)
        pw = min(sx2-sx1, dx2-dx1-VW) if 'dx2' in dir() else min(sx2-sx1, VW-dx1)
        # (简化，只画在 canvas 内)
        for y in range(sy1, sy2):
            for x in range(sx1, sx2):
                if edges[y, x]:
                    cy = dy1 + (y - sy1)
                    cx = dx1 + (x - sx1)
                    if 0 <= cy < VH and 0 <= cx < VW:
                        canvas[cy, cx] = [0, 200, 200]

        # 路径
        if self.path:
            pts = [self.img2scr(*p) for p in self.path]
            for i in range(1, len(pts)):
                cv2.line(canvas, pts[i-1], pts[i], (0, 255, 0), 2)
            # 当前路标
            if self.current_waypoint < len(pts):
                cv2.circle(canvas, pts[self.current_waypoint], 8,
                           (255, 255, 0), -1)

        # 起点 终点
        if self.start:
            sp = self.img2scr(*self.start)
            cv2.circle(canvas, sp, 7, (0, 255, 0), -1)
            cv2.putText(canvas, "S", (sp[0]+10, sp[1]), FONT, 0.5, (0, 255, 0), 2)
        if self.goal:
            gp = self.img2scr(*self.goal)
            cv2.circle(canvas, gp, 7, (0, 0, 255), -1)
            cv2.putText(canvas, "G", (gp[0]+10, gp[1]), FONT, 0.5, (0, 0, 255), 2)

        # 实时位置
        if self.position:
            tp = self.img2scr(*self.position)
            cv2.circle(canvas, tp, 9, (0, 255, 255), -1)
            cv2.circle(canvas, tp, 11, (255, 255, 255), 2)

        # 状态
        state_names = ["空闲", "就绪(按Enter开始)", "导航中", "已暂停"]
        cv2.putText(canvas, f"[{state_names[self.state]}] {self.status_msg}",
                    (5, 18), FONT, 0.38, (0, 255, 0), 1)
        cv2.putText(canvas,
                    "左键=起点 右键=终点 Enter=开始 空格=暂停 Q=退出",
                    (5, VH-6), FONT, 0.3, (180, 180, 180), 1)

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
        elif event == cv2.EVENT_MOUSEMOVE and getattr(self, '_dragging', False):
            self.offset_x = self._dox + (sx - self._dsx)
            self.offset_y = self._doy + (sy - self._dsy)
        elif event == cv2.EVENT_MBUTTONUP:
            self._dragging = False
        elif event == cv2.EVENT_MOUSEWHEEL or event == 10:
            old = self.scale
            self.scale = (min(3.0, self.scale * 1.15) if flags > 0
                          else max(0.03, self.scale / 1.15))
            if old != self.scale:
                r = self.scale / old
                self.offset_x = int(sx - r*(sx-self.offset_x))
                self.offset_y = int(sy - r*(sy-self.offset_y))


# ============================================================
def main():
    p = argparse.ArgumentParser()
    p.add_argument("reachable", nargs="?", default="map_output_reachable.png")
    p.add_argument("--map", default="map_output.jpg")
    p.add_argument("-c", "--camera", type=int, default=1)
    args = p.parse_args()

    if not os.path.exists(args.reachable):
        print(f"[错误] {args.reachable} 不存在")
        sys.exit(1)

    nav = Navigator(args.reachable, args.map, args.camera)

    print("\n=== 路径导航闭环 ===")
    print("左键=起点 | 右键=终点(A*规划)")
    print("Enter=开始导航 | 空格=暂停 | Esc=停止 | Q=退出\n")

    cv2.namedWindow("导航", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty("导航", cv2.WND_PROP_TOPMOST, 1)
    cv2.setMouseCallback("导航", nav.on_mouse)

    last_nav = 0
    # 先做一次初始定位
    print("[定位] 请在地图上点击你的当前位置作为起点...")

    while True:
        canvas = nav.render()
        cv2.imshow("导航", canvas)
        key = cv2.waitKey(30) & 0xFF

        if key == ord('q') or key == ord('Q'):
            break
        elif key == 13:  # Enter
            if nav.state == nav.STATE_READY:
                # 先测试控制器
                if nav.ctrl:
                    print("[测试] 发送 W 键 0.2s...")
                    nav.ctrl.press(nav.ctrl.VK_W, 0.2)
                    time.sleep(0.3)
                    print("[测试] 发送 D 键 0.2s...")
                    nav.ctrl.press(nav.ctrl.VK_D, 0.2)
                    time.sleep(0.3)
                    print("[测试] 控制器测试完成，观察角色是否移动")
                nav.state = nav.STATE_NAVIGATING
                print("[导航] 开始!")
        elif key == ord(' '):  # 空格
            if nav.state == nav.STATE_NAVIGATING:
                nav.state = nav.STATE_PAUSED
                print("[暂停]")
            elif nav.state == nav.STATE_PAUSED:
                nav.state = nav.STATE_NAVIGATING
                print("[继续]")
        elif key == 27:  # Esc
            nav.state = nav.STATE_IDLE
            nav.status_msg = "已停止"
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
