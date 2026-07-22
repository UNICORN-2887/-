"""
DeadMaze - HP 血条检测 (OBS)
OBS 获取画面 → 绿色占比 → HP%

绿色框可拖拽定位, IJKL=微调, Shift+IJKL=调大小, S=保存, Q=退出
"""

import cv2, numpy as np, time, json, os

# ========== 配置 ==========
OBS_CAM_ID = 1
HP_ROI = [80, 30, 200, 20]
HP_INTERVAL = 0.5
GREEN_LOW = np.array([35, 40, 40])
GREEN_HIGH = np.array([85, 255, 255])
MAP_W = 600; SIDEBAR_W = 400; WIN_H = 500

SAVE_FILE = os.path.join(os.path.dirname(__file__), "hp_detector_roi.json")
if os.path.exists(SAVE_FILE):
    with open(SAVE_FILE) as f: HP_ROI = json.load(f)

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
FONT = cv2.FONT_HERSHEY_SIMPLEX

last_t = 0; frame = None; hp_pct = 0; gm = None
dragging = False; dstart = (0, 0); rstart = None

def on_mouse(event, sx, sy, flags, param):
    global dragging, dstart, rstart
    ms = MAP_W / gw; rx, ry, rw, rh = HP_ROI
    mx, my = int(rx*ms), int(ry*ms); mw, mh = int(rw*ms), int(rh*ms)
    if event == cv2.EVENT_LBUTTONDOWN and mx <= sx <= mx+mw and my <= sy <= my+mh:
        dragging = True; dstart = (sx, sy); rstart = (rx, ry)
    elif event == cv2.EVENT_LBUTTONUP: dragging = False
    elif event == cv2.EVENT_MOUSEMOVE and dragging:
        dx = int((sx-dstart[0])/ms); dy = int((sy-dstart[1])/ms)
        HP_ROI[0] = rstart[0]+dx; HP_ROI[1] = rstart[1]+dy

cv2.setMouseCallback("HP 检测", on_mouse)
print("拖拽定位 | IJKL=微调 | Shift+IJKL=大小 | S=保存 | Q=退出")

while True:
    ret, obs = cap.read()
    if not ret: time.sleep(0.01); continue
    now = time.time()

    if now - last_t > HP_INTERVAL:
        frame = obs.copy(); last_t = now
        rx, ry, rw, rh = [max(1, v) for v in HP_ROI]
        rx = min(rx, gw-2); ry = min(ry, gh-2)
        rw = min(rw, gw-rx); rh = min(rh, gh-ry)
        HP_ROI = [rx, ry, rw, rh]
        roi = frame[ry:ry+rh, rx:rx+rw]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        gm = cv2.inRange(hsv, GREEN_LOW, GREEN_HIGH)
        hp_pct = np.count_nonzero(gm) / gm.size * 100 if gm.size > 0 else 0

    # 渲染
    ww = MAP_W + SIDEBAR_W
    canvas = np.zeros((WIN_H, ww, 3), dtype=np.uint8)
    ms = MAP_W / gw; mh = int(gh*ms)
    d = cv2.resize(obs, (MAP_W, mh))
    rx, ry, rw, rh = HP_ROI
    x, y, w, h = int(rx*ms), int(ry*ms), int(rw*ms), int(rh*ms)
    cv2.rectangle(d, (x, y), (x+w, y+h), (0, 255, 0), 2)
    cv2.putText(d, f"HP:{hp_pct:.0f}%", (x, y-5), FONT, 0.35, (0, 255, 0), 1)
    canvas[:mh, :MAP_W] = d

    sx = MAP_W + 10; sy = 10
    if frame is not None:
        roi = frame[ry:ry+rh, rx:rx+rw]
        bw = min(rw*2, SIDEBAR_W-20)
        big = cv2.resize(roi, (bw, rh*12), interpolation=cv2.INTER_NEAREST)
        if gm is not None:
            gv = cv2.resize(gm, (bw, rh*12), interpolation=cv2.INTER_NEAREST)
            big[gv > 0] = [0, 255, 0]
        canvas[sy:sy+big.shape[0], sx:sx+big.shape[1]] = big
        sy += big.shape[0] + 5

    cv2.putText(canvas, f"HP: {hp_pct:.1f}%", (sx, sy+18), FONT, 0.6, (0, 255, 0), 2)
    sy += 25
    cv2.putText(canvas, f"({rx},{ry}) {rw}x{rh}", (sx, sy+15), FONT, 0.4, (150, 150, 150), 1)
    sy += 25
    cv2.putText(canvas, "拖拽|IJKL微调|Shift+IJKL大小|S保存", (sx, sy+15), FONT, 0.35, (150, 150, 150), 1)
    sy += 30
    bar_w = 200; bar_h = 25
    cv2.rectangle(canvas, (sx, sy), (sx+bar_w, sy+bar_h), (100, 100, 100), 1)
    cv2.rectangle(canvas, (sx, sy), (sx+int(bar_w*hp_pct/100), sy+bar_h), (0, 200, 0), -1)

    cv2.imshow("HP 检测", canvas)

    key = cv2.waitKey(30) & 0xFF
    if key == ord('q'): break
    step = 1
    if key == ord('j'): HP_ROI[0] -= step
    elif key == ord('l'): HP_ROI[0] += step
    elif key == ord('i'): HP_ROI[1] -= step
    elif key == ord('k'): HP_ROI[1] += step
    elif key == ord('J'): HP_ROI[2] -= step
    elif key == ord('L'): HP_ROI[2] += step
    elif key == ord('I'): HP_ROI[3] -= step
    elif key == ord('K'): HP_ROI[3] += step
    elif key == ord('s'):
        with open(SAVE_FILE, 'w') as f: json.dump(HP_ROI, f)
        print(f"ROI已保存: {HP_ROI}")

cap.release(); cv2.destroyAllWindows()
