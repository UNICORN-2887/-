"""
DeadMaze - 战斗仪表盘
左侧: OBS+YOLO检测框, 右侧: OCR状态+HP+僵尸统计

Q=退出
"""

import cv2, numpy as np, time, json, os, easyocr, pytesseract
from ultralytics import YOLO
pytesseract.pytesseract.tesseract_cmd = r"E:\Tools\tesseract\tesseract.exe"

# ========== 配置 ==========
OBS_CAM_ID = 1
OCR_INTERVAL = 1.0; YOLO_INTERVAL = 0.5; ROI_SCALE = 5
MAP_W = 640; SIDEBAR_W = 320; WIN_H = 700
GREEN_LOW = np.array([35, 40, 40]); GREEN_HIGH = np.array([85, 255, 255])
MODEL_PATH = os.path.join(os.path.dirname(__file__),
    "runs", "detect", "deadmaze_combat", "weights", "best.pt")
ENEMY_CLASSES = {'CrawerZB','ExploderZB','PerubianZB','PitcherZB',
                 'SimpleZB','SlowerZB','SprinkerZB','SummonerZB','ZombieE'}

# ========== 加载保存的 ROI ==========
OCR_REGIONS = [
    ("Exp", 80, 620, 50, 25, "0123456789xp"),
    ("Hunger", 180, 620, 50, 25, "0123456789"),
    ("Thirst", 280, 620, 50, 25, "0123456789"),
    ("Stamina", 380, 620, 50, 25, "0123456789"),
    ("Threat", 480, 620, 50, 25, "0123456789xp"),
    ("Open", 300, 300, 40, 30, "开"),  # 中文"开"字识别
]
HP_ROI = [80, 30, 200, 20]

for fn, target in [("ocr_reader_roi.json", OCR_REGIONS), ("hp_detector_roi.json", HP_ROI)]:
    p = os.path.join(os.path.dirname(__file__), fn)
    if os.path.exists(p):
        with open(p) as f:
            data = json.load(f)
        if fn.startswith("ocr"):
            # 保留额外区域(如Open)
            for r in data:
                found = False
                for i, orig in enumerate(OCR_REGIONS):
                    if orig[0] == r[0]: OCR_REGIONS[i] = tuple(r); found = True; break
                if not found: OCR_REGIONS.append(tuple(r))
        else: HP_ROI = data
        print(f"加载 {fn}")

# ========== OBS ==========
cap = cv2.VideoCapture(OBS_CAM_ID)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
ret, test = cap.read()
if not ret: print("OBS未开!"); exit()
gw, gh = test.shape[1], test.shape[0]
print(f"OBS: {gw}x{gh}")

# ========== 模型 ==========
ocr = easyocr.Reader(["en"], gpu=True)
yolo = YOLO(MODEL_PATH)
print("模型就绪")

cv2.namedWindow("战斗仪表盘", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("战斗仪表盘", cv2.WND_PROP_TOPMOST, 1)
FONT = cv2.FONT_HERSHEY_SIMPLEX

last_ocr = 0; last_yolo = 0
ocr_vals = {r[0]: "?" for r in OCR_REGIONS}
enemy_counts = {}; hp_pct = 0
_exp_max = 0; _prev_exp = 0
_prev_vals = {}# 上次的 Hunger/Thirst/Stamina 值
annotated = None
dragging = -1; dstart = (0, 0)

def find_roi(sx, sy):
    ms = MAP_W / gw
    for i, (_, rx, ry, rw, rh, *_) in enumerate(OCR_REGIONS):
        x, y = int(rx*ms), int(ry*ms); w, h = int(rw*ms), int(rh*ms)
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

cv2.setMouseCallback("战斗仪表盘", mouse)
SAVE_FILE = os.path.join(os.path.dirname(__file__), "ocr_reader_roi.json")

while True:
    ret, frame = cap.read()
    if not ret: time.sleep(0.01); continue
    now = time.time()

    # YOLO
    if now - last_yolo > YOLO_INTERVAL:
        yf = cv2.resize(frame, (640, 384))
        det = yolo(yf, verbose=False, conf=0.4)[0]
        annotated = cv2.resize(det.plot(), (gw, gh))
        counts = {}
        for b in det.boxes:
            cls = yolo.names[int(b.cls[0])]
            if cls in ENEMY_CLASSES: counts[cls] = counts.get(cls, 0) + 1
        enemy_counts = counts; last_yolo = now

    if annotated is None: annotated = frame.copy()

    # OCR
    if frame is not None and now - last_ocr > OCR_INTERVAL:
        for name, rx, ry, rw, rh, allow in OCR_REGIONS:
            roi = frame[ry:ry+rh, rx:rx+rw]
            if roi.size == 0: continue
            if name == "Open":
                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                big = cv2.resize(gray, (rw*4, rh*4), interpolation=cv2.INTER_CUBIC)
                _, th = cv2.threshold(big, 127, 255, cv2.THRESH_BINARY)
                txt = pytesseract.image_to_string(th, lang='chi_sim', config='--psm 6').strip()
                ocr_vals[name] = "OPEN" if "开" in txt else "?"
            else:
                big = cv2.resize(roi, (rw*ROI_SCALE, rh*ROI_SCALE), interpolation=cv2.INTER_CUBIC)
                r = ocr.readtext(big, detail=1, allowlist=allow)
                ocr_vals[name] = r[0][1] if r else "?"
        # 约束: Hunger/Thirst/Stamina ≤200, 变化≤2
        for nm in ["Hunger", "Thirst", "Stamina"]:
            v = ocr_vals.get(nm, "?")
            if v.isdigit():
                n = int(v)
                if n > 200: n = int(v[:2])
                if nm in _prev_vals:
                    p = _prev_vals[nm]
                    if abs(n - p) > 2: n = p  # 变化超2,拒绝
                _prev_vals[nm] = n
                ocr_vals[nm] = str(n)
        # Exp: 只增不减, 增量≤80, 上限5000, 0=死亡重置
        ev = ocr_vals.get("Exp", "?")
        en = int(''.join(c for c in ev if c.isdigit())) if any(c.isdigit() for c in ev) else None
        if en is not None:
            if en == 0:
                _exp_max = 0; _prev_exp = 0
            elif en > _prev_exp + 80:
                en = _prev_exp  # 跳变超80, 拒绝
            if en > 5000:
                en = int(str(en)[:-1])  # 截断最后一位
            _exp_max = max(_exp_max, en)
            _prev_exp = en
            ocr_vals["Exp"] = f"{_exp_max}xp"
        last_ocr = now

    # HP
    rx, ry, rw, rh = [max(1, v) for v in HP_ROI]
    rx = min(rx, gw-2); ry = min(ry, gh-2); rw = min(rw, gw-rx); rh = min(rh, gh-ry)
    hp_roi = frame[ry:ry+rh, rx:rx+rw]
    if hp_roi.size > 0:
        hsv = cv2.cvtColor(hp_roi, cv2.COLOR_BGR2HSV)
        gm = cv2.inRange(hsv, GREEN_LOW, GREEN_HIGH)
        hp_pct = np.count_nonzero(gm) / gm.size * 100 if gm.size > 0 else hp_pct

    # ===== 渲染 =====
    ww = MAP_W + SIDEBAR_W
    canvas = np.zeros((WIN_H, ww, 3), dtype=np.uint8)
    ms = MAP_W / gw; mh = int(gh * ms)
    d = cv2.resize(annotated, (MAP_W, mh))
    # HP框
    cx, cy, cw, ch = int(rx*ms), int(ry*ms), int(rw*ms), int(rh*ms)
    cv2.rectangle(d, (cx, cy), (cx+cw, cy+ch), (0, 255, 0), 2)
    # OCR框
    for name, rx2, ry2, rw2, rh2, *_ in OCR_REGIONS:
        x = int(rx2*ms); y = int(ry2*ms); w = int(rw2*ms); h = int(rh2*ms)
        cv2.rectangle(d, (x, y), (x+w, y+h), (0, 255, 0), 1)
    canvas[:mh, :MAP_W] = d

    # 侧边栏
    sx = MAP_W + 10; sy = 10
    cv2.putText(canvas, "STATUS", (sx, sy+15), FONT, 0.45, (0, 255, 0), 1); sy += 20
    for name in ["Exp", "Hunger", "Thirst", "Stamina", "Threat", "Open"]:
        cv2.putText(canvas, f"{name}: {ocr_vals.get(name,'?')}", (sx, sy+15), FONT, 0.4, (0, 255, 0), 1); sy += 18
    sy += 5
    cv2.putText(canvas, f"HP: {hp_pct:.0f}%", (sx, sy+15), FONT, 0.4, (0, 255, 0), 1); sy += 18
    bw = 200; bh = 15
    cv2.rectangle(canvas, (sx, sy), (sx+bw, sy+bh), (100, 100, 100), 1)
    cv2.rectangle(canvas, (sx, sy), (sx+int(bw*hp_pct/100), sy+bh), (0, 200, 0), -1)
    sy += bh + 10
    total = sum(enemy_counts.values())
    cv2.putText(canvas, f"ZOMBIES: {total}", (sx, sy+15), FONT, 0.45, (0, 0, 255), 1); sy += 20
    for name, cnt in sorted(enemy_counts.items(), key=lambda x: -x[1])[:8]:
        cv2.putText(canvas, f"  {name}: {cnt}", (sx, sy+12), FONT, 0.35, (0, 0, 255), 1); sy += 15

    cv2.imshow("战斗仪表盘", canvas)
    key = cv2.waitKey(30) & 0xFF
    if key == ord('q'): break
    if key == ord('s'):
        with open(SAVE_FILE, 'w') as f: json.dump(OCR_REGIONS, f, indent=2)
        print("ROI已保存")

cap.release(); cv2.destroyAllWindows()
