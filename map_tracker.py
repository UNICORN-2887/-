"""
DeadMaze - 实时地图追踪器 (ORB 特征匹配)
用 ORB 特征匹配跟踪帧间位移——与 map_stitcher 同技术栈
只跟踪静态场景特征点（墙角/边缘/物体），不受僵尸移动影响

操作:
  鼠标左键点击地图 = 设定初始位置
  空格 = 追踪 | 滚轮 = 缩放地图
  R = 重置 | Q = 退出
"""

import os
import sys
import time
import argparse

import cv2
import numpy as np


# ============================================================
class Tracker:
    def __init__(self, map_path, camera_id=1):
        self.map_full = cv2.imread(map_path)
        if self.map_full is None:
            raise FileNotFoundError(f"地图: {map_path}")
        self.mh, self.mw = self.map_full.shape[:2]
        print(f"[地图] {self.mw}x{self.mh}")

        self.cap = cv2.VideoCapture(camera_id, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            raise RuntimeError(f"摄像头 {camera_id}")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.fw = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.fh = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[摄像头] {self.fw}x{self.fh}")

        # ORB
        self.orb = cv2.ORB_create(nfeatures=2000)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

        self.last_position = None    # (cx, cy) L0 坐标
        self.prev_frame = None       # 上一帧追踪时的画面
        self.match_result = None
        self.total_matches = 0
        self.trail = []
        self.need_click = True
        self.auto_mode = False
        self.auto_interval = 0.2  # 每秒 5 次
        self.last_auto_time = 0

        self.map_scale = 0.06
        self.map_offset_x = 0
        self.map_offset_y = 0
        self._display_scale = 1.0

    # ----------------------------------------------------------
    def _get_frame(self, scale=0.5):
        ret, frame = self.cap.read()
        if not ret:
            return None
        if scale < 1.0:
            h, w = frame.shape[:2]
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
        return frame

    # ----------------------------------------------------------
    def _orb_displacement(self, prev_frame, curr_frame):
        """ORB 匹配 → 两帧间位移 (dx, dy, inlier_ratio)"""
        kp1, des1 = self.orb.detectAndCompute(prev_frame, None)
        kp2, des2 = self.orb.detectAndCompute(curr_frame, None)

        n_feat = len(kp2) if kp2 else 0

        if des1 is None or des2 is None or len(des1) < 10 or len(des2) < 10:
            return 0, 0, 0, n_feat

        matches = self.matcher.match(des1, des2)
        if len(matches) < 8:
            return 0, 0, 0, n_feat

        matches = sorted(matches, key=lambda m: m.distance)[:60]
        dxs, dys = [], []
        for m in matches:
            p1 = kp1[m.queryIdx].pt
            p2 = kp2[m.trainIdx].pt
            dxs.append(p2[0] - p1[0])
            dys.append(p2[1] - p1[1])

        dx = np.median(dxs)
        dy = np.median(dys)
        inliers = sum(
            1 for ddx, ddy in zip(dxs, dys)
            if abs(ddx - dx) < 6 and abs(ddy - dy) < 6
        )
        conf = inliers / len(dxs)
        return dx, dy, conf, n_feat

    # ----------------------------------------------------------
    def _orb_vs_map(self, frame, cx, cy, window=800):
        """ORB 在 map ROI 中匹配当前帧 → 绝对位置 (fx, fy, conf)"""
        fh, fw = frame.shape[:2]
        q_scale = fw / self.fw  # frame 相对于原始摄像头的缩放比

        # 在地图上取 ROI（L0 坐标，按缩放比调整）
        r = window
        x1 = max(0, int(cx - r))
        y1 = max(0, int(cy - r))
        x2 = min(self.mw, int(cx + r))
        y2 = min(self.mh, int(cy + r))

        if x2 - x1 < 100 or y2 - y1 < 100:
            return cx, cy, 0

        map_roi = self.map_full[y1:y2, x1:x2]
        # 把 map ROI 缩放到与 frame 相同尺度
        map_scaled = cv2.resize(map_roi,
                                (int((x2 - x1) * q_scale),
                                 int((y2 - y1) * q_scale)),
                                interpolation=cv2.INTER_AREA)

        t0 = time.time()
        kp_m, des_m = self.orb.detectAndCompute(map_scaled, None)
        kp_f, des_f = self.orb.detectAndCompute(frame, None)

        if (des_m is None or des_f is None or
                len(des_m) < 10 or len(des_f) < 10):
            return cx, cy, 0, (time.time() - t0) * 1000

        matches = self.matcher.match(des_f, des_m)
        if len(matches) < 8:
            return cx, cy, 0, (time.time() - t0) * 1000

        matches = sorted(matches, key=lambda m: m.distance)[:60]
        dxs, dys = [], []
        for m in matches:
            pf = kp_f[m.queryIdx].pt
            pm = kp_m[m.trainIdx].pt
            dxs.append(pm[0] - pf[0])
            dys.append(pm[1] - pf[1])

        dx = np.median(dxs)
        dy = np.median(dys)
        inliers = sum(
            1 for ddx, ddy in zip(dxs, dys)
            if abs(ddx - dx) < 8 and abs(ddy - dy) < 8
        )
        conf = inliers / len(dxs)
        ms = (time.time() - t0) * 1000

        # 映射回 L0 坐标（中心 = 窗口偏移 + 匹配位移/缩放 + 半帧宽）
        fx = x1 + int(dx / q_scale) + self.fw // 2
        fy = y1 + int(dy / q_scale) + self.fh // 2

        return fx, fy, conf, ms

    # ----------------------------------------------------------
    def track(self):
        frame = self._get_frame(scale=0.5)
        if frame is None:
            return None

        if self.prev_frame is not None:
            # 光流式 ORB: 帧间位移 → 预测位置 → map ORB 验证
            dx, dy, flow_conf, n_feat = self._orb_displacement(
                self.prev_frame, frame
            )
            pred_cx = self.last_position[0] + dx / 0.5  # 恢复到 L0
            pred_cy = self.last_position[1] + dy / 0.5

            # map 验证
            fx, fy, map_conf, ms = self._orb_vs_map(
                frame, pred_cx, pred_cy, window=800
            )

            if map_conf > 0.30:
                self.last_position = (fx, fy)
                self.match_result = (fx, fy, map_conf, ms, frame)
                self.trail.append((fx, fy))
                if len(self.trail) > 100:
                    self.trail = self.trail[-100:]
                self.total_matches += 1
                d = np.hypot(fx - pred_cx, fy - pred_cy)
                print(f"[#{self.total_matches}] ({fx},{fy}) "
                      f"d={d:.0f} map_conf={map_conf:.3f} "
                      f"flow({dx:.1f},{dy:.1f}) feat={n_feat} {ms:.0f}ms")
            else:
                # map 匹配失败，信帧间 ORB
                self.last_position = (pred_cx, pred_cy)
                print(f"[flow] ({pred_cx:.0f},{pred_cy:.0f}) "
                      f"ORB({dx:.1f},{dy:.1f}) "
                      f"map_conf={map_conf:.3f}(跳过) feat={n_feat}")
        else:
            # 首次 track：在当前位置做 map 匹配验证
            fx, fy, map_conf, ms = self._orb_vs_map(
                frame, self.last_position[0], self.last_position[1],
                window=800
            )
            if map_conf > 0.20:
                self.last_position = (fx, fy)
            self.match_result = (self.last_position[0],
                                 self.last_position[1], map_conf, ms, frame)
            self.trail.append(self.last_position)
            self.total_matches += 1
            print(f"[#{self.total_matches}] ({self.last_position[0]},"
                  f"{self.last_position[1]}) conf={map_conf:.3f} {ms:.0f}ms")

        self.prev_frame = frame.copy()
        return self.match_result

    # ----------------------------------------------------------
    def handle_click(self, click_x, click_y):
        cx = int((click_x - self.map_offset_x) / self.map_scale)
        cy = int((click_y - self.map_offset_y) / self.map_scale)
        cx = max(0, min(cx, self.mw - 1))
        cy = max(0, min(cy, self.mh - 1))
        print(f"[点击] → ({cx},{cy})")
        print("[ORB匹配]...", end=" ", flush=True)

        frame = self._get_frame(scale=0.5)
        if frame is None:
            print("摄像头失败")
            return

        fx, fy, map_conf, ms = self._orb_vs_map(frame, cx, cy, window=1000)
        if map_conf < 0.15:
            print(f"置信度 {map_conf:.3f} 太低，换特征明显的点重试")
            return

        self.match_result = (fx, fy, map_conf, ms, frame)
        self.last_position = (fx, fy)
        self.prev_frame = frame.copy()
        self.trail = [(fx, fy)]
        self.total_matches = 1
        self.need_click = False
        self.auto_mode = True  # 点击定位后自动开始追踪
        print(f"({fx},{fy}) conf={map_conf:.3f} {ms:.0f}ms [自动追踪已开启]")

        self.map_offset_x = int(400 - fx * self.map_scale)
        self.map_offset_y = int(200 - fy * self.map_scale)

    def reset(self):
        self.last_position = None
        self.prev_frame = None
        self.match_result = None
        self.trail = []
        self.need_click = True
        print("[重置]")

    # ----------------------------------------------------------
    def render(self):
        ret, frame = self.cap.read()
        if not ret:
            return np.zeros((400, 600, 3), dtype=np.uint8)

        FONT = cv2.FONT_HERSHEY_SIMPLEX
        fh, fw = frame.shape[:2]
        cam_s = 180 / fh
        cam_disp = cv2.resize(frame, (int(fw * cam_s), 180))

        md_w = int(self.mw * self.map_scale)
        md_h = int(self.mh * self.map_scale)
        map_disp = cv2.resize(self.map_full, (md_w, md_h))
        self._display_scale = self.map_scale

        if self.need_click:
            cv2.putText(map_disp, "点击地图设定位置",
                        (10, md_h - 10), FONT, 0.55, (0, 255, 255), 2)

        if len(self.trail) >= 2:
            for i in range(1, len(self.trail)):
                p1 = (int(self.trail[i-1][0]*self.map_scale),
                      int(self.trail[i-1][1]*self.map_scale))
                p2 = (int(self.trail[i][0]*self.map_scale),
                      int(self.trail[i][1]*self.map_scale))
                a = (i + 1) / len(self.trail)
                color = (int(50+150*a), int(50+200*a), 50)
                cv2.line(map_disp, p1, p2, color, 2)
            cv2.circle(map_disp, p2, 9, (0, 0, 255), -1)
            cv2.circle(map_disp, p2, 11, (255, 255, 255), 2)

        if self.match_result:
            fx, fy, conf, total_ms, query = self.match_result
            qh, qw = query.shape[:2]
            qw_l0 = int(qw / 0.5)
            qh_l0 = int(qh / 0.5)
            dx = int((fx - qw_l0//2) * self.map_scale)
            dy = int((fy - qh_l0//2) * self.map_scale)
            dw = int(qw_l0 * self.map_scale)
            dh = int(qh_l0 * self.map_scale)

            cv2.rectangle(map_disp, (dx, dy), (dx+dw, dy+dh), (0, 255, 0), 2)
            cv2.arrowedLine(map_disp, (dx+dw//2, dy+dh+35),
                            (dx+dw//2, dy+3), (0, 0, 255), 3,
                            cv2.LINE_AA, tipLength=0.2)

            info = (f"({fx},{fy}) conf={conf:.3f} #{self.total_matches}")
            cv2.putText(map_disp, info, (5, 15), FONT, 0.4, (0, 255, 255), 1)

        tw = max(cam_disp.shape[1], md_w)
        if cam_disp.shape[1] < tw:
            cam_disp = np.hstack([cam_disp,
                         np.zeros((180, tw-cam_disp.shape[1], 3), dtype=np.uint8)])
        if md_w < tw:
            map_disp = np.hstack([map_disp,
                         np.zeros((md_h, tw-md_w, 3), dtype=np.uint8)])
        canvas = np.vstack([cam_disp, map_disp])

        bottom = np.zeros((40, tw, 3), dtype=np.uint8)
        scale_pct = int(self.map_scale * 100)
        if self.need_click:
            hint = f"点击地图设定位置 | 滚轮缩放({scale_pct}%) | Q=退出"
            color = (0, 255, 255)
        else:
            auto = "A=自动[ON]" if self.auto_mode else "A=自动[OFF]"
            hint = (f"空格=追踪 | {auto} | 滚轮({scale_pct}%) | "
                    f"R=重置 | Q=退出")
            color = (180, 180, 180)
        cv2.putText(bottom, hint, (10, 24), FONT, 0.4, color, 1)
        canvas = np.vstack([canvas, bottom])
        return canvas


# ============================================================
def make_mouse_cb(tracker):
    def cb(event, x, y, flags, param):
        map_y = y - 180
        if event == cv2.EVENT_LBUTTONDOWN and map_y >= 0 and tracker.need_click:
            tracker.handle_click(x, map_y)
        elif (event == cv2.EVENT_MOUSEWHEEL or event == 10) and map_y >= 0:
            old = tracker.map_scale
            tracker.map_scale = (min(0.5, tracker.map_scale * 1.2)
                                 if flags > 0
                                 else max(0.02, tracker.map_scale / 1.2))
            if old != tracker.map_scale:
                r = tracker.map_scale / old
                tracker.map_offset_x = int(x - r*(x - tracker.map_offset_x))
                tracker.map_offset_y = int(map_y - r*(map_y - tracker.map_offset_y))
    return cb


# ============================================================
def main():
    p = argparse.ArgumentParser()
    p.add_argument("map", nargs="?", default="map_output.jpg")
    p.add_argument("-c", "--camera", type=int, default=1)
    args = p.parse_args()

    if not os.path.exists(args.map):
        print(f"[错误]: {args.map}")
        sys.exit(1)

    tracker = Tracker(args.map, args.camera)
    print("\n=== ORB 特征追踪 ===")
    print("走到标志物旁 → 放大地图 → 点击对应位置\n")

    cv2.namedWindow("地图追踪", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty("地图追踪", cv2.WND_PROP_TOPMOST, 1)
    cv2.setMouseCallback("地图追踪", make_mouse_cb(tracker))

    while True:
        canvas = tracker.render()
        cv2.imshow("地图追踪", canvas)
        key = cv2.waitKey(30) & 0xFF

        if key == ord('q') or key == ord('Q'):
            break
        elif key == ord(' ') and not tracker.need_click:
            tracker.track()
        elif key == ord('a') or key == ord('A'):
            tracker.auto_mode = not tracker.auto_mode
            state = "ON" if tracker.auto_mode else "OFF"
            print(f"[自动追踪] {state}")
        elif key == ord('r') or key == ord('R'):
            tracker.reset()
            tracker.auto_mode = False

        # 自动追踪
        if (tracker.auto_mode and not tracker.need_click and
                time.time() - tracker.last_auto_time > tracker.auto_interval):
            tracker.track()
            tracker.last_auto_time = time.time()

    tracker.cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
