"""
DeadMaze - 地图定位工具（彩色匹配）
OBS 画面 → 三通道模板匹配 → 在大地图中定位

RGB 三通道各自匹配后相乘融合，保留全部颜色信息

操作:
  空格    - 执行一次定位
  M      - 切换匹配方法 (三通道融合 / 灰度 / HSV / 边缘)
  Q      - 退出
"""

import os
import sys
import time
import argparse

import cv2
import numpy as np


# ============================================================
# 匹配引擎
# ============================================================
def match_rgb_multichannel(map_img, query):
    """
    RGB 三通道独立匹配 + 融合
    每个通道做 TM_CCOEFF_NORMED，结果相乘（交集效应）
    """
    results = []
    t0 = time.time()
    for c in range(3):
        r = cv2.matchTemplate(
            map_img[:, :, c], query[:, :, c], cv2.TM_CCOEFF_NORMED
        )
        results.append(r)

    # 三通道结果相乘 → 只有三个通道都匹配好的位置才高分
    fused = results[0] * results[1] * results[2]
    # 归一化到 0~1
    fused = (fused - fused.min()) / (fused.max() - fused.min() + 1e-8)

    _, max_val, _, max_loc = cv2.minMaxLoc(fused)
    elapsed = (time.time() - t0) * 1000
    return max_loc, max_val, elapsed, "RGB三通道融合"


def match_rgb_grayscale(map_img, query):
    """灰度匹配（保留亮度结构）"""
    t0 = time.time()
    map_gray = cv2.cvtColor(map_img, cv2.COLOR_BGR2GRAY)
    query_gray = cv2.cvtColor(query, cv2.COLOR_BGR2GRAY)
    result = cv2.matchTemplate(map_gray, query_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    elapsed = (time.time() - t0) * 1000
    return max_loc, max_val, elapsed, "灰度"


def match_hsv_hue(map_img, query):
    """HSV 空间 Hue 通道匹配（对光照不敏感）"""
    t0 = time.time()
    map_hsv = cv2.cvtColor(map_img, cv2.COLOR_BGR2HSV)
    query_hsv = cv2.cvtColor(query, cv2.COLOR_BGR2HSV)
    result = cv2.matchTemplate(
        map_hsv[:, :, 0], query_hsv[:, :, 0], cv2.TM_CCOEFF_NORMED
    )
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    elapsed = (time.time() - t0) * 1000
    return max_loc, max_val, elapsed, "HSV-Hue"


def match_edge_combined(map_img, query):
    """Canny 边缘 + 灰度混合匹配"""
    t0 = time.time()

    def edges(img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        e = cv2.Canny(gray, 50, 150)
        return e.astype(np.float32)

    map_edge = edges(map_img)
    query_edge = edges(query)

    # 边缘匹配
    r_edge = cv2.matchTemplate(map_edge, query_edge, cv2.TM_CCOEFF_NORMED)

    # 灰度匹配
    map_gray = cv2.cvtColor(map_img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    query_gray = cv2.cvtColor(query, cv2.COLOR_BGR2GRAY).astype(np.float32)
    r_gray = cv2.matchTemplate(map_gray, query_gray, cv2.TM_CCOEFF_NORMED)

    # 融合
    fused = r_edge * 0.6 + r_gray * 0.4
    _, max_val, _, max_loc = cv2.minMaxLoc(fused)
    elapsed = (time.time() - t0) * 1000
    return max_loc, max_val, elapsed, "边缘+灰度"


METHODS = [
    ("RGB三通道融合", match_rgb_multichannel),
    ("灰度", match_rgb_grayscale),
    ("HSV-Hue", match_hsv_hue),
    ("边缘+灰度", match_edge_combined),
]


# ============================================================
# 定位器
# ============================================================
class ColorLocalizer:
    def __init__(self, map_path, camera_id=1):
        self.map_full = cv2.imread(map_path)
        if self.map_full is None:
            raise FileNotFoundError(f"地图不存在: {map_path}")
        self.map_h, self.map_w = self.map_full.shape[:2]
        self.map_gray = cv2.cvtColor(self.map_full, cv2.COLOR_BGR2GRAY)
        print(f"[地图] {self.map_w}x{self.map_h}")

        self.cap = cv2.VideoCapture(camera_id)
        if not self.cap.isOpened():
            raise RuntimeError(f"无法打开摄像头 {camera_id}")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.fw = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.fh = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[摄像头] {self.fw}x{self.fh}")

        self.method_idx = 0  # 默认 RGB 三通道融合
        self.match_result = None

    def localize(self):
        ret, frame = self.cap.read()
        if not ret:
            return None

        name, func = METHODS[self.method_idx]

        # 缩放帧（如果大于地图）
        fh, fw = frame.shape[:2]
        scale = min(self.map_w / fw, self.map_h / fh, 0.6)
        if scale < 1.0:
            frame_small = cv2.resize(frame, (int(fw * scale), int(fh * scale)))
        else:
            frame_small = frame

        max_loc, max_val, elapsed, detail = func(self.map_full, frame_small)
        self.match_result = (max_loc, max_val, elapsed, detail, frame_small)
        print(f"[匹配] {detail} | 置信度={max_val:.3f} | {elapsed:.0f}ms")
        return self.match_result

    def render(self):
        ret, frame = self.cap.read()
        if not ret:
            return np.zeros((400, 600, 3), dtype=np.uint8)

        FONT = cv2.FONT_HERSHEY_SIMPLEX
        MAP_MAX = 750

        # 缩小显示
        fh, fw = frame.shape[:2]
        s = 220 / fh
        frame_s = cv2.resize(frame, (int(fw * s), 220))

        # 地图 + 标记
        mh, mw = self.map_full.shape[:2]
        map_scale = min(MAP_MAX / mw, MAP_MAX / mh, 1.0)
        md_w, md_h = int(mw * map_scale), int(mh * map_scale)
        map_disp = cv2.resize(self.map_full, (md_w, md_h))

        method_name, _ = METHODS[self.method_idx]

        if self.match_result:
            max_loc, max_val, elapsed, detail, query = self.match_result
            qh, qw = query.shape[:2]

            # 匹配区域在显示地图上的坐标
            dx = int(max_loc[0] * map_scale)
            dy = int(max_loc[1] * map_scale)
            dw = int(qw * map_scale)
            dh = int(qh * map_scale)
            cx = dx + dw // 2
            cy = dy + dh // 2

            # 绿色匹配框
            cv2.rectangle(map_disp, (dx, dy), (dx + dw, dy + dh),
                          (0, 255, 0), 2)

            # 红色箭头
            arrow_start = (cx, min(md_h - 10, dy + dh + 50))
            cv2.arrowedLine(map_disp, arrow_start, (cx, cy),
                            (0, 0, 255), 3, cv2.LINE_AA, tipLength=0.3)

            # 红色圆点
            cv2.circle(map_disp, (cx, cy), 8, (0, 0, 255), -1)
            cv2.circle(map_disp, (cx, cy), 11, (255, 255, 255), 2)

            # 顶部信息
            info = (f"LOC: ({max_loc[0]}, {max_loc[1]}) | "
                    f"{detail} | conf={max_val:.3f}")
            cv2.putText(map_disp, info, (5, 18), FONT, 0.45,
                        (0, 255, 255), 1)

        else:
            cv2.putText(map_disp, "按空格定位", (10, 25),
                        FONT, 0.6, (0, 255, 0), 2)

        cv2.putText(map_disp, method_name, (md_w - 180, md_h - 8),
                    FONT, 0.45, (255, 255, 255), 1)

        # 拼接
        target_w = max(frame_s.shape[1], md_w)
        parts = [frame_s, map_disp]
        padded = []
        for p in parts:
            if p.shape[1] < target_w:
                pad = np.zeros((p.shape[0], target_w - p.shape[1], 3),
                               dtype=np.uint8)
                p = np.hstack([p, pad])
            padded.append(p)

        canvas = np.vstack(padded)

        # 控制栏
        bottom = np.zeros((40, canvas.shape[1], 3), dtype=np.uint8)
        cv2.putText(bottom, "空格=定位 | M=切换方法 | Q=退出",
                    (10, 16), FONT, 0.45, (180, 180, 180), 1)
        methods_str = " | ".join(
            f"[{'*' if i==self.method_idx else ' '}]{n}"
            for i, (n, _) in enumerate(METHODS)
        )
        cv2.putText(bottom, methods_str, (10, 35), FONT, 0.35,
                    (0, 255, 255), 1)

        canvas = np.vstack([canvas, bottom])
        return canvas


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="DeadMaze 地图定位 (彩色)")
    parser.add_argument("map", nargs="?", default="map_output.jpg")
    parser.add_argument("-c", "--camera", type=int, default=1)
    args = parser.parse_args()

    if not os.path.exists(args.map):
        print(f"[错误] 地图不存在: {args.map}")
        sys.exit(1)

    loc = ColorLocalizer(args.map, args.camera)

    print("\n匹配方法 (M键切换):")
    for i, (name, _) in enumerate(METHODS):
        mark = " ← 默认" if i == 0 else ""
        print(f"  [{i}] {name}{mark}")
    print("\n  空格=定位 | M=切换方法 | Q=退出\n")

    cv2.namedWindow("地图定位 (彩色)", cv2.WINDOW_NORMAL)
    loc.localize()

    while True:
        canvas = loc.render()
        cv2.imshow("地图定位 (彩色)", canvas)

        key = cv2.waitKey(30) & 0xFF

        if key == ord('q') or key == ord('Q'):
            break
        elif key == ord(' '):
            loc.localize()
        elif key == ord('m') or key == ord('M'):
            loc.method_idx = (loc.method_idx + 1) % len(METHODS)
            loc.localize()

    loc.cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
