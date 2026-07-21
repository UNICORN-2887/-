"""
DeadMaze - YOLO 实时检测 + OCR 状态读取
  YOLO: OBS 虚拟摄像头实时识别
  OCR:  直接截取游戏窗口, 每秒一次

操作: Q = 退出
"""

import cv2
import numpy as np
from ultralytics import YOLO
import time
import re
import pytesseract
import win32gui
import mss

# ========== OCR 配置 ==========
pytesseract.pytesseract.tesseract_cmd = r"E:\Tools\tesseract\tesseract.exe"

# OCR 区域 (游戏窗口像素坐标)
OCR_REGIONS = [
    ("HP",        80,  620,  50, 25),
    ("Hunger",   180,  620,  50, 25),
    ("Thirst",   280,  620,  50, 25),
    ("Stamina",  380,  620,  50, 25),
    ("Threat",   480,  620,  60, 25),
]

# ========== YOLO 配置 ==========
MODEL_PATH = r"E:\Project\DeadMaze\AImaneuver\runs\detect\deadmaze_combat\weights\best.pt"
OBS_CAM_ID = 1

# ============================================================
# 找游戏窗口 (用于 OCR 截图)
# ============================================================
def find_game_window():
    pat = re.compile(r'dead[\s]*maze', re.IGNORECASE)
    exc = re.compile(r'visual studio|vscode', re.IGNORECASE)
    results = []
    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if pat.search(t) and not exc.search(t):
                r = win32gui.GetWindowRect(hwnd)
                w, h = r[2]-r[0], r[3]-r[1]
                if 800 <= w <= 2560 and 600 <= h <= 1440:
                    results.append((hwnd, t, r))
    win32gui.EnumWindows(cb, None)
    return results[0] if results else None

hwnd, title, rect = find_game_window()
gw, gh = rect[2]-rect[0], rect[3]-rect[1]
print(f"游戏窗口: \"{title}\" {gw}x{gh} @({rect[0]},{rect[1]})")

sct = mss.mss()
ocr_monitor = {"left": rect[0], "top": rect[1], "width": gw, "height": gh}

# ============================================================
# 加载 YOLO
# ============================================================
print("加载 YOLO...", end=" ", flush=True)
model = YOLO(MODEL_PATH)
print("OK")

# ============================================================
# 打开 OBS 摄像头
# ============================================================
cap = cv2.VideoCapture(OBS_CAM_ID)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
ret, test = cap.read()
if not ret:
    print("OBS 摄像头无画面!"); exit()
yfw, yfh = test.shape[1], test.shape[0]
print(f"OBS: {yfw}x{yfh}")

# ============================================================
# 窗口
# ============================================================
cv2.namedWindow("YOLO 检测", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("YOLO 检测", cv2.WND_PROP_TOPMOST, 1)
FONT = cv2.FONT_HERSHEY_SIMPLEX
last_ocr = 0
ocr_vals = {name: "?" for name, *_ in OCR_REGIONS}
fps_t = time.time(); fc = 0

while True:
    # ===== YOLO (OBS) — 缩小到640加速推理 =====
    ret, yolo_frame = cap.read()
    if not ret:
        time.sleep(0.01); continue

    # 缩小输入加速 YOLO
    yf_small = cv2.resize(yolo_frame, (640, 384))
    det = model(yf_small, verbose=False, conf=0.5)[0]
    annotated = det.plot()
    # 显示也缩小
    annotated = cv2.resize(annotated, (960, 576))

    # ===== OCR (直接截游戏窗口, 每秒一次) =====
    now = time.time()
    if now - last_ocr > 1.0:
        img = np.array(sct.grab(ocr_monitor))
        ocr_frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        ocr_results = {}
        for name, rx, ry, rw, rh in OCR_REGIONS:
            roi = ocr_frame[ry:ry+rh, rx:rx+rw]
            if roi.size == 0: continue
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            _, th = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
            txt = pytesseract.image_to_string(
                th, config=r'--psm 7 -c tessedit_char_whitelist=0123456789'
            ).strip()
            ocr_results[name] = txt if txt else "?"
        ocr_vals = ocr_results
        last_ocr = now
        print(f"OCR: {ocr_vals}")

    # ===== 画 YOLO 窗口上的 OCR 绿框 =====
    # 先缩放 OCR 坐标 (因为 OBS 画面和游戏窗口尺寸可能不同)
    sx_ocr = yfw / gw
    sy_ocr = yfh / gh
    for name, rx, ry, rw, rh in OCR_REGIONS:
        x = int(rx * sx_ocr); y = int(ry * sy_ocr)
        w = int(rw * sx_ocr); h = int(rh * sy_ocr)
        cv2.rectangle(annotated, (x, y), (x+w, y+h), (0, 255, 0), 2)
        cv2.putText(annotated, f"{name}:{ocr_vals.get(name,'?')}",
                    (x, y-5), FONT, 0.4, (0, 255, 0), 1)

    # FPS
    fc += 1
    if now - fps_t > 1.0:
        fps = fc/(now-fps_t); fps_t = now; fc = 0
        cv2.putText(annotated, f"FPS:{fps:.1f}", (10, 25), FONT, 0.5, (0, 255, 0), 2)

    cv2.imshow("YOLO 检测", annotated)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release(); cv2.destroyAllWindows()
