"""
独立状态检测 — 灰度6x放大, 打印所有OCR原始结果
"""
import cv2, numpy as np, json, os, time, easyocr

BASE = os.path.dirname(__file__)
HP_FILE = os.path.join(BASE, "AImaneuver", "hp_detector_roi.json")
OCR_FILE = os.path.join(BASE, "AImaneuver", "ocr_reader_roi.json")
OBS_CAM = 1

cap = cv2.VideoCapture(OBS_CAM, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

hp_roi = json.load(open(HP_FILE)) if os.path.exists(HP_FILE) else None
ocr_regions = []
if os.path.exists(OCR_FILE):
    for r in json.load(open(OCR_FILE)):
        ocr_regions.append((r[0], int(r[1]), int(r[2]), int(r[3]), int(r[4])))
print(f"HP ROI: {hp_roi}")
print(f"OCR regions: {len(ocr_regions)}")

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

    # OCR — 和ocr_reader一样的灰度6x放大
    vals = {}
    for name, rx, ry, rw, rh in ocr_regions:
        roi = frame[ry:ry+rh, rx:rx+rw]
        if roi.size == 0: continue
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        big = cv2.resize(gray, (rw*6, rh*6), interpolation=cv2.INTER_CUBIC)
        rt = ocr_en.readtext(big, detail=1, allowlist="0123456789")
        parts = []
        if rt:
            for r in rt:
                s = r[1].strip()
                if s.isdigit(): parts.append(s)
            v = "".join(parts)
            if v.isdigit():
                val = int(v)
                if val > 200: val = int(str(val)[:2])
                vals[name] = val
            print(f"  [OCR:{name}] raw_parts={parts} -> {v}")
        else:
            print(f"  [OCR:{name}] NO RESULT")
            vals[name] = 0

    print(f"[Standalone] HP={hp}% H={vals.get('Hunger','?')} T={vals.get('Thirst','?')} S={vals.get('Stamina','?')}")

    key = cv2.waitKey(30) & 0xFF
    if key == ord('q'): break

cap.release()
