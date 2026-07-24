"""
独立状态检测对比 — 打印HP/H/T/S, 与navigator对比验证
"""
import cv2, numpy as np, json, os, time

BASE = os.path.dirname(__file__)
HP_FILE = os.path.join(BASE, "AImaneuver", "hp_detector_roi.json")
OCR_FILE = os.path.join(BASE, "AImaneuver", "ocr_reader_roi.json")
OBS_CAM = 1

cap = cv2.VideoCapture(OBS_CAM, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

# 加载HP ROI
hp_roi = json.load(open(HP_FILE)) if os.path.exists(HP_FILE) else None
print(f"HP ROI: {hp_roi}")

# 加载OCR ROI
ocr_regions = []
if os.path.exists(OCR_FILE):
    for r in json.load(open(OCR_FILE)):
        ocr_regions.append((r[0], int(r[1]), int(r[2]), int(r[3]), int(r[4])))
print(f"OCR regions: {len(ocr_regions)}")

# EasyOCR
import easyocr
ocr_en = easyocr.Reader(["en"], gpu=True)
print("EasyOCR ready")

last_print = 0
while True:
    ret, frame = cap.read()
    if not ret: time.sleep(0.01); continue

    now = time.time()
    if now - last_print < 2.0:
        cv2.waitKey(30)
        continue
    last_print = now

    # HP
    hp = 0
    if hp_roi:
        hx, hy, hw, hh = [max(1, int(v)) for v in hp_roi]
        roi = frame[hy:hy+hh, hx:hx+hw]
        if roi.size > 0:
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            gm = cv2.inRange(hsv, np.array([35, 40, 40]), np.array([85, 255, 255]))
            hp = int(np.count_nonzero(gm) / gm.size * 100)

    # OCR
    vals = {}
    for name, rx, ry, rw, rh in ocr_regions:
        roi = frame[ry:ry+rh, rx:rx+rw]
        if roi.size == 0: continue
        big = cv2.resize(roi, (rw*5, rh*5), interpolation=cv2.INTER_CUBIC)
        rt = ocr_en.readtext(big, detail=1, allowlist="0123456789")
        if rt:
            raw_parts = [r[1].strip() for r in rt]
            v = "".join([p for p in raw_parts if p.isdigit()])
            if v.isdigit():
                val = int(v)
                if val > 200: val = int(str(val)[:2])
                vals[name] = val
            # 调试打印
            if name in ("Thirst",):
                print(f"  [OCR:{name}] raw={raw_parts} -> v={v}")

    print(f"[Standalone] HP={hp}% H={vals.get('Hunger','?')} T={vals.get('Thirst','?')} S={vals.get('Stamina','?')}")

    key = cv2.waitKey(30) & 0xFF
    if key == ord('q'): break

cap.release()
