"""
DeadMaze - 二值可达图生成器
从拼接地图中提取可行走区域 → 生成二值图供 A* 寻路

初始化: 检测地图外围黑边 → 标记为不可达，内部全白(可达)
HSV 分割提供初稿，手动涂刷修边

操作:
  左键拖拽 = 涂白(可行走) | 右键拖拽 = 涂黑(障碍)
  IJKL = 平移 | +/- = 缩放 | 中键拖拽 = 平移
  1-4 = 画笔大小 | T = 切换视图
  C = HSV 重分割 | G/E/D = 形态学
  S = 保存 | R = 重置 | Q = 退出
"""

import os
import sys
import argparse

import cv2
import numpy as np


class ReachabilityEditor:
    def __init__(self, image_path):
        self.original = cv2.imread(image_path)
        if self.original is None:
            raise FileNotFoundError(f"图片: {image_path}")
        self.h, self.w = self.original.shape[:2]
        self.base = os.path.splitext(os.path.basename(image_path))[0]
        print(f"[地图] {self.w}x{self.h}")

        self.binary = np.ones((self.h, self.w), dtype=np.uint8) * 255

        # 显示
        self.scale = min(1000 / self.w, 750 / self.h, 1.0)
        self.offset_x = 0
        self.offset_y = 0
        self.show_mode = 0  # 0=叠加 1=二值 2=原图
        self.brush_size = 12

        # 鼠标
        self.drawing = None   # 'white' / 'black' / 'pan'
        self.drag_sx = 0
        self.drag_sy = 0
        self.drag_ox = 0
        self.drag_oy = 0

        # 多边形描边模式
        self.poly_mode = False        # True=描边模式
        self.poly_points = []         # 顶点列表 [(ix,iy), ...]
        self.poly_color = 255         # 填充颜色（左键=白, 右键=黑）

        # 门标记模式
        self.door_mode = False        # True=门标记模式
        self.doors = []               # [(x, y, dx, dy), ...] 门位置+方向
        self._pending_door = None     # (ix, iy) 等待选方向
        self._load_doors()

    # ============================================================
    # 坐标
    # ============================================================
    def screen_to_image(self, sx, sy):
        ix = int((sx - self.offset_x) / self.scale)
        iy = int((sy - self.offset_y) / self.scale)
        return max(0, min(ix, self.w - 1)), max(0, min(iy, self.h - 1))

    # ============================================================
    # 初始化: 黑色边缘 = 不可达
    # ============================================================
    def init_boundary(self):
        """标记外围黑色区域为不可达，内部全白"""
        gray = cv2.cvtColor(self.original, cv2.COLOR_BGR2GRAY)
        # 提高阈值确保黑色区域被排除
        _, data = cv2.threshold(gray, 25, 255, cv2.THRESH_BINARY)
        # 更小的闭合核，避免把黑角连进来
        data = cv2.morphologyEx(data, cv2.MORPH_CLOSE, np.ones((8, 8), np.uint8))
        contours, _ = cv2.findContours(data, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            # 取最大轮廓（地图主体），不用 convexHull（避免凸包囊括黑角）
            largest = max(contours, key=cv2.contourArea)
            interior = np.zeros((self.h, self.w), dtype=np.uint8)
            cv2.drawContours(interior, [largest], -1, 255, -1)
            # 轻微膨胀填补轮廓边缘缝隙
            interior = cv2.dilate(interior, np.ones((5, 5), np.uint8))
            self.binary = interior
            pct = np.sum(interior > 0) / interior.size * 100
            print(f"[边界] 地图内可达={pct:.1f}% 黑色外围=不可达")
        else:
            print("[边界] 未检测到，保持全白")

    # ============================================================
    # HSV 分割
    # ============================================================
    def hsv_segment(self):
        hsv = cv2.cvtColor(self.original, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([0, 0, 40]), np.array([180, 255, 255]))
        self.binary = mask
        pct = np.sum(mask > 0) / mask.size * 100
        print(f"[HSV] 可行走≈{pct:.1f}%")

    # ============================================================
    # 涂刷
    # ============================================================
    def paint(self, ix, iy, color):
        r = max(1, int(self.brush_size / self.scale))
        x1 = max(0, ix - r)
        y1 = max(0, iy - r)
        x2 = min(self.w, ix + r)
        y2 = min(self.h, iy + r)
        self.binary[y1:y2, x1:x2] = color

    # ============================================================
    # 形态学
    # ============================================================
    def morph(self, name):
        k = {'close': (7, cv2.MORPH_CLOSE), 'open': (5, cv2.MORPH_OPEN),
             'erode': (3, cv2.MORPH_ERODE), 'dilate': (3, cv2.MORPH_DILATE)}
        if name in k:
            s, m = k[name]
            self.binary = cv2.morphologyEx(self.binary, m, np.ones((s, s), np.uint8))
            print(f"[形态] {name}")

    # ============================================================
    # 渲染
    # ============================================================
    def render(self):
        VW, VH = 1050, 720
        FONT = cv2.FONT_HERSHEY_SIMPLEX

        dw = int(self.w * self.scale)
        dh = int(self.h * self.scale)
        orig_s = cv2.resize(self.original, (dw, dh))
        bin_s = cv2.resize(self.binary, (dw, dh), interpolation=cv2.INTER_NEAREST)

        canvas = np.zeros((VH, VW, 3), dtype=np.uint8)

        # 可视区域裁剪
        ox, oy = self.offset_x, self.offset_y
        sx1 = max(0, -ox); sy1 = max(0, -oy)
        sx2 = min(dw, -ox + VW); sy2 = min(dh, -oy + VH)
        dx1 = max(0, ox); dy1 = max(0, oy)
        dx2 = min(VW, ox + dw); dy2 = min(VH, oy + dh)
        pw = min(sx2 - sx1, dx2 - dx1)
        ph = min(sy2 - sy1, dy2 - dy1)

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
                    int(p[1]*self.scale + self.offset_y))
                   for p in self.poly_points]
            for i in range(len(pts)):
                cv2.circle(canvas, pts[i], 4, (0, 255, 255), -1)
                if i > 0:
                    cv2.line(canvas, pts[i-1], pts[i], (0, 255, 255), 2)

        # 待选方向的门（闪烁黄点）
        if self._pending_door:
            px, py = self._pending_door
            sx = int(px * self.scale + self.offset_x)
            sy = int(py * self.scale + self.offset_y)
            cv2.circle(canvas, (sx, sy), 8, (0, 255, 255), -1)
            cv2.putText(canvas, "1=左上-右下 2=右上-左下", (sx+10, sy-10),
                        FONT, 0.35, (0, 255, 255), 1)

        # 门标记（紫色圆点+方向箭头）
        for i, (dx, dy, ddx, ddy) in enumerate(self.doors):
            sx = int(dx * self.scale + self.offset_x)
            sy = int(dy * self.scale + self.offset_y)
            cv2.circle(canvas, (sx, sy), 6, (255, 0, 255), -1)
            cv2.arrowedLine(canvas, (sx, sy),
                     (int(sx + ddx * 30), int(sy + ddy * 30)),
                     (255, 0, 255), 2, tipLength=0.4)
            cv2.putText(canvas, f"D{i+1}", (sx+8, sy-8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 0, 255), 1)
            # 鼠标到最后一个点的虚线
            # (虚线在 mouse move 里画不了，这里留空)

        walkable = np.sum(self.binary == 255) / self.binary.size * 100
        view_names = ["叠加", "二值", "原图"]
        color_label = "白(可达)" if self.poly_color == 255 else "黑(不可达)"
        if self.door_mode:
            mode_str = "门标记"
        elif self.poly_mode:
            mode_str = f"描边[{color_label}]"
        else:
            mode_str = "涂刷"
        info = (f"[{mode_str}] 可行走={walkable:.1f}% | "
                f"缩放={self.scale*100:.0f}% | 画笔={self.brush_size}px | "
                f"视图: {view_names[self.show_mode]}")
        cv2.putText(canvas, info, (5, 18), FONT, 0.38, (0, 255, 0), 1)
        cv2.putText(canvas,
                    "P=描边 D=标记门 左/右键=操作 F=切换颜色 "
                    "IJKL=平移 +/-=缩放 1-4画笔 T=视图 S=保存 Q=退出",
                    (5, VH - 6), FONT, 0.3, (180, 180, 180), 1)
        return canvas

    # ============================================================
    # 鼠标回调
    # ============================================================
    def _fill_polygon(self):
        """填充当前多边形"""
        if len(self.poly_points) < 3:
            print("[描边] 至少需要3个顶点")
            return
        pts = np.array(self.poly_points, dtype=np.int32).reshape((-1, 1, 2))
        cv2.fillPoly(self.binary, [pts], self.poly_color)
        label = "可行走" if self.poly_color == 255 else "障碍"
        print(f"[描边] 填充{len(self.poly_points)}边形 → {label}")
        self.poly_points = []

    # ============================================================
    # 门标记
    # ============================================================
    def _door_file(self):
        return f"{self.base}_doors.json"

    def _load_doors(self):
        path = self._door_file()
        if os.path.exists(path):
            import json
            with open(path, 'r') as f:
                self.doors = json.load(f)
            print(f"[门] 加载 {len(self.doors)} 个门")

    def _save_doors(self):
        import json
        with open(self._door_file(), 'w') as f:
            json.dump(self.doors, f)
        print(f"[门] 保存 {len(self.doors)} 个门")

    def _add_door(self, ix, iy):
        """放置门位置，等待选择方向"""
        self._pending_door = (ix, iy)
        print(f"[门] 位置({ix},{iy}) 请按方向: 1=左上↔右下 2=右上↔左下")

    def _set_door_dir(self, dir_idx):
        """1=左上↔右下  2=右上↔左下  门双向通行"""
        if self._pending_door is None:
            print("[门] 请先点击放置门位置")
            return
        dirs = [(1, 1), (1, -1)]  # 0=左上↔右下  1=右上↔左下
        if dir_idx not in [0, 1]:
            print("[门] 请按1(左上↔右下)或2(右上↔左下)")
            return
        dx, dy = dirs[dir_idx]
        ix, iy = self._pending_door
        self.doors.append((ix, iy, dx, dy))
        label = "左上↔右下" if dy == 1 else "右上↔左下"
        print(f"[门] #{len(self.doors)} ({ix},{iy}) {label}")
        self._pending_door = None
        self._save_doors()

    def _del_door(self, ix, iy):
        for i, (door_x, door_y, _, _) in enumerate(self.doors):
            if abs(door_x - ix) < 30 and abs(door_y - iy) < 30:
                self.doors.pop(i)
                print(f"[门] 删除 #{i+1} ({door_x},{door_y})")
                self._save_doors()
                return
        print(f"[门] ({ix},{iy}) 附近无门")

    def on_mouse(self, event, sx, sy, flags, param):
        ix, iy = self.screen_to_image(sx, sy)

        if self.door_mode:
            if event == cv2.EVENT_LBUTTONDOWN:
                self._add_door(ix, iy)
            elif event == cv2.EVENT_RBUTTONDOWN:
                self._del_door(ix, iy)
            return

        if self.poly_mode:
            # === 描边模式 ===
            if event == cv2.EVENT_LBUTTONDOWN:
                self.poly_points.append((ix, iy))
                print(f"[描边] 顶点#{len(self.poly_points)} ({ix},{iy})",
                      flush=True)
            elif event == cv2.EVENT_RBUTTONDOWN:
                self._fill_polygon()  # 用当前 poly_color 填充
            return  # 描边模式下不触发涂刷

        # === 涂刷模式 ===
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drawing = 'white'
            self.paint(ix, iy, 255)
            print(f"[涂白] ({ix},{iy})", flush=True)

        elif event == cv2.EVENT_RBUTTONDOWN:
            self.drawing = 'black'
            self.paint(ix, iy, 0)
            print(f"[涂黑] ({ix},{iy})", flush=True)

        elif event == cv2.EVENT_MBUTTONDOWN:
            self.drawing = 'pan'
            self.drag_sx, self.drag_sy = sx, sy
            self.drag_ox, self.drag_oy = self.offset_x, self.offset_y

        elif event == cv2.EVENT_MOUSEMOVE:
            if self.drawing == 'white':
                ix, iy = self.screen_to_image(sx, sy)
                self.paint(ix, iy, 255)
            elif self.drawing == 'black':
                ix, iy = self.screen_to_image(sx, sy)
                self.paint(ix, iy, 0)
            elif self.drawing == 'pan':
                self.offset_x = self.drag_ox + (sx - self.drag_sx)
                self.offset_y = self.drag_oy + (sy - self.drag_sy)

        elif event in (cv2.EVENT_LBUTTONUP, cv2.EVENT_RBUTTONUP,
                       cv2.EVENT_MBUTTONUP):
            self.drawing = None

        elif event == cv2.EVENT_MOUSEWHEEL or event == 10:
            old = self.scale
            self.scale = (min(3.0, self.scale * 1.15) if flags > 0
                          else max(0.03, self.scale / 1.15))
            if old != self.scale:
                r = self.scale / old
                self.offset_x = int(sx - r * (sx - self.offset_x))
                self.offset_y = int(sy - r * (sy - self.offset_y))

    # ============================================================
    def save(self, path=None):
        if path is None:
            path = f"{self.base}_reachable.png"
        cv2.imwrite(path, self.binary)
        pct = np.sum(self.binary == 255) / self.binary.size * 100
        print(f"[保存] {path} 可行走={pct:.1f}%")


# ============================================================
def main():
    p = argparse.ArgumentParser()
    p.add_argument("image", nargs="?", default="map_output.jpg")
    p.add_argument("-o", "--output", default=None)
    args = p.parse_args()

    if not os.path.exists(args.image):
        print(f"[错误]: {args.image}")
        sys.exit(1)

    editor = ReachabilityEditor(args.image)

    # 尝试加载已有标注（断点续标）
    save_path = args.output or f"{editor.base}_reachable.png"
    if os.path.exists(save_path):
        saved = cv2.imread(save_path, cv2.IMREAD_GRAYSCALE)
        if saved is not None and saved.shape == (editor.h, editor.w):
            editor.binary = saved
            pct = np.sum(saved == 255) / saved.size * 100
            print(f"[加载] 已有标注 {save_path} (可行走={pct:.1f}%)")
        else:
            editor.init_boundary()
    else:
        editor.init_boundary()

    print("\n=== 二值可达图 ===")
    print("初始化: 外围黑边=不可达, 内部=全白可达")
    print("左键=涂白 | 右键=涂黑 | P/M=描边 | IJKL=平移 | +/-=缩放")
    print("1-4=画笔 | C=HSV | T=视图 | S=保存 | Q=保存+退出\n")

    cv2.namedWindow("二值可达图", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty("二值可达图", cv2.WND_PROP_TOPMOST, 1)
    cv2.setMouseCallback("二值可达图", editor.on_mouse)

    while True:
        canvas = editor.render()
        cv2.imshow("二值可达图", canvas)
        key = cv2.waitKey(30) & 0xFF

        if key == ord('q') or key == ord('Q'):
            editor.save(args.output or f"{editor.base}_reachable.png")
            print("[退出] 进度已自动保存")
            break

        # 多边形模式
        elif key in (ord('p'), ord('P'), ord('m'), ord('M')):
            editor.door_mode = False
            editor.poly_mode = not editor.poly_mode
            editor.poly_points = []
            m = "描边" if editor.poly_mode else "涂刷"
            print(f"[模式] {m}")
        elif key in (ord('d'), ord('D')):
            editor.poly_mode = False
            editor.door_mode = not editor.door_mode
            m = "门标记" if editor.door_mode else "涂刷"
            print(f"[模式] {m}")
        elif editor.poly_mode and key == 27:  # Esc
            editor.poly_points = []
            print("[描边] 已取消")
        elif editor.poly_mode and key == 13:  # Enter
            editor._fill_polygon()
        elif editor.poly_mode and key in (ord('f'), ord('F')):
            editor.poly_color = 0 if editor.poly_color == 255 else 255
            label = "可达(白)" if editor.poly_color == 255 else "不可达(黑)"
            print(f"[描边] 填充颜色切换→ {label}")

        elif key == ord('t') or key == ord('T'):
            editor.show_mode = (editor.show_mode + 1) % 3
        elif key == ord('c') or key == ord('C'):
            editor.hsv_segment()
        elif key == ord('g') or key == ord('G'):
            editor.morph('close')
        elif key == ord('e') or key == ord('E'):
            editor.morph('erode')
        elif key == ord('d') or key == ord('D'):
            editor.morph('dilate')
        elif key == ord('o') or key == ord('O'):
            editor.morph('open')
        elif key == ord('s') or key == ord('S'):
            editor.save(args.output)
        elif key == ord('r') or key == ord('R'):
            editor.init_boundary()

        elif key in (ord('+'), ord('=')):
            editor.scale = min(3.0, editor.scale * 1.15)
        elif key in (ord('-'), ord('_')):
            editor.scale = max(0.03, editor.scale / 1.15)

        elif key == ord('i'): editor.offset_y += 30
        elif key == ord('k'): editor.offset_y -= 30
        elif key == ord('j'): editor.offset_x += 30
        elif key == ord('l'): editor.offset_x -= 30

        elif key == ord('1'):
            if editor.door_mode: editor._set_door_dir(0)
            else: editor.brush_size = 4
        elif key == ord('2'):
            if editor.door_mode: editor._set_door_dir(1)
            else: editor.brush_size = 12
        elif key == ord('3'): editor.brush_size = 30
        elif key == ord('4'): editor.brush_size = 80

    cv2.destroyAllWindows()
    print("退出.")


if __name__ == "__main__":
    main()
