"""
DeadMaze - 地图拼接工具
通过 OBS 虚拟摄像头获取游戏画面，自动拼接成大地图

操作:
  A     - 切换自动拼接模式
  C     - 手动拼接当前帧
  S     - 保存地图
  R     - 重置地图
  T     - 切换裁剪框显示
  IJKL  - 微调裁剪框位置
  +/-   - 缩放裁剪框 (四边同时)
  Shift+WASD - 收缩单边 (上/下/左/右)
  Q     - 退出

裁剪框: 只拼接框内区域，屏蔽 HUD/侧边栏/工具栏
"""

import time
import argparse
import json
import os
import ctypes

import cv2
import numpy as np


# ============================================================
# 地图拼接器
# ============================================================
class MapStitcher:
    def __init__(self, min_movement=25, canvas_w=None, canvas_h=None):
        self.canvas = None
        self.canvas_x = 0
        self.canvas_y = 0
        self.prev_frame = None
        self.prev_color = None
        self.total_dx = 0.0
        self.total_dy = 0.0
        self.frame_count = 0
        self.min_movement = min_movement
        self.auto_mode = False
        self.canvas_w = canvas_w  # 固定画布宽 (None=自动扩展)
        self.canvas_h = canvas_h  # 固定画布高

        self.orb = cv2.ORB_create(nfeatures=1500)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.status = "就绪 | C拼接 | A自动 | S保存 | Q退出"

    def compute_offset(self, prev_gray, curr_gray):
        kp1, des1 = self.orb.detectAndCompute(prev_gray, None)
        kp2, des2 = self.orb.detectAndCompute(curr_gray, None)

        if des1 is None or des2 is None or len(des1) < 10 or len(des2) < 10:
            return 0, 0, 0

        matches = self.matcher.match(des1, des2)
        if len(matches) < 8:
            return 0, 0, 0

        matches = sorted(matches, key=lambda m: m.distance)
        dx_list, dy_list = [], []
        for m in matches[:50]:
            p1 = kp1[m.queryIdx].pt
            p2 = kp2[m.trainIdx].pt
            dx_list.append(p2[0] - p1[0])
            dy_list.append(p2[1] - p1[1])

        dx = np.median(dx_list)
        dy = np.median(dy_list)
        inliers = sum(
            1 for ddx, ddy in zip(dx_list, dy_list)
            if abs(ddx - dx) < 5 and abs(ddy - dy) < 5
        )
        confidence = inliers / len(dx_list) if dx_list else 0
        return -dx, -dy, confidence

    def add_frame(self, color_frame):
        gray = cv2.cvtColor(color_frame, cv2.COLOR_BGR2GRAY)
        h, w = color_frame.shape[:2]

        if self.canvas is None:
            if self.canvas_w and self.canvas_h:
                # 固定画布: 初始帧居中
                self.canvas = np.zeros((self.canvas_h, self.canvas_w, 3), dtype=np.uint8)
                px = (self.canvas_w - w) // 2
                py = (self.canvas_h - h) // 2
                self.canvas[py:py+h, px:px+w] = color_frame
                self.canvas_x = -px
                self.canvas_y = -py
            else:
                self.canvas = color_frame.copy()
                self.canvas_x = 0
                self.canvas_y = 0
            self.prev_frame = gray
            self.prev_color = color_frame
            self.frame_count = 1
            return self.canvas, 0, 0, 0

        dx, dy, confidence = self.compute_offset(self.prev_frame, gray)
        movement = np.hypot(dx, dy)
        if movement < self.min_movement or confidence < 0.3:
            return self.canvas, dx, dy, confidence

        self.total_dx += dx
        self.total_dy += dy

        new_x = int(self.total_dx)
        new_y = int(self.total_dy)
        ch, cw = self.canvas.shape[:2]
        old_cx, old_cy = self.canvas_x, self.canvas_y

        if self.canvas_w and self.canvas_h:
            # 固定画布: 限制边界, 不扩展
            left = old_cx
            top = old_cy
        else:
            # 自动扩展
            left = min(old_cx, new_x)
            top = min(old_cy, new_y)
            right = max(old_cx + cw, new_x + w)
            bottom = max(old_cy + ch, new_y + h)
            new_cw = right - left
            new_ch = bottom - top
            new_canvas = np.zeros((new_ch, new_cw, 3), dtype=np.uint8)
            old_place_x = old_cx - left
            old_place_y = old_cy - top
            new_canvas[
                old_place_y:old_place_y + ch,
                old_place_x:old_place_x + cw
            ] = self.canvas
            self.canvas = new_canvas

        frame_place_x = new_x - left
        frame_place_y = new_y - top

        # 裁剪到画布内
        sx1 = max(0, frame_place_x)
        sy1 = max(0, frame_place_y)
        sx2 = min(cw, frame_place_x + w)
        sy2 = min(ch, frame_place_y + h)
        if sx2 <= sx1 or sy2 <= sy1:
            self.prev_frame = gray
            self.prev_color = color_frame
            return self.canvas, dx, dy, confidence

        frame_gray = cv2.cvtColor(color_frame, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(frame_gray, 5, 255, cv2.THRESH_BINARY)
        mask_3ch = cv2.merge([mask, mask, mask])

        roi = self.canvas[sy1:sy2, sx1:sx2]
        src = color_frame[sy1-frame_place_y:sy2-frame_place_y,
                          sx1-frame_place_x:sx2-frame_place_x]
        src_mask = mask_3ch[sy1-frame_place_y:sy2-frame_place_y,
                            sx1-frame_place_x:sx2-frame_place_x]
        np.copyto(roi, src, where=(src_mask > 0))

        self.canvas_x = left
        self.canvas_y = top
        self.prev_frame = gray
        self.prev_color = color_frame
        self.frame_count += 1

        return self.canvas, dx, dy, confidence

    def save(self, path="map_output.jpg"):
        if self.canvas is None:
            print("[!] 尚无地图数据")
            return
        cv2.imwrite(path, self.canvas)
        print(f"[保存] {path}  ({self.canvas.shape[1]}x{self.canvas.shape[0]})")

    def reset(self):
        self.canvas = None
        self.canvas_x = 0
        self.canvas_y = 0
        self.prev_frame = None
        self.prev_color = None
        self.total_dx = 0.0
        self.total_dy = 0.0
        self.frame_count = 0
        print("[重置] 地图已清空")


# ============================================================
# 裁剪框 — 屏蔽 HUD/侧边栏
# ============================================================
class CropRegion:
    """定义画面中的游戏世界区域，排除 UI"""

    def __init__(self, x, y, w, h):
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    def apply(self, frame):
        """裁剪画面，只返回游戏世界部分"""
        h, w = frame.shape[:2]
        x = max(0, min(self.x, w - 1))
        y = max(0, min(self.y, h - 1))
        rw = min(self.w, w - x)
        rh = min(self.h, h - y)
        return frame[y:y + rh, x:x + rw].copy()

    def draw_on(self, frame, color=(0, 255, 0)):
        """在画面上绘制裁剪框"""
        display = frame.copy()
        h, w = display.shape[:2]
        x = max(0, min(self.x, w - 1))
        y = max(0, min(self.y, h - 1))
        rw = min(self.w, w - x)
        rh = min(self.h, h - y)
        cv2.rectangle(display, (x, y), (x + rw, y + rh), color, 2)
        # 半透明阴影覆盖裁剪区外
        overlay = display.copy()
        cv2.rectangle(overlay, (0, 0), (w, y), (0, 0, 0), -1)              # 上
        cv2.rectangle(overlay, (0, y + rh), (w, h), (0, 0, 0), -1)         # 下
        cv2.rectangle(overlay, (0, y), (x, y + rh), (0, 0, 0), -1)         # 左
        cv2.rectangle(overlay, (x + rw, y), (w, y + rh), (0, 0, 0), -1)    # 右
        display = cv2.addWeighted(display, 0.5, overlay, 0.5, 0)
        cv2.rectangle(display, (x, y), (x + rw, y + rh), color, 2)
        cv2.putText(display, f"ROI: ({x},{y}) {rw}x{rh}",
                    (x + 5, y + 20), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, color, 2)
        return display

    def to_dict(self):
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    @staticmethod
    def from_dict(d):
        return CropRegion(d["x"], d["y"], d["w"], d["h"])

    def __repr__(self):
        return f"CropRegion(x={self.x}, y={self.y}, w={self.w}, h={self.h})"


# ============================================================
# 主程序
# ============================================================
CONFIG_FILE = "map_stitcher_crop.json"


def load_crop_config(frame_w, frame_h):
    """从文件加载裁剪配置，没有则返回默认值"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                d = json.load(f)
            crop = CropRegion.from_dict(d)
            print(f"[配置] 已加载裁剪框: {crop}")
            return crop
        except Exception:
            pass
    # 默认：假设 1280x720，排除上方 80px HUD + 左侧 200px 侧边栏
    # 按比例适配实际分辨率
    x = int(frame_w * 200 / 1280)
    y = int(frame_h * 80 / 720)
    w = frame_w - x
    h = frame_h - y
    return CropRegion(x, y, w, h)


def save_crop_config(crop):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(crop.to_dict(), f, indent=2)
    print(f"[配置] 裁剪框已保存到 {CONFIG_FILE}")


def main():
    parser = argparse.ArgumentParser(description="DeadMaze 地图拼接工具")
    parser.add_argument("-c", "--camera", type=int, default=1)
    parser.add_argument("-m", "--min-move", type=int, default=25)
    parser.add_argument("-o", "--output", type=str, default="map_output.jpg")
    parser.add_argument("--crop", type=str, default=None,
                        help="裁剪区域 x,y,w,h (如: 200,80,1080,640)")
    parser.add_argument("--width", type=int, default=None,
                        help="固定画布宽度 (不设则自动扩展)")
    parser.add_argument("--height", type=int, default=None,
                        help="固定画布高度 (不设则自动扩展)")
    args = parser.parse_args()

    # 打开摄像头
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"[错误] 无法打开摄像头索引 {args.camera}")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[信息] 摄像头 {args.camera} 已连接 ({fw}x{fh})")

    # 裁剪配置
    if args.crop:
        parts = [int(p.strip()) for p in args.crop.split(",")]
        crop = CropRegion(*parts)
    else:
        crop = load_crop_config(fw, fh)
    print(f"[信息] 裁剪区: {crop}")

    stitcher = MapStitcher(min_movement=args.min_move,
                           canvas_w=args.width, canvas_h=args.height)
    show_crop = True  # 是否显示裁剪框

    print("=" * 60)
    print("  A     - 切换自动拼接")
    print("  C     - 手动拼接当前帧")
    print("  T     - 切换裁剪框显示")
    print("  IJKL  - 微调裁剪框位置")
    print("  +/-   - 缩放裁剪框 (四边同时)")
    print("  Shift+WASD - 收缩单边 (上/下/左/右)")
    print("  S     - 保存地图 + 裁剪配置")
    print("  R     - 重置地图")
    print("  Q     - 退出")
    print("=" * 60)

    cv2.namedWindow("DeadMaze - 地图拼接", cv2.WINDOW_NORMAL)
    cv2.namedWindow("拼接地图", cv2.WINDOW_NORMAL)

    auto_timer = time.time()
    auto_interval = 0.3

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.01)
            continue

        # 显示画面（带裁剪框叠加）
        if show_crop:
            display = crop.draw_on(frame)
        else:
            display = frame.copy()

        FONT = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(display, stitcher.status, (10, 25),
                    FONT, 0.45, (0, 255, 0), 1)
        cv2.putText(display, f"已拼: {stitcher.frame_count} 帧", (10, 45),
                    FONT, 0.4, (255, 255, 0), 1)
        auto_text = "ON" if stitcher.auto_mode else "OFF"
        cv2.putText(display, f"自动: {auto_text}", (10, 65),
                    FONT, 0.4, (0, 255, 0) if stitcher.auto_mode else (0, 0, 255), 1)

        cv2.imshow("DeadMaze - 地图拼接", display)

        # 拼接地图
        if stitcher.canvas is not None:
            md = stitcher.canvas.copy()
            mh, mw = md.shape[:2]
            max_display = 900
            scale = min(max_display / mw, max_display / mh, 1.0)
            if scale < 1.0:
                md = cv2.resize(md, (int(mw * scale), int(mh * scale)))
            cv2.imshow("拼接地图", md)

        key = cv2.waitKey(1) & 0xFF
        _shift = ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000 != 0  # VK_SHIFT

        # ---- 拼接 ----
        if key == ord('c') or key == ord('C'):
            cropped = crop.apply(frame)
            canvas, dx, dy, conf = stitcher.add_frame(cropped)
            if canvas is not None:
                stitcher.status = (
                    f"拼接 #{stitcher.frame_count} | "
                    f"Δ({dx:.0f},{dy:.0f}) c={conf:.2f}"
                )

        elif key == ord('a') or key == ord('A'):
            stitcher.auto_mode = not stitcher.auto_mode
            stitcher.status = f"自动: {'ON' if stitcher.auto_mode else 'OFF'}"

        # ---- 显示切换 ----
        elif key == ord('t') or key == ord('T'):
            show_crop = not show_crop
            stitcher.status = f"裁剪框: {'显示' if show_crop else '隐藏'}"

        # ---- 微调裁剪框 ----
        elif key == ord('i') or key == ord('I'):
            crop.y = max(0, crop.y - 5)
            stitcher.status = f"裁剪框上移: {crop}"
        elif key == ord('k') or key == ord('K'):
            crop.y += 5
            stitcher.status = f"裁剪框下移: {crop}"
        elif key == ord('j') or key == ord('J'):
            crop.x = max(0, crop.x - 5)
            stitcher.status = f"裁剪框左移: {crop}"
        elif key == ord('l') or key == ord('L'):
            crop.x += 5
            stitcher.status = f"裁剪框右移: {crop}"

        # ---- 缩放裁剪框 (四边同时) ----
        elif key == ord('+') or key == ord('='):
            crop.x = max(0, crop.x - 10)
            crop.y = max(0, crop.y - 10)
            crop.w += 20
            crop.h += 20
            stitcher.status = f"裁剪框放大: {crop}"
        elif key == ord('-') or key == ord('_'):
            crop.x += 10
            crop.y += 10
            crop.w = max(100, crop.w - 20)
            crop.h = max(100, crop.h - 20)
            stitcher.status = f"裁剪框缩小: {crop}"

        # ---- 伸缩单边裁剪框 (Shift+WASD: 收缩上/下/左/右边) ----
        elif key in (ord('w'), ord('W')) and _shift:
            crop.y += 10; crop.h = max(100, crop.h - 10)
            stitcher.status = f"裁剪框收缩上边: {crop}"
        elif key in (ord('s'), ord('S')) and _shift:
            crop.h = max(100, crop.h - 10)
            stitcher.status = f"裁剪框收缩下边: {crop}"
        elif key in (ord('a'), ord('A')) and _shift:
            crop.x += 10; crop.w = max(100, crop.w - 10)
            stitcher.status = f"裁剪框收缩左边: {crop}"
        elif key in (ord('d'), ord('D')) and _shift:
            crop.w = max(100, crop.w - 10)
            stitcher.status = f"裁剪框收缩右边: {crop}"

        # ---- 保存 ----
        elif key == ord('s') or key == ord('S'):
            stitcher.save(args.output)
            save_crop_config(crop)

        # ---- 重置 ----
        elif key == ord('r') or key == ord('R'):
            stitcher.reset()

        elif key == ord('q') or key == ord('Q'):
            # 退出前自动保存裁剪配置
            save_crop_config(crop)
            break

        # ---- 自动拼接 ----
        if stitcher.auto_mode and time.time() - auto_timer > auto_interval:
            cropped = crop.apply(frame)
            canvas, dx, dy, conf = stitcher.add_frame(cropped)
            if canvas is not None and stitcher.frame_count > 0:
                stitcher.status = (
                    f"自动 #{stitcher.frame_count} | "
                    f"Δ({dx:.0f},{dy:.0f}) c={conf:.2f}"
                )
            auto_timer = time.time()

    cap.release()
    cv2.destroyAllWindows()
    print(f"退出。共拼接 {stitcher.frame_count} 帧。")


if __name__ == "__main__":
    main()
