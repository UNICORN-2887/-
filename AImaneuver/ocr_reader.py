"""
DeadMaze - OCR 状态读取器 (EasyOCR + OBS)
OBS 获取画面 → OCR → 绿框 + 侧边栏数值

绿框可拖拽定位, S=保存, Q=退出
"""

import cv2, numpy as np, time, json, os, easyocr, pytesseract
pytesseract.pytesseract.tesseract_cmd = r"E:\Tools\tesseract\tesseract.exe"

# ========== 配置 ==========
OBS_CAM_ID = 1  # OBS 虚拟摄像头
OCR_REGIONS = [
    ("Exp",      80,  620,  50, 25,  "0123456789xp"),
    ("Hunger",   180,  620,  50, 25,  "0123456789"),
    ("Thirst",   280,  620,  50, 25,  "0123456789"),
    ("Stamina",  380,  620,  50, 25,  "0123456789"),
    ("Threat",   480,  620,  50, 25,  "0123456789xp"),
    ("Open",     300,  300,  40, 30,  "开"),
]
OCR_INTERVAL = 1.0; ROI_SCALE = 5
MAP_W = 600; SIDEBAR_W = 350; WIN_H = 600

SAVE_FILE = os.path.join(os.path.dirname(__file__), "ocr_reader_roi.json")
if os.path.exists(SAVE_FILE):
    with open(SAVE_FILE) as f: saved = json.load(f)
    for r in saved:  # 按名称更新, 保留新增的
        for i, orig in enumerate(OCR_REGIONS):
            if orig[0] == r[0]: OCR_REGIONS[i] = tuple(r); break

# ========== OBS ==========
cap = cv2.VideoCapture(OBS_CAM_ID)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
ret, test = cap.read()
if not ret: print(f"OBS摄像头{OBS_CAM_ID}未开!"); exit()
gw, gh = test.shape[1], test.shape[0]
print(f"OBS: {gw}x{gh}")

# ========== OCR ==========
print("EasyOCR...", end=" "); ocr = easyocr.Reader(["en"], gpu=True); print("OK")

# ========== 窗口 ==========
cv2.namedWindow("OCR 状态", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("OCR 状态", cv2.WND_PROP_TOPMOST, 1)
FONT = cv2.FONT_HERSHEY_SIMPLEX

last_t = 0; frame = None
ocr_vals = {r[0]: "?" for r in OCR_REGIONS}
dragging = -1; dstart = (0, 0)

def find_roi(sx, sy):
    ms = MAP_W / gw
    for i, (_, rx, ry, rw, rh, *_) in enumerate(OCR_REGIONS):
        x, y = int(rx*ms), int(ry*ms)
        w, h = int(rw*ms), int(rh*ms)
        if x <= sx <= x+w and y <= sy <= y+h: return i
    return -1

def mouse(event, sx, sy, flags, param):
    global dragging, dstart
    if event == cv2.EVENT_LBUTTONDOWN:
        dragging = find_roi(sx, sy)
        if dragging >= 0: dstart = (sx, sy)
    elif event == cv2.EVENT_LBUTTONUP: dragging = -1
    elif event == cv2.EVENT_MOUSEMOVE and dragging >= 0:
        ms = MAP_W / gw
        dx = int((sx - dstart[0]) / ms); dy = int((sy - dstart[1]) / ms)
        o = OCR_REGIONS[dragging]
        OCR_REGIONS[dragging] = (o[0], o[1]+dx, o[2]+dy, o[3], o[4], o[5])
        dstart = (sx, sy)

cv2.setMouseCallback("OCR 状态", mouse)
print("拖拽绿框定位 | S=保存 | Q=退出")

while True:
    ret, obs = cap.read()
    if not ret: time.sleep(0.01); continue
    now = time.time()

    if now - last_t > OCR_INTERVAL:
        frame = obs.copy(); last_t = now
        for name, rx, ry, rw, rh, allow in OCR_REGIONS:
            roi = frame[ry:ry+rh, rx:rx+rw]
            if roi.size == 0: continue
            if name == "Open":
                # Tesseract 中文识别
                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                big = cv2.resize(gray, (rw*4, rh*4), interpolation=cv2.INTER_CUBIC)
                _, th = cv2.threshold(big, 127, 255, cv2.THRESH_BINARY)
                txt = pytesseract.image_to_string(th, lang='chi_sim', config='--psm 6').strip()
                ocr_vals[name] = "OPEN" if "开" in txt else "?"
                print(f"[Open] raw='{txt}' -> {ocr_vals[name]}")
            else:
                big = cv2.resize(roi, (rw*ROI_SCALE, rh*ROI_SCALE), interpolation=cv2.INTER_CUBIC)
                r = ocr.readtext(big, detail=1, allowlist=allow)
                ocr_vals[name] = r[0][1] if r else "?"

    # 渲染
    ww = MAP_W + SIDEBAR_W
    canvas = np.zeros((WIN_H, ww, 3), dtype=np.uint8)
    ms = MAP_W / gw; mh = int(gh * ms)
    d = cv2.resize(obs, (MAP_W, mh))
    for name, rx, ry, rw, rh, *_ in OCR_REGIONS:
        x, y = int(rx*ms), int(ry*ms); w, h = int(rw*ms), int(rh*ms)
        cv2.rectangle(d, (x, y), (x+w, y+h), (0, 255, 0), 2)
        cv2.putText(d, f"{name}:{ocr_vals.get(name,'?')}", (x, y-3), FONT, 0.3, (0, 255, 0), 1)
    canvas[:mh, :MAP_W] = d

    sx = MAP_W + 10; sy = 10
    for name, rx, ry, rw, rh, allow in OCR_REGIONS:
        roi = obs[ry:ry+rh, rx:rx+rw]
        if roi.size == 0: continue
        h = min(rh * ROI_SCALE, 80)
        w = int(rw * ROI_SCALE * h / (rh * ROI_SCALE)) if rh > 0 else 60
        big = cv2.resize(roi, (w, h), interpolation=cv2.INTER_CUBIC)
        if sy + h + 30 > WIN_H: break
        canvas[sy:sy+h, sx:sx+w] = big
        cv2.putText(canvas, f"{name}:{ocr_vals.get(name,'?')}", (sx+w+5, sy+15), FONT, 0.5, (0, 255, 0), 1)
        cv2.putText(canvas, f"({rx},{ry}) {rw}x{rh}", (sx+w+5, sy+32), FONT, 0.3, (150, 150, 150), 1)
        sy += h + 12

    cv2.putText(canvas, "拖拽绿框 | S=保存 | Q=退出", (10, WIN_H-10), FONT, 0.4, (150, 150, 150), 1)
    cv2.imshow("OCR 状态", canvas)

    key = cv2.waitKey(30) & 0xFF
    if key == ord('q'): break
    if key == ord('s'):
        with open(SAVE_FILE, 'w') as f: json.dump(OCR_REGIONS, f, indent=2)
        print("ROI已保存")

cap.release(); cv2.destroyAllWindows()
