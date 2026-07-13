"""
DeadMaze - 地图定位工具
OBS 画面 → TOZERO 预处理 → 在大地图中模板匹配定位

核心: THRESH_TOZERO 暗部压黑、亮部保留，对游戏场景结构提取效果好

操作:
  空格    - 执行一次定位匹配
  , / .   - 增减 TOZERO 阈值 (或左右箭头)
  1-9     - 切换预处理模式
  Q       - 退出
"""

import os
import sys
import time
import argparse

import cv2
import numpy as np


# ============================================================
# 预处理管道
# ============================================================
def prep_gray(img):
    """灰度"""
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def prep_tozero(img, thresh):
    """TOZERO — src > thresh 保留，否则置0（压暗暗部）"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, out = cv2.threshold(gray, thresh, 255, cv2.THRESH_TOZERO)
    return out


def prep_binary(img, thresh):
    """二值化"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, out = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY)
    return out


def prep_canny(img, low=50, high=150):
    """Canny 边缘"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.Canny(gray, low, high)


def prep_gradient(img):
    """Sobel 梯度"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    mag = np.uint8(np.clip(mag, 0, 255))
    _, out = cv2.threshold(mag, 30, 255, cv2.THRESH_BINARY)
    return out


# 管道: (名称, 函数, 是否有阈值参数, 默认阈值)
PIPELINES = [
    ("灰度", prep_gray, False, 0),
    ("Canny边缘", prep_canny, False, 0),
    ("Sobel梯度", prep_gradient, False, 0),
    ("二值化", prep_binary, True, 127),
    ("TOZERO", prep_tozero, True, 50),   # ← 默认 TOZERO T=50
]


# ============================================================
# 定位器
# ============================================================
class MapLocalizer:
    def __init__(self, map_path, camera_id=1):
        # 大地图
        self.map_full = cv2.imread(map_path)
        if self.map_full is None:
            raise FileNotFoundError(f"地图不存在: {map_path}")
        self.map_h, self.map_w = self.map_full.shape[:2]
        print(f"[地图] {self.map_w}x{self.map_h}")

        # 管道状态
        self.pipeline_idx = 4  # 默认 TOZERO
        self.thresh_val = 50   # TOZERO 默认阈值
        self.prepped_map = None
        self._prep_map()

        # 摄像头
        self.cap = cv2.VideoCapture(camera_id)
        if not self.cap.isOpened():
            raise RuntimeError(f"无法打开摄像头 {camera_id}")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.fw = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.fh = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[摄像头] {self.fw}x{self.fh}")

        # 匹配结果
        self.match_result = None

    def _get_pipeline(self):
        return PIPELINES[self.pipeline_idx]

    def _apply_pipeline(self, img):
        """对图像应用当前管道"""
        _, func, has_thresh, default_thresh = self._get_pipeline()
        thresh = self.thresh_val if has_thresh else default_thresh
        if has_thresh:
            return func(img, thresh)
        else:
            return func(img) if 'low' not in func.__code__.co_varnames else func(img)

    def _prep_map(self):
        name, _, _, _ = self._get_pipeline()
        t0 = time.time()
        self.prepped_map = self._apply_pipeline(self.map_full)
        elapsed = (time.time() - t0) * 1000
        has_thresh = self._get_pipeline()[2]
        thresh_info = f" T={self.thresh_val}" if has_thresh else ""
        print(f"[预处理] 地图 → {name}{thresh_info} ({elapsed:.0f}ms)")

    def set_pipeline(self, idx):
        self.pipeline_idx = idx % len(PIPELINES)
        self._prep_map()
        self.match_result = None

    def localize(self):
        ret, frame = self.cap.read()
        if not ret:
            return None

        name, _, has_thresh, _ = self._get_pipeline()
        t0 = time.time()
        prepped = self._apply_pipeline(frame)
        prep_ms = (time.time() - t0) * 1000

        # 如果帧大于地图就缩小
        fh, fw = prepped.shape[:2]
        scale = min(self.map_w / fw, self.map_h / fh, 0.8)
        if scale < 1.0:
            prepped = cv2.resize(prepped, (int(fw * scale), int(fh * scale)))

        # 模板匹配
        t0 = time.time()
        result = cv2.matchTemplate(
            self.prepped_map, prepped, cv2.TM_CCOEFF_NORMED
        )
        match_ms = (time.time() - t0) * 1000

        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        self.match_result = (max_loc, max_val, prep_ms + match_ms, prepped)
        thresh_info = f" T={self.thresh_val}" if has_thresh else ""
        print(f"[匹配] {name}{thresh_info} | "
              f"置信度={max_val:.3f} | 位置={max_loc} | {prep_ms+match_ms:.0f}ms")
        return self.match_result

    def render(self):
        ret, frame = self.cap.read()
        if not ret:
            return np.zeros((300, 600, 3), dtype=np.uint8)

        FONT = cv2.FONT_HERSHEY_SIMPLEX
        ROW_H = 250
        MAP_DISP_MAX = 800

        def fit_h(img, h):
            ih, iw = img.shape[:2]
            if ih == 0:
                return np.zeros((h, 10, 3), dtype=np.uint8)
            s = h / ih
            resized = cv2.resize(img, (int(iw * s), h))
            if len(resized.shape) == 2:
                resized = cv2.cvtColor(resized, cv2.COLOR_GRAY2BGR)
            return resized

        name, _, has_thresh, _ = self._get_pipeline()
        thresh_info = f" T={self.thresh_val}" if has_thresh else ""

        # 原始帧 + 预处理帧
        frame_s = fit_h(frame, ROW_H)
        prepped = self._apply_pipeline(frame)
        prepped_s = fit_h(prepped, ROW_H)

        row1 = np.hstack([frame_s, prepped_s])
        cv2.putText(row1, "摄像头", (5, 20), FONT, 0.5, (0, 255, 0), 2)
        cv2.putText(row1, f"预处理: {name}{thresh_info}",
                    (frame_s.shape[1] + 5, 20), FONT, 0.5, (0, 255, 0), 2)

        # ---- 地图定位视图（全图 + 红色箭头标记） ----
        map_color = cv2.cvtColor(self.prepped_map, cv2.COLOR_GRAY2BGR)
        mh, mw = map_color.shape[:2]
        # 缩放到显示大小
        scale = min(MAP_DISP_MAX / mw, MAP_DISP_MAX / mh, 1.0)
        map_disp = cv2.resize(map_color,
                              (int(mw * scale), int(mh * scale)))
        md_h, md_w = map_disp.shape[:2]

        if self.match_result:
            max_loc, confidence, elapsed_ms, query = self.match_result
            qh, qw = query.shape[:2]

            # 计算在显示坐标系中的位置
            disp_x = int(max_loc[0] * scale)
            disp_y = int(max_loc[1] * scale)
            disp_w = int(qw * scale)
            disp_h = int(qh * scale)
            center_x = disp_x + disp_w // 2
            center_y = disp_y + disp_h // 2

            # 绿色矩形框
            cv2.rectangle(map_disp,
                          (disp_x, disp_y),
                          (disp_x + disp_w, disp_y + disp_h),
                          (0, 255, 0), 2)

            # 红色箭头（从画面底部指向匹配位置）
            arrow_tip = (center_x, center_y)
            arrow_base = (center_x, min(md_h - 10, center_y + 60))
            cv2.arrowedLine(map_disp, arrow_base, arrow_tip,
                            (0, 0, 255), 3, cv2.LINE_AA, tipLength=0.3)

            # 红色圆点标记中心
            cv2.circle(map_disp, (center_x, center_y), 8, (0, 0, 255), -1)
            cv2.circle(map_disp, (center_x, center_y), 10, (255, 255, 255), 2)

            # 位置信息
            cv2.putText(map_disp,
                        f"LOC: ({max_loc[0]}, {max_loc[1]}) "
                        f"conf={confidence:.2f}",
                        (disp_x, max(0, disp_y - 8)),
                        FONT, 0.4, (0, 255, 255), 1)

            info_text = (f"位置: ({max_loc[0]}, {max_loc[1]}) | "
                         f"置信度: {confidence:.3f} | {elapsed_ms:.0f}ms")
        else:
            info_text = "按空格开始定位"

        cv2.putText(map_disp, info_text, (5, md_h - 5),
                    FONT, 0.4, (0, 255, 0), 1)

        # ---- 底部控制栏 ----
        bottom = np.zeros((45, max(row1.shape[1], md_w), 3), dtype=np.uint8)
        cv2.putText(bottom, "空格=定位 | 1-5=切换 | ,/.(增减阈值) | Q=退出",
                    (10, 20), FONT, 0.4, (180, 180, 180), 1)
        modes = " | ".join(
            f"[{i+1}]{'*' if i == self.pipeline_idx else ' '}{n}"
            for i, (n, _, _, _) in enumerate(PIPELINES)
        )
        cv2.putText(bottom, modes, (10, 40), FONT, 0.35,
                    (0, 255, 255) if self.pipeline_idx == 4 else (150, 150, 150), 1)

        # 统一宽度后拼接
        parts = [row1, map_disp, bottom]
        target_w = max(p.shape[1] for p in parts)
        padded = []
        for p in parts:
            if p.shape[1] < target_w:
                pad = np.zeros((p.shape[0], target_w - p.shape[1], 3), dtype=np.uint8)
                p = np.hstack([p, pad])
            padded.append(p)

        return np.vstack(padded)


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="DeadMaze 地图定位")
    parser.add_argument("map", nargs="?", default="map_output.jpg")
    parser.add_argument("-c", "--camera", type=int, default=1)
    args = parser.parse_args()

    if not os.path.exists(args.map):
        print(f"[错误] 地图不存在: {args.map}")
        sys.exit(1)

    localizer = MapLocalizer(args.map, args.camera)

    print("\n管道 (按数字键切换):")
    for i, (name, _, has_thresh, default_thresh) in enumerate(PIPELINES):
        mark = " ← TOZERO 默认" if i == 4 else ""
        thresh_info = f" (T={default_thresh})" if has_thresh else ""
        print(f"  [{i+1}] {name}{thresh_info}{mark}")
    print("\n  空格=定位 | 1-5=切换 | ,=降阈值 .=升阈值 | Q=退出\n")

    cv2.namedWindow("地图定位", cv2.WINDOW_NORMAL)
    localizer.localize()

    while True:
        canvas = localizer.render()
        cv2.imshow("地图定位", canvas)

        key = cv2.waitKey(30) & 0xFF

        if key == ord('q') or key == ord('Q'):
            break

        elif key == ord(' '):
            localizer.localize()

        elif key == ord(',') or key == ord('<'):
            localizer.thresh_val = max(0, localizer.thresh_val - 10)
            localizer._prep_map()
            localizer.localize()

        elif key == ord('.') or key == ord('>'):
            localizer.thresh_val = min(255, localizer.thresh_val + 10)
            localizer._prep_map()
            localizer.localize()

        elif ord('1') <= key <= ord('5'):
            idx = key - ord('1')
            localizer.set_pipeline(idx)
            if PIPELINES[idx][2]:  # has_thresh
                localizer.thresh_val = PIPELINES[idx][3]
            localizer.localize()

    localizer.cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
