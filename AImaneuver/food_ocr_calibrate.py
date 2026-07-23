"""
食物/水 OCR 区域标定工具
拖拽绿框定位 tooltip 出现区域 → 实时 EasyOCR 检测 "食物"/"水" + 数字

拖拽绿框定位 | IJKL=微调 | Shift+IJKL=调大小 | S=保存 | Q=退出
"""

import cv2, numpy as np, json, os, time, easyocr

# ========== 配置 ==========
OBS_CAM_ID = 1
SAVE_FILE = os.path.join(os.path.dirname(__file__), "food_ocr_roi.json")
ROI = [200, 200, 250, 120]  # 默认: x, y, w, h

# 加载已保存
if os.path.exists(SAVE_FILE):
    ROI = json.load(open(SAVE_FILE))
    print(f"[加载] ROI: {ROI}")

# ========== OBS ==========
cap = cv2.VideoCapture(OBS_CAM_ID, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
ret, test = cap.read()
if not ret: print("OBS未开!"); exit()
obs_w, obs_h = test.shape[1], test.shape[0]
print(f"[OBS] {obs_w}x{obs_h}")

# ========== OCR ==========
print("EasyOCR(chinese)...", end=" ")
ocr = easyocr.Reader(["ch_sim"], gpu=True)
print("OK")

# ========== 窗口 ==========
cv2.namedWindow("FoodOCR", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("FoodOCR", cv2.WND_PROP_TOPMOST, 1)
cv2.resizeWindow("FoodOCR", 900, 650)
FONT = cv2.FONT_HERSHEY_SIMPLEX

# 鼠标拖拽
dragging = False
dstart = (0, 0)
rstart = None
last_ocr_txt = ""
last_ocr_time = 0
food_type = None
food_qty = None

def on_mouse(event, sx, sy, flags, param):
    global dragging, dstart, rstart
    ms = 600 / obs_w  # display scale
    rx, ry, rw, rh = ROI
    mx, my = int(rx * ms), int(ry * ms)
    mw, mh = int(rw * ms), int(rh * ms)
    on_box = mx <= sx <= mx + mw and my <= sy <= my + mh

    if event == cv2.EVENT_LBUTTONDOWN and on_box:
        dragging = True
        dstart = (sx, sy)
        rstart = (rx, ry)
    elif event == cv2.EVENT_LBUTTONUP:
        dragging = False
    elif event == cv2.EVENT_MOUSEMOVE and dragging:
        dx = int((sx - dstart[0]) / ms)
        dy = int((sy - dstart[1]) / ms)
        ROI[0] = max(0, rstart[0] + dx)
        ROI[1] = max(0, rstart[1] + dy)

cv2.setMouseCallback("FoodOCR", on_mouse)

print("\n拖拽绿框定位 | IJKL=微调(1px) | Shift+IJKL=调大小 | S=保存 | Q=退出\n")

while True:
    ret, frame = cap.read()
    if not ret:
        time.sleep(0.01)
        continue
    now = time.time()

    # OCR (每秒)
    if now - last_ocr_time > 1.0:
        rx, ry, rw, rh = [max(1, int(v)) for v in ROI]
        rx = min(rx, obs_w - 2)
        ry = min(ry, obs_h - 2)
        rw = min(rw, obs_w - rx)
        rh = min(rh, obs_h - ry)
        ROI[:] = [rx, ry, rw, rh]

        roi = frame[ry:ry + rh, rx:rx + rw]
        if roi.size > 0:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            big = cv2.resize(gray, (rw * 3, rh * 3), interpolation=cv2.INTER_CUBIC)
            r = ocr.readtext(big, detail=1)

            import re
            full_txt = " ".join([line[1] for line in r]) if r else ""
            last_ocr_txt = full_txt if full_txt else "(空)"

            food_qty = None
            water_qty = None

            # 在完整文本中找 "食物" 后面的数字
            fm = re.search(r'食物\s*[+-]?\s*(\d+)', full_txt)
            if fm:
                food_qty = int(fm.group(1))

            # 找 "水" 后面的数字
            wm = re.search(r'水\s*[+-]?\s*(\d+)', full_txt)
            if wm:
                water_qty = int(wm.group(1))

            if food_qty is not None or water_qty is not None:
                parts = []
                if food_qty is not None:
                    parts.append(f"食物 x{food_qty}")
                if water_qty is not None:
                    parts.append(f"水 x{water_qty}")
                print(f"[OCR] '{full_txt[:60]}...' → {' | '.join(parts)}")
            elif full_txt and full_txt != "(空)":
                print(f"[OCR] '{full_txt[:60]}...' → 未检测到食物/水")

            last_ocr_time = now

    # ===== 渲染 =====
    canvas = np.zeros((650, 900, 3), dtype=np.uint8)

    # 左侧: OBS
    mw, mh = 600, int(600 * obs_h / obs_w)
    disp = cv2.resize(frame, (mw, mh))
    ms = mw / obs_w

    # 绿框
    rx, ry, rw, rh = ROI
    x, y = int(rx * ms), int(ry * ms)
    w, h = max(1, int(rw * ms)), max(1, int(rh * ms))
    cv2.rectangle(disp, (x, y), (x + w, y + h), (0, 255, 0), 2)
    cv2.putText(disp, "Tooltip OCR", (x, y - 5), FONT, 0.4, (0, 255, 0), 1)

    canvas[:mh, :mw] = disp

    # 右侧: OCR 结果
    sx = mw + 15
    cv2.putText(canvas, "=== Food OCR Calibrate ===", (sx, 20), FONT, 0.5, (0, 255, 0), 1)
    cv2.putText(canvas, f"ROI: ({rx},{ry}) {rw}x{rh}", (sx, 50), FONT, 0.4, (200, 200, 200), 1)
    cv2.putText(canvas, f"OCR: {last_ocr_txt[:80]}", (sx, 80), FONT, 0.4, (255, 255, 0), 1)
    ly = 110
    if food_qty is not None:
        cv2.putText(canvas, f"Food x{food_qty}", (sx, ly), FONT, 0.6, (0, 255, 0), 2)
        ly += 30
    if water_qty is not None:
        cv2.putText(canvas, f"Water x{water_qty}", (sx, ly), FONT, 0.6, (255, 255, 0), 2)
        ly += 30
    if food_qty is None and water_qty is None:
        cv2.putText(canvas, "(no food/water detected)", (sx, ly), FONT, 0.4, (100, 100, 100), 1)

    # ROI 放大预览
    if frame is not None:
        roi = frame[ry:ry + rh, rx:rx + rw]
        if roi.size > 0:
            preview = cv2.resize(roi, (rw * 2, rh * 2), interpolation=cv2.INTER_CUBIC)
            ph, pw = preview.shape[:2]
            if sy_prev := 150:
                if ph > 0 and pw > 0:
                    fit_w = min(pw, 250)
                    fit_h = min(ph, 400)
                    canvas[sy_prev:sy_prev + fit_h, sx:sx + fit_w] = preview[:fit_h, :fit_w]

    cv2.putText(canvas, "Drag green box | IJKL=move | Shift+IJKL=resize | S=save | Q=quit",
               (10, 635), FONT, 0.35, (150, 150, 150), 1)
    cv2.putText(canvas, f"ROI: ({rx},{ry},{rw},{rh})",
               (10, 620), FONT, 0.35, (150, 150, 150), 1)

    cv2.imshow("FoodOCR", canvas)
    key = cv2.waitKey(30) & 0xFF

    STEP = 1
    if key == ord('q'):
        break
    # IJKL 微调位置
    elif key == ord('i'):
        ROI[1] -= STEP
    elif key == ord('k'):
        ROI[1] += STEP
    elif key == ord('j'):
        ROI[0] -= STEP
    elif key == ord('l'):
        ROI[0] += STEP
    # Shift+IJKL 调大小
    elif key == ord('I'):
        ROI[3] = max(10, ROI[3] - STEP)
    elif key == ord('K'):
        ROI[3] += STEP
    elif key == ord('J'):
        ROI[2] = max(10, ROI[2] - STEP)
    elif key == ord('L'):
        ROI[2] += STEP
    elif key == ord('s'):
        with open(SAVE_FILE, 'w') as f:
            json.dump(ROI, f)
        print(f"[保存] ROI={ROI} → {SAVE_FILE}")

cap.release()
cv2.destroyAllWindows()
