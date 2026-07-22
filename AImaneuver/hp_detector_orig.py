"""
DeadMaze - HP 血条颜色检测器
从 OBS 画面检测绿色/黑色比例 → 估算血量百分比

左侧: OBS 画面 + 绿框 = HP检测区
右侧: ROI 放大 + 绿色占比

操作:
  方向键    - 移动 ROI (±1px)
  Shift+方向 - 调整 ROI 大小 (±1px)
  S         - 保存 ROI 坐标
  Q         - 退出
"""

import cv2
import numpy as np
import time
import json
import os

# ========== 配置 ==========
from camera_finder import find_obs_camera
OBS_CAM_ID = find_obs_camera()
HP_ROI = [80, 30, 200, 20]  # [x, y, w, h]
HP_INTERVAL = 0.5           # 检测间隔(秒)

# 绿色判定 (HSV)
GREEN_LOW = np.array([35, 40, 40])
GREEN_HIGH = np.array([85, 255, 255])

MAP_W = 600
SIDEBAR_W = 500
ROI_SCALE_H = 12  # ROI 纵向放大倍数
WIN_W = MAP_W + SIDEBAR_W
WIN_H = 500

SAVE_FILE = os.path.join(os.path.dirname(__file__), "hp_detector_roi.json")

# ========== 加载保存的 ROI ==========
if os.path.exists(SAVE_FILE):
    with open(SAVE_FILE, 'r') as f:
        HP_ROI = json.load(f)
    print(f"加载ROI: {SAVE_FILE}")

# ========== OBS ==========
cap = cv2.VideoCapture(OBS_CAM_ID)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
ret, test = cap.read()
if not ret: print("OBS未开!"); exit()
gw, gh = test.shape[1], test.shape[0]
print(f"OBS: {gw}x{gh}")

# ========== 窗口 ==========
cv2.namedWindow("HP 检测", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("HP 检测", cv2.WND_PROP_TOPMOST, 1)
cv2.resizeWindow("HP 检测", WIN_W, WIN_H)
FONT = cv2.FONT_HERSHEY_SIMPLEX

last_t = 0
frame = None
hp_pct = 0
green_mask = None
dragging = False
drag_start = (0, 0)
roi_start = None

def on_mouse(event, sx, sy, flags, param):
    global dragging, drag_start, roi_start
    ms = MAP_W / gw
    rx, ry, rw, rh = HP_ROI
    # ROI 在地图上的显示位置
    mx, my = int(rx*ms), int(ry*ms)
    mw, mh = int(rw*ms), int(rh*ms)
    if event == cv2.EVENT_LBUTTONDOWN and mx <= sx <= mx+mw and my <= sy <= my+mh:
        dragging = True
        drag_start = (sx, sy)
        roi_start = (rx, ry)
    elif event == cv2.EVENT_LBUTTONUP:
        dragging = False
    elif event == cv2.EVENT_MOUSEMOVE and dragging:
        dx = int((sx - drag_start[0]) / ms)
        dy = int((sy - drag_start[1]) / ms)
        HP_ROI[0] = roi_start[0] + dx
        HP_ROI[1] = roi_start[1] + dy

cv2.setMouseCallback("HP 检测", on_mouse)

print("拖拽绿框定位 | IJKL=微调 | Shift+IJKL=调大小 | S=保存 | Q=退出")

while True:
    ret, obs = cap.read()
    if not ret: time.sleep(0.01); continue

    now = time.time()
    if now - last_t > HP_INTERVAL:
        frame = obs.copy()
        last_t = now
        rx, ry, rw, rh = [max(1, v) for v in HP_ROI]
        rx = min(rx, gw-2); ry = min(ry, gh-2)
        rw = min(rw, gw-rx); rh = min(rh, gh-ry)
        HP_ROI = [rx, ry, rw, rh]

        roi = frame[ry:ry+rh, rx:rx+rw]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        green_mask = cv2.inRange(hsv, GREEN_LOW, GREEN_HIGH)
        total = roi.shape[0] * roi.shape[1]
        green_cnt = np.count_nonzero(green_mask)
        hp_pct = green_cnt / total * 100 if total > 0 else 0

    # ===== 渲染 =====
    canvas = np.zeros((WIN_H, WIN_W, 3), dtype=np.uint8)

    # 左侧：OBS截图
    if frame is not None:
        ms = MAP_W / gw; mh = int(gh * ms)
        d = cv2.resize(frame, (MAP_W, mh))
        x = int(rx*ms); y = int(ry*ms); w = int(rw*ms); h = int(rh*ms)
        cv2.rectangle(d, (x, y), (x+w, y+h), (0, 255, 0), 2)
        cv2.putText(d, f"HP:{hp_pct:.0f}%", (x, y-5), FONT, 0.35, (0,255,0), 1)
        canvas[:mh, :MAP_W] = d

    # 右侧：ROI放大 + 绿色标注
    sx = MAP_W + 10; sy = 10
    if frame is not None and hp_pct > 0:
        roi = frame[ry:ry+rh, rx:rx+rw]
        big = cv2.resize(roi, (rw * 2, rh * ROI_SCALE_H),
                         interpolation=cv2.INTER_NEAREST)
        if green_mask is not None:
            gm = cv2.resize(green_mask, (rw * 2, rh * ROI_SCALE_H),
                            interpolation=cv2.INTER_NEAREST)
            big[gm > 0] = [0, 255, 0]

        bh = big.shape[0]
        canvas[sy:sy+bh, sx:sx+big.shape[1]] = big
        sy += bh + 5

    # HP 数值 + 坐标信息
    cv2.putText(canvas, f"HP: {hp_pct:.1f}%", (sx, sy+18), FONT, 0.6, (0, 255, 0), 2)
    sy += 25
    cv2.putText(canvas, f"ROI: ({rx},{ry}) {rw}x{rh}", (sx, sy+15),
                FONT, 0.4, (150, 150, 150), 1)
    sy += 25
    cv2.putText(canvas, "拖拽定位 | IJKL=微调 | Shift+IJKL=大小 | S=保存", (sx, sy+15),
                FONT, 0.35, (150, 150, 150), 1)

    # HP 条可视化
    sy += 30
    bar_w = 200; bar_h = 25
    cv2.rectangle(canvas, (sx, sy), (sx+bar_w, sy+bar_h), (100, 100, 100), 1)
    fill = int(bar_w * hp_pct / 100)
    cv2.rectangle(canvas, (sx, sy), (sx+fill, sy+bar_h), (0, 200, 0), -1)

    cv2.imshow("HP 检测", canvas)
    key = cv2.waitKey(30) & 0xFF
    step = 1
    if key == ord('q'): break

    # IJKL = 移动 ROI, Shift+IJKL = 调大小
    if key == ord('j'): HP_ROI[0] -= step
    elif key == ord('l'): HP_ROI[0] += step
    elif key == ord('i'): HP_ROI[1] -= step
    elif key == ord('k'): HP_ROI[1] += step
    elif key == ord('J'): HP_ROI[2] -= step
    elif key == ord('L'): HP_ROI[2] += step
    elif key == ord('I'): HP_ROI[3] -= step
    elif key == ord('K'): HP_ROI[3] += step

    elif key == ord('s'):
        with open(SAVE_FILE, 'w') as f:
            json.dump(HP_ROI, f)
        print(f"ROI已保存: {HP_ROI}")

cap.release(); cv2.destroyAllWindows()
