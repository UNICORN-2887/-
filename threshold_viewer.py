"""
DeadMaze - 二值图阈值可视化工具
拖动滑块实时调整阈值，观察物体与背景的分离效果

操作:
  阈值滑块  - 调整二值化阈值 (0~255)
  模式滑块  - 切换阈值类型
  S        - 保存当前二值图
  Q        - 退出
"""

import os
import sys
import argparse

import cv2
import numpy as np


# 阈值模式
MODE_BINARY = 0         # cv2.THRESH_BINARY
MODE_BINARY_INV = 1     # cv2.THRESH_BINARY_INV
MODE_TRUNC = 2          # cv2.THRESH_TRUNC
MODE_TOZERO = 3         # cv2.THRESH_TOZERO
MODE_TOZERO_INV = 4     # cv2.THRESH_TOZERO_INV
MODE_ADAPTIVE_MEAN = 5  # 自适应均值
MODE_ADAPTIVE_GAUSS = 6 # 自适应高斯
MODE_OTSU = 7           # 大津法（自动）
MODE_CANNY = 8          # Canny 边缘检测

MODE_NAMES = {
    MODE_BINARY: "THRESH_BINARY",
    MODE_BINARY_INV: "THRESH_BINARY_INV",
    MODE_TRUNC: "THRESH_TRUNC",
    MODE_TOZERO: "THRESH_TOZERO",
    MODE_TOZERO_INV: "THRESH_TOZERO_INV",
    MODE_ADAPTIVE_MEAN: "自适应均值",
    MODE_ADAPTIVE_GAUSS: "自适应高斯",
    MODE_OTSU: "大津法 OTSU",
    MODE_CANNY: "Canny 边缘",
}


class ThresholdViewer:
    def __init__(self, image_path):
        # 加载原图
        self.original_bgr = cv2.imread(image_path)
        if self.original_bgr is None:
            raise FileNotFoundError(f"无法加载: {image_path}")
        self.original_gray = cv2.cvtColor(self.original_bgr, cv2.COLOR_BGR2GRAY)
        self.h, self.w = self.original_gray.shape[:2]
        self.base_name = os.path.splitext(os.path.basename(image_path))[0]
        self.output_dir = f"threshold_{self.base_name}"

        # 状态
        self.threshold_val = 127
        self.mode = MODE_BINARY
        self.adaptive_block = 11   # 自适应阈值块大小
        self.canny_low = 50        # Canny 低阈值
        self.canny_high = 150      # Canny 高阈值
        self.show_original = True
        self.result = None

    def process(self):
        """根据当前参数生成二值图"""
        gray = self.original_gray
        mode = self.mode
        thresh = self.threshold_val

        if mode == MODE_ADAPTIVE_MEAN:
            block = self.adaptive_block
            if block % 2 == 0:
                block += 1
            self.result = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                cv2.THRESH_BINARY, block, 2
            )
            return "自适应均值", thresh

        elif mode == MODE_ADAPTIVE_GAUSS:
            block = self.adaptive_block
            if block % 2 == 0:
                block += 1
            self.result = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, block, 2
            )
            return "自适应高斯", thresh

        elif mode == MODE_OTSU:
            val, self.result = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )
            return f"OTSU (自动阈值={val})", val

        elif mode == MODE_CANNY:
            self.result = cv2.Canny(gray, self.canny_low, self.canny_high)
            return f"Canny (低={self.canny_low} 高={self.canny_high})", None

        else:
            # 标准阈值模式
            mode_map = {
                MODE_BINARY: cv2.THRESH_BINARY,
                MODE_BINARY_INV: cv2.THRESH_BINARY_INV,
                MODE_TRUNC: cv2.THRESH_TRUNC,
                MODE_TOZERO: cv2.THRESH_TOZERO,
                MODE_TOZERO_INV: cv2.THRESH_TOZERO_INV,
            }
            cv_mode = mode_map.get(mode, cv2.THRESH_BINARY)
            _, self.result = cv2.threshold(gray, thresh, 255, cv_mode)
            return MODE_NAMES[mode], thresh

    def render(self):
        """渲染显示画面"""
        if self.result is None:
            self.process()

        # 缩放以适应屏幕
        max_h = 600
        scale = min(max_h / self.h, 1.0)
        dw = int(self.w * scale)
        dh = int(self.h * scale)

        result_color = cv2.cvtColor(self.result, cv2.COLOR_GRAY2BGR)
        result_disp = cv2.resize(result_color, (dw, dh))

        # 并排显示
        if self.show_original:
            orig_disp = cv2.resize(self.original_bgr, (dw, dh))
            canvas = np.hstack([orig_disp, result_disp])
            # 标签
            FONT = cv2.FONT_HERSHEY_SIMPLEX
            cv2.putText(canvas, "原图", (10, 20), FONT, 0.6, (0, 255, 0), 2)
            cv2.putText(canvas, "二值图", (dw + 10, 20), FONT, 0.6, (0, 255, 0), 2)
        else:
            canvas = result_disp

        FONT = cv2.FONT_HERSHEY_SIMPLEX
        y = dh + 30

        # 信息栏
        mode_name, actual_thresh = self.process()
        cv2.putText(canvas, f"模式: {mode_name}", (10, y),
                    FONT, 0.5, (255, 255, 0), 1)
        if actual_thresh is not None:
            cv2.putText(canvas, f"阈值: {int(actual_thresh)}", (10, y + 25),
                        FONT, 0.5, (255, 255, 0), 1)
        if self.mode in (MODE_ADAPTIVE_MEAN, MODE_ADAPTIVE_GAUSS):
            cv2.putText(canvas, f"块大小: {self.adaptive_block}", (10, y + 50),
                        FONT, 0.5, (255, 255, 0), 1)
        if self.mode == MODE_CANNY:
            cv2.putText(canvas, f"Canny: [{self.canny_low}, {self.canny_high}]",
                        (10, y + 25), FONT, 0.5, (255, 255, 0), 1)

        # 操作提示
        hint = "1-9切换模式 | 阈值/参数滑块 | T=原图对比 | S=保存 | Q=退出"
        cv2.putText(canvas, hint, (10, canvas.shape[0] - 10),
                    FONT, 0.4, (180, 180, 180), 1)

        return canvas

    def save(self):
        if self.result is None:
            return
        os.makedirs(self.output_dir, exist_ok=True)
        fname = f"{MODE_NAMES[self.mode]}_thresh{self.threshold_val}.png"
        path = os.path.join(self.output_dir, fname)
        cv2.imwrite(path, self.result)
        print(f"[保存] {path}")


# ============================================================
# 滑块回调
# ============================================================
def make_viewer(viewer):
    """设置 trackbar 回调"""
    def on_threshold(val):
        viewer.threshold_val = val

    def on_mode(val):
        viewer.mode = val
        # 根据模式显示/隐藏对应滑块
        if val in (MODE_ADAPTIVE_MEAN, MODE_ADAPTIVE_GAUSS):
            cv2.setTrackbarPos("阈值/参数", "二值图阈值", viewer.adaptive_block)
        elif val == MODE_CANNY:
            cv2.setTrackbarPos("阈值/参数", "二值图阈值", viewer.canny_low)
        else:
            cv2.setTrackbarPos("阈值/参数", "二值图阈值", viewer.threshold_val)

    def on_param(val):
        if viewer.mode in (MODE_ADAPTIVE_MEAN, MODE_ADAPTIVE_GAUSS):
            if val % 2 == 0:
                val = max(3, val + 1)
            viewer.adaptive_block = val
        elif viewer.mode == MODE_CANNY:
            viewer.canny_low = val
            viewer.canny_high = val * 3
        else:
            viewer.threshold_val = val

    return on_threshold, on_mode, on_param


def main():
    parser = argparse.ArgumentParser(description="二值图阈值可视化")
    parser.add_argument("image", nargs="?", default="map_output.jpg",
                        help="输入图片路径")
    args = parser.parse_args()

    if not os.path.exists(args.image):
        print(f"[错误] 图片不存在: {args.image}")
        sys.exit(1)

    viewer = ThresholdViewer(args.image)
    print(f"  原图: {viewer.w}x{viewer.h}")

    cv2.namedWindow("二值图阈值", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("二值图阈值", 1200, 700)

    # 创建滑块
    cv2.createTrackbar("阈值/参数", "二值图阈值", 127, 255,
                       lambda v: setattr(viewer, 'threshold_val', v))
    cv2.createTrackbar("模式", "二值图阈值", 0, 8,
                       lambda v: setattr(viewer, 'mode', v))

    # 模式切换说明
    mode_hints = [
        "[1] BINARY  [2] BINARY_INV  [3] TRUNC  [4] TOZERO  [5] TOZERO_INV",
        "[6] 自适应均值  [7] 自适应高斯  [8] OTSU  [9] Canny",
    ]
    for hint in mode_hints:
        print(f"  {hint}")

    print("  [T] 切换原图对比  [S] 保存  [Q] 退出")

    while True:
        # 同步滑块值
        thresh = cv2.getTrackbarPos("阈值/参数", "二值图阈值")
        mode = cv2.getTrackbarPos("模式", "二值图阈值")

        if viewer.mode != mode:
            viewer.mode = mode
            # 模式切换时重置滑块到合适的默认值
            if mode in (MODE_ADAPTIVE_MEAN, MODE_ADAPTIVE_GAUSS):
                cv2.setTrackbarPos("阈值/参数", "二值图阈值", viewer.adaptive_block)
            elif mode == MODE_CANNY:
                cv2.setTrackbarPos("阈值/参数", "二值图阈值", viewer.canny_low)
            # 否则滑块值就是阈值

        if mode in (MODE_ADAPTIVE_MEAN, MODE_ADAPTIVE_GAUSS):
            viewer.adaptive_block = max(3, thresh)
        elif mode == MODE_CANNY:
            viewer.canny_low = thresh
            viewer.canny_high = thresh * 3
        else:
            viewer.threshold_val = thresh

        # 渲染
        canvas = viewer.render()
        cv2.imshow("二值图阈值", canvas)

        key = cv2.waitKey(50) & 0xFF

        if key == ord('q') or key == ord('Q'):
            break
        elif key == ord('t') or key == ord('T'):
            viewer.show_original = not viewer.show_original
        elif key == ord('s') or key == ord('S'):
            viewer.save()

        # 数字键切换模式
        elif ord('1') <= key <= ord('9'):
            mode_idx = key - ord('1')
            viewer.mode = mode_idx
            cv2.setTrackbarPos("模式", "二值图阈值", mode_idx)

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
