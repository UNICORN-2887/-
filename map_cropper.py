"""
DeadMaze - 地图物体切割工具 (FastSAM)
从拼接好的大地图中点击物体，自动抠出带透明通道的 PNG

原理: FastSAM 一次分割全图 → 点击物体 → 提取对应 mask → 保存 PNG

操作:
  左键点击  - 选中物体（自动高亮 mask）
  右键点击  - 添加到当前选区（合并多个区域）
  Enter    - 保存当前选中的物体
  Esc      - 清除当前选区
  Z        - 撤销上一次选中的区域
  +/-      - 缩放
  滚轮     - 缩放 | 中键拖拽 - 平移
  S        - 列出已保存的物体
  Q        - 退出
"""

import os
import sys
import argparse
import json
import time

import cv2
import numpy as np

from ultralytics import FastSAM


# ============================================================
# 交互式地图切割器
# ============================================================
class MapCropperSAM:
    def __init__(self, image_path):
        # 加载地图
        self.original = cv2.imread(image_path)
        if self.original is None:
            raise FileNotFoundError(f"无法加载图片: {image_path}")
        self.h, self.w = self.original.shape[:2]
        self.base_name = os.path.splitext(os.path.basename(image_path))[0]

        # 显示
        self.scale = min(900 / self.w, 700 / self.h, 1.0)
        self.offset_x = 0
        self.offset_y = 0
        self.dragging = False
        self.drag_start = (0, 0)
        self.drag_off_start = (0, 0)

        # 加载 FastSAM
        print("[加载] FastSAM 模型中...")
        self.model = FastSAM('FastSAM-s.pt')
        print("[就绪] FastSAM 已加载")

        # 运行全图分割
        print("[分割] 正在分析全图...")
        t0 = time.time()
        self.results = self.model(self.original, device='cpu',
                                   retina_masks=True, imgsz=1024,
                                   conf=0.35, iou=0.6)
        self.masks = self.results[0].masks
        elapsed = time.time() - t0
        if self.masks is not None:
            print(f"[分割] 完成! 发现 {len(self.masks)} 个区域 ({elapsed:.1f}s)")
        else:
            print("[分割] 未检测到任何区域，尝试降低 conf 阈值")
            self.results = self.model(self.original, device='cpu',
                                       retina_masks=True, imgsz=1024,
                                       conf=0.2, iou=0.5)
            self.masks = self.results[0].masks
            if self.masks is not None:
                print(f"[分割] 完成! 发现 {len(self.masks)} 个区域")
            else:
                print("[分割] 仍未检测到区域")
                self.masks = None

        # 选中状态
        self.selected_indices = []   # 当前选中的 mask 索引
        self.highlight_mask = None   # 合并后的高亮 mask
        self.crops = []              # 已保存: [(name, bgra_image), ...]
        self.output_dir = f"cropped_{self.base_name}"

    # ----------------------------------------------------------
    # 坐标转换
    # ----------------------------------------------------------
    def screen_to_image(self, sx, sy):
        ix = int((sx - self.offset_x) / self.scale)
        iy = int((sy - self.offset_y) / self.scale)
        return max(0, min(ix, self.w - 1)), max(0, min(iy, self.h - 1))

    def image_to_screen(self, ix, iy):
        return int(ix * self.scale + self.offset_x), int(iy * self.scale + self.offset_y)

    # ----------------------------------------------------------
    # 查找点击位置对应的 mask
    # ----------------------------------------------------------
    def find_mask_at(self, ix, iy):
        """返回包含 (ix,iy) 的 mask 索引列表"""
        if self.masks is None:
            return []
        found = []
        mask_data = self.masks.data.cpu().numpy()  # [N, H, W]
        for i, m in enumerate(mask_data):
            if m[iy, ix] > 0.5:
                found.append(i)
        return found

    # ----------------------------------------------------------
    # 构建高亮显示
    # ----------------------------------------------------------
    def build_highlight(self):
        if not self.selected_indices or self.masks is None:
            self.highlight_mask = None
            return
        mask_data = self.masks.data.cpu().numpy()
        combined = np.zeros((self.h, self.w), dtype=np.uint8)
        for idx in self.selected_indices:
            combined = np.maximum(combined, (mask_data[idx] * 255).astype(np.uint8))
        self.highlight_mask = combined

    # ----------------------------------------------------------
    # 获取选中物体的裁剪图（带透明通道）
    # ----------------------------------------------------------
    def get_cropped_object(self):
        if not self.selected_indices or self.masks is None:
            return None
        mask_data = self.masks.data.cpu().numpy()
        combined_mask = np.zeros((self.h, self.w), dtype=np.uint8)
        for idx in self.selected_indices:
            combined_mask = np.maximum(
                combined_mask, (mask_data[idx] * 255).astype(np.uint8)
            )

        # 找到 mask 的边界框
        ys, xs = np.where(combined_mask > 127)
        if len(ys) == 0:
            return None
        x1, y1 = xs.min(), ys.min()
        x2, y2 = xs.max() + 1, ys.max() + 1

        # 裁剪
        crop = self.original[y1:y2, x1:x2].copy()
        alpha = combined_mask[y1:y2, x1:x2]

        # BGRA
        bgra = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
        bgra[:, :, 3] = alpha
        return bgra, (x1, y1, x2 - x1, y2 - y1)

    # ----------------------------------------------------------
    # 保存
    # ----------------------------------------------------------
    def save_selected(self, name):
        result = self.get_cropped_object()
        if result is None:
            print("[!] 没有选中物体")
            return
        bgra, rect = result
        os.makedirs(self.output_dir, exist_ok=True)
        path = os.path.join(self.output_dir, f"{name}.png")
        cv2.imwrite(path, bgra)
        self.crops.append((name, bgra, rect))
        print(f"[保存] {name} ({rect[2]}x{rect[3]}) → {path}")

        # 保存坐标
        info_path = os.path.join(self.output_dir, "_crops_info.json")
        with open(info_path, 'w') as f:
            json.dump([
                {"name": n, "x": r[0], "y": r[1], "w": r[2], "h": r[3]}
                for n, _, r in self.crops
            ], f, indent=2, ensure_ascii=False)

        # 清空选区
        self.selected_indices = []
        self.highlight_mask = None

    # ----------------------------------------------------------
    # 渲染
    # ----------------------------------------------------------
    def render(self):
        dw = int(self.w * self.scale)
        dh = int(self.h * self.scale)
        resized = cv2.resize(self.original, (dw, dh))

        canvas = np.zeros((max(dh, 720), max(dw, 960), 3), dtype=np.uint8)
        canvas[:dh, :dw] = resized

        # 绘制高亮
        if self.highlight_mask is not None:
            hm_small = cv2.resize(self.highlight_mask, (dw, dh),
                                   interpolation=cv2.INTER_NEAREST)
            overlay = canvas[:dh, :dw].copy()
            # 半透明蓝色高亮
            blue = np.zeros_like(overlay)
            blue[:, :, 0] = 180
            overlay[hm_small > 127] = cv2.addWeighted(
                overlay[hm_small > 127], 0.5,
                blue[hm_small > 127], 0.5, 0
            )
            # 边界线
            contours, _ = cv2.findContours(
                hm_small, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            cv2.drawContours(overlay, contours, -1, (255, 80, 80), 2)
            canvas[:dh, :dw] = overlay

        FONT = cv2.FONT_HERSHEY_SIMPLEX

        # 提示
        n_total = len(self.masks) if self.masks else 0
        n_sel = len(self.selected_indices)
        cv2.putText(canvas, f"区域总数: {n_total} | 已选中: {n_sel}",
                    (10, 25), FONT, 0.5, (0, 255, 0), 2)
        cv2.putText(canvas, f"缩放: {self.scale*100:.0f}%",
                    (10, 50), FONT, 0.4, (255, 255, 0), 1)

        hint = "左键=选中 | 右键=追加 | WASD=平移 | +/-=缩放 | Enter=保存 | Q=退出"
        cv2.putText(canvas, hint, (10, 72), FONT, 0.4, (200, 200, 200), 1)

        # 已保存列表
        y0 = 95
        cv2.putText(canvas, f"已保存 ({len(self.crops)}):", (10, y0),
                    FONT, 0.4, (200, 200, 200), 1)
        for i, (name, img, rect) in enumerate(self.crops[:12]):
            yi = y0 + 18 + i * 18
            cv2.putText(canvas, f"  {i+1}. {name} ({rect[2]}x{rect[3]})",
                        (10, yi), FONT, 0.35, (200, 200, 200), 1)

        return canvas

    # ----------------------------------------------------------
    # 鼠标回调
    # ----------------------------------------------------------
    def on_mouse(self, event, sx, sy, flags, param):
        ix, iy = self.screen_to_image(sx, sy)

        # 左键：选中
        if event == cv2.EVENT_LBUTTONDOWN:
            found = self.find_mask_at(ix, iy)
            if found:
                self.selected_indices = found
                self.build_highlight()
                print(f"[选中] {len(found)} 个区域")
            else:
                self.selected_indices = []
                self.highlight_mask = None
                print("[!] 该位置没有检测到物体区域")

        # 右键：追加选中
        elif event == cv2.EVENT_RBUTTONDOWN:
            found = self.find_mask_at(ix, iy)
            if found:
                for f in found:
                    if f not in self.selected_indices:
                        self.selected_indices.append(f)
                self.build_highlight()
                print(f"[追加] 共选中 {len(self.selected_indices)} 个区域")


# ============================================================
# 主程序
# ============================================================
def _get_name():
    import tkinter as tk
    from tkinter import simpledialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    name = simpledialog.askstring("保存物体", "输入物体名称:", parent=root)
    root.destroy()
    return name.strip() if name else None


def main():
    parser = argparse.ArgumentParser(description="DeadMaze 地图切割 (FastSAM)")
    parser.add_argument("image", nargs="?", default="map_output.jpg",
                        help="拼接好的地图图片")
    args = parser.parse_args()

    if not os.path.exists(args.image):
        print(f"[错误] 图片不存在: {args.image}")
        sys.exit(1)

    cropper = MapCropperSAM(args.image)
    print(f"  原图: {cropper.w}x{cropper.h}")
    print(f"  区域: {len(cropper.masks) if cropper.masks else 0} 个")
    print("=" * 55)
    print("  左键点击  - 选中物体")
    print("  右键点击  - 追加到选区")
    print("  Enter    - 命名并保存为 PNG (带透明通道)")
    print("  Esc      - 清除选区")
    print("  WASD     - 平移 | +/- 缩放")
    print("  S        - 查看已保存")
    print("  Q        - 退出")
    print("=" * 55)

    cv2.namedWindow("地图物体切割 (FastSAM)", cv2.WINDOW_NORMAL)
    cv2.setMouseCallback("地图物体切割 (FastSAM)", cropper.on_mouse)

    while True:
        canvas = cropper.render()
        cv2.imshow("地图物体切割 (FastSAM)", canvas)

        key = cv2.waitKey(1) & 0xFF
        pan_speed = 30  # 平移速度（像素/帧）

        if key == ord('q') or key == ord('Q'):
            break

        # 缩放
        elif key == ord('+') or key == ord('='):
            cropper.scale = min(3.0, cropper.scale * 1.15)
        elif key == ord('-') or key == ord('_'):
            cropper.scale = max(0.08, cropper.scale / 1.15)

        # 平移 WASD
        elif key == ord('w') or key == ord('W'):
            cropper.offset_y += pan_speed
        elif key == ord('s') or key == ord('S'):
            cropper.offset_y -= pan_speed
        elif key == ord('a') or key == ord('A'):
            cropper.offset_x += pan_speed
        elif key == ord('d') or key == ord('D'):
            cropper.offset_x -= pan_speed

        elif key == 13:  # Enter
            name = _get_name()
            if name:
                cropper.save_selected(name)
        elif key == 27:  # Esc
            cropper.selected_indices = []
            cropper.highlight_mask = None
            print("[清除] 选区已清除")

    cv2.destroyAllWindows()
    print(f"退出。已保存 {len(cropper.crops)} 个物体到 {cropper.output_dir}/")


if __name__ == "__main__":
    main()
