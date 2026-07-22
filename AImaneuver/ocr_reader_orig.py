"""
DeadMaze - OCR 状态读取器 (EasyOCR)
左侧: 游戏截图(高清源, 显示缩略)
右侧: ROI 局部放大 + EasyOCR 识别数值

ROI 区域在 OCR_REGIONS 中修改 (游戏窗口像素坐标)
空格=截图, 拖拽框选调整ROI, Q=退出
"""

import cv2
import numpy as np
import time
import json
import os
import easyocr

# ========== OCR 配置 ==========
# (名称, x, y, w, h, 字符白名单)
OCR_REGIONS = [
    ("Exp",      80,  620,  50, 25,  "0123456789xp"),
    ("Hunger",   180,  620,  50, 25,  "0123456789"),
    ("Thirst",   280,  620,  50, 25,  "0123456789"),
    ("Stamina",  380,  620,  50, 25,  "0123456789"),
    ("Threat",   480,  620,  50, 25,  "0123456789xp"),
]
OCR_INTERVAL = 1.0
ROI_SCALE = 5

# 尝试加载保存的 ROI
SAVE_FILE = os.path.join(os.path.dirname(__file__), "ocr_reader_roi.json")
if os.path.exists(SAVE_FILE):
    with open(SAVE_FILE, 'r') as f:
        OCR_REGIONS = json.load(f)
    print(f"加载保存的ROI: {SAVE_FILE}")

# ========== OBS 虚拟摄像头 ==========
from camera_finder import find_obs_camera
OBS_CAM_ID = find_obs_camera()
cap = cv2.VideoCapture(OBS_CAM_ID)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
ret, test = cap.read()
if not ret:
    print(f"OBS 摄像头 {OBS_CAM_ID} 未打开!"); exit()
gw, gh = test.shape[1], test.shape[0]
print(f"OBS: {gw}x{gh}")

# ========== OCR 引擎 ==========
print("EasyOCR...", end=" ", flush=True)
ocr = easyocr.Reader(["en"], gpu=True)
print("OK")

# ========== 窗口 ==========
MAP_W = 600          # 左侧地图宽度
SIDEBAR_W = 350      # 右侧栏宽度
WIN_W = MAP_W + SIDEBAR_W
WIN_H = 600

cv2.namedWindow("OCR 状态", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("OCR 状态", cv2.WND_PROP_TOPMOST, 1)
cv2.resizeWindow("OCR 状态", WIN_W, WIN_H)
FONT = cv2.FONT_HERSHEY_SIMPLEX

last_t = 0
last_cap_time = 0
frame = None
ocr_vals = {r[0]: "?" for r in OCR_REGIONS}
ocr_filtered = dict(ocr_vals)  # 约束后的值
_prev_threat = None
_prev_stamina = None
_exp_max = 0
dragging_roi = -1
drag_offset = (0, 0)


def find_roi_index(sx, sy):
    """屏幕坐标 → ROI 索引, -1=无"""
    for i, (_, rx, ry, rw, rh, *_) in enumerate(OCR_REGIONS):
        x = int(rx * MAP_W / gw)
        y = int(ry * MAP_W / gw)
        w = int(rw * MAP_W / gw)
        h = int(rh * MAP_W / gw)
        if x <= sx <= x + w and y <= sy <= y + h:
            return i
    return -1


def mouse(event, sx, sy, flags, param):
    global dragging_roi, drag_offset
    if event == cv2.EVENT_LBUTTONDOWN:
        dragging_roi = find_roi_index(sx, sy)
        if dragging_roi >= 0:
            drag_offset = (sx, sy)
    elif event == cv2.EVENT_LBUTTONUP:
        dragging_roi = -1
    elif event == cv2.EVENT_MOUSEMOVE and dragging_roi >= 0:
        dx = int((sx - drag_offset[0]) * gw / MAP_W)
        dy = int((sy - drag_offset[1]) * gw / MAP_W)
        old = OCR_REGIONS[dragging_roi]
        OCR_REGIONS[dragging_roi] = (old[0], old[1]+dx, old[2]+dy,
                                      old[3], old[4], old[5])
        drag_offset = (sx, sy)

cv2.setMouseCallback("OCR 状态", mouse)

print("Q=退出 | 拖拽绿框调整ROI | 自动每秒截图+OCR")

while True:
    now = time.time()

    # OBS 取帧 + OCR (每秒)
    ret, obs_frame = cap.read()
    if not ret:
        time.sleep(0.01); continue

    if now - last_t > OCR_INTERVAL:
        frame = obs_frame.copy()
        last_t = now

        for name, rx, ry, rw, rh, allow in OCR_REGIONS:
            roi = frame[ry:ry+rh, rx:rx+rw]
            if roi.size == 0: continue
            big = cv2.resize(roi, (rw*ROI_SCALE, rh*ROI_SCALE),
                             interpolation=cv2.INTER_CUBIC)
            result = ocr.readtext(big, detail=1, allowlist=allow)
            if result:
                ocr_vals[name] = result[0][1]
            else:
                ocr_vals[name] = "?"

        # 约束过滤
        def _clamp_n(name, mx):
            v = ocr_vals.get(name, "?")
            if v.isdigit() and int(v) > mx:
                ocr_vals[name] = v[:2]

        _clamp_n("Hunger", 200)
        _clamp_n("Thirst", 200)
        _clamp_n("Stamina", 200)

        # Exp 有条件递增
        def _to_int(val):
            d = ''.join(c for c in val if c.isdigit())
            return int(d) if d else None

        en = _to_int(ocr_vals.get("Exp", "?"))
        tn = _to_int(ocr_vals.get("Threat", "?"))
        s = ocr_vals.get("Stamina", "?")
        sn = int(s) if s.isdigit() else None

        if en is not None:
            # 判断是否允许重置
            reset = False
            if _prev_threat is not None and tn is not None:
                if abs(tn - _prev_threat) > 20:
                    reset = True
            if _prev_stamina is not None and sn is not None:
                if sn > _prev_stamina + 10:
                    reset = True

            if reset:
                _exp_max = en
            else:
                # 跳变上限: 变化不能超过1000 (除非Threat=0)
                if _exp_max > 0 and tn is not None and tn > 0:
                    if en > _exp_max + 1000:
                        en = _exp_max  # 拒绝跳变
                _exp_max = max(_exp_max, en)
            ocr_vals["Exp"] = f"{_exp_max}xp"

        # Threat 约束: 只能 +1 或归零
        if tn is not None and _prev_threat is not None:
            if tn != 0 and tn != _prev_threat + 1 and tn != _prev_threat:
                tn = _prev_threat  # 拒绝非法跳变
                ocr_vals["Threat"] = f"{tn}xp"

        _prev_threat = tn
        _prev_stamina = sn
        ocr_filtered = dict(ocr_vals)

    # ===== 渲染 =====
    canvas = np.zeros((WIN_H, WIN_W, 3), dtype=np.uint8)

    # --- 左侧: 游戏截图 (缩略到 MAP_W 宽) ---
    if frame is not None:
        map_scale = MAP_W / gw
        mh = int(gh * map_scale)
        map_disp = cv2.resize(frame, (MAP_W, mh))

        # 画 ROI 绿框
        for name, rx, ry, rw, rh, allow in OCR_REGIONS:
            x = int(rx * map_scale)
            y = int(ry * map_scale)
            w = int(rw * map_scale)
            h = int(rh * map_scale)
            cv2.rectangle(map_disp, (x, y), (x+w, y+h), (0, 255, 0), 2)
            cv2.putText(map_disp, name, (x, y-3), FONT, 0.35, (0, 255, 0), 1)

        canvas[:mh, :MAP_W] = map_disp

    # --- 右侧: ROI 放大 + OCR 数值 ---
    sx = MAP_W + 10
    sy = 10
    for name, rx, ry, rw, rh, allow in OCR_REGIONS:
        if frame is None: break
        roi = frame[ry:ry+rh, rx:rx+rw]
        if roi.size == 0: continue

        # 计算侧边栏每格大小
        h = min(rh * ROI_SCALE, 80)
        w = int(rw * ROI_SCALE * h / (rh * ROI_SCALE)) if rh > 0 else 60
        roi_big = cv2.resize(roi, (w, h), interpolation=cv2.INTER_CUBIC)

        if sy + h + 30 > WIN_H: break  # 超出窗口

        canvas[sy:sy+h, sx:sx+w] = roi_big
        val = ocr_vals.get(name, "?")
        cv2.putText(canvas, f"{name}: {val}", (sx+w+5, sy+15),
                    FONT, 0.5, (0, 255, 0), 1)
        cv2.putText(canvas, f"({rx},{ry}) {rw}x{rh}", (sx+w+5, sy+32),
                    FONT, 0.3, (150, 150, 150), 1)
        sy += h + 12

    # 底部提示
    cv2.putText(canvas, "拖拽绿框=调ROI | Q=退出", (10, WIN_H-10),
                FONT, 0.4, (150, 150, 150), 1)
    cv2.imshow("OCR 状态", canvas)

    key = cv2.waitKey(30) & 0xFF
    if key == ord('q'):
        break
    if key == ord('s'):
        with open(SAVE_FILE, 'w') as f:
            json.dump(OCR_REGIONS, f, indent=2)
        print("ROI已保存:", SAVE_FILE)
        for r in OCR_REGIONS:
            print(f"  {r}")

cap.release()
cv2.destroyAllWindows()
