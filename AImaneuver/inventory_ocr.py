"""
背包物品检测 - IJKL控制游戏内虚拟光标 + OCR
IJKL=移动点击位置, Enter=点击+OCR, [/]=切格子

Q=退出
"""

import cv2, numpy as np, time, json, os, easyocr

# ========== 配置 ==========
OBS_CAM_ID = 1
ROI = [300, 300, 200, 60]         # OCR文字区域
SLOTS = [(400, 300)]              # 点击坐标(游戏窗口坐标系)
OCR_INTERVAL = 0.5
MAP_W = 700; SIDEBAR_W = 250; WIN_H = 500
TARGETS = ["食物", "水"]
CLICK_STEP = 5  # IJKL移动步长

SAVE_FILE = os.path.join(os.path.dirname(__file__), "inventory_roi.json")
SLOT_FILE = os.path.join(os.path.dirname(__file__), "inventory_slots.json")
if os.path.exists(SAVE_FILE):
    with open(SAVE_FILE) as f: ROI = json.load(f)
if os.path.exists(SLOT_FILE):
    with open(SLOT_FILE) as f: SLOTS = json.load(f)
    print(f"加载 {len(SLOTS)} 格子点位")

# ========== OCR ==========
print("EasyOCR(chinese)...", end=" "); ocr_zh = easyocr.Reader(["ch_sim"], gpu=True); print("OK")

# ========== OBS ==========
cap = cv2.VideoCapture(OBS_CAM_ID, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
ret, test = cap.read()
if not ret: print("OBS未开!"); exit()
gw, gh = test.shape[1], test.shape[0]
print(f"OBS: {gw}x{gh}")

cv2.namedWindow("背包检测", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("背包检测", cv2.WND_PROP_TOPMOST, 1)
FONT = cv2.FONT_HERSHEY_SIMPLEX

last_t = 0; frame = None; result_text = "?"
dragging = False; dstart = (0, 0); rstart = None
cur_slot = 0
last_click = None  # (x, y, t) 上次点击位置+时间

# 后台操控
try:
    import sys, os as _os
    _root = _os.path.join(_os.path.dirname(__file__), '..')
    if _root not in sys.path: sys.path.insert(0, _root)
    from game_controller import DeadMazeController
    ctrl = DeadMazeController(); ctrl.find_window()
    print("控制器就绪")
except Exception as e:
    ctrl = None; print(f"无控制器: {e}")

def on_mouse(event, sx, sy, flags, param):
    global dragging, dstart, rstart
    ms = MAP_W / gw
    ix = int(sx / ms); iy = int(sy / ms)  # 原图坐标

    # 检查是否点在绿框上
    rx, ry, rw, rh = ROI
    mx, my = int(rx*ms), int(ry*ms); mw, mh = int(rw*ms), int(rh*ms)
    on_box = mx <= sx <= mx+mw and my <= sy <= my+mh

    if event == cv2.EVENT_LBUTTONDOWN:
        if on_box:
            dragging = True; dstart = (sx, sy); rstart = (rx, ry)
        else:
            # 点在别处 → 添加格子点位
            SLOTS.append([ix, iy])
            print(f"[格子] #{len(SLOTS)} ({ix},{iy})")
    elif event == cv2.EVENT_RBUTTONDOWN:
        # 右键删除最近格子
        if SLOTS:
            md = 999; mi = 0
            for i, (sx2, sy2) in enumerate(SLOTS):
                d = (sx2-ix)**2 + (sy2-iy)**2
                if d < md: md = d; mi = i
            if md < 2500:
                print(f"[删除] 格子#{mi+1} ({SLOTS[mi][0]},{SLOTS[mi][1]})")
                SLOTS.pop(mi)
    elif event == cv2.EVENT_LBUTTONUP: dragging = False
    elif event == cv2.EVENT_MOUSEMOVE and dragging:
        dx = int((sx-dstart[0])/ms); dy = int((sy-dstart[1])/ms)
        ROI[0] = rstart[0]+dx; ROI[1] = rstart[1]+dy

cv2.setMouseCallback("背包检测", on_mouse)
print("[ ]切格子 | IJKL=移点位 | Enter=点击+OCR | S=保存 | Q=退出")

while True:
    ret, obs = cap.read()
    if not ret: time.sleep(0.01); continue
    now = time.time()

    if now - last_t > OCR_INTERVAL:
        frame = obs.copy(); last_t = now
        rx, ry, rw, rh = [max(1, v) for v in ROI]
        rx = min(rx, gw-2); ry = min(ry, gh-2)
        rw = min(rw, gw-rx); rh = min(rh, gh-ry)
        ROI[:] = [rx, ry, rw, rh]

        roi = frame[ry:ry+rh, rx:rx+rw]
        big = cv2.resize(roi, (rw*3, rh*3), interpolation=cv2.INTER_CUBIC)
        r = ocr_zh.readtext(big, detail=1)
        txt = " ".join([line[1] for line in r]) if r else ""
        found = [t for t in TARGETS if t in txt]
        result_text = ",".join(found) if found else f"-"
        if txt.strip():
            print(f"[OCR] '{txt}' | {'✅'+result_text if found else '无目标'}")

    # 渲染
    ww = MAP_W + SIDEBAR_W
    canvas = np.zeros((WIN_H, ww, 3), dtype=np.uint8)
    ms = MAP_W / gw; mh = int(gh*ms)
    d = cv2.resize(obs, (MAP_W, mh))
    x, y, w, h = int(ROI[0]*ms), int(ROI[1]*ms), int(ROI[2]*ms), int(ROI[3]*ms)
    cv2.rectangle(d, (x, y), (x+w, y+h), (0, 255, 0), 2)
    cv2.putText(d, result_text, (x, y-5), FONT, 0.4, (0, 255, 0), 1)
    # 上次点击的十字标记
    if last_click:
        cx, cy, ct = last_click
        if time.time() - ct < 1.5:
            cpx, cpy = int(cx*ms), int(cy*ms)
            cv2.line(d, (cpx-10, cpy), (cpx+10, cpy), (0, 0, 255), 2)
            cv2.line(d, (cpx, cpy-10), (cpx, cpy+10), (0, 0, 255), 2)
    # 格子点位
    for i, (sx2, sy2) in enumerate(SLOTS):
        px, py = int(sx2*ms), int(sy2*ms)
        is_sel = (i == cur_slot)
        color = (0, 255, 255) if is_sel else (255, 255, 0)
        r = 7 if is_sel else 5
        cv2.circle(d, (px, py), r, color, -1)
        cv2.putText(d, str(i+1), (px+6, py+4), FONT, 0.3, color, 1)
    canvas[:mh, :MAP_W] = d

    sx = MAP_W + 10; sy = 10
    if frame is not None:
        roi = frame[ROI[1]:ROI[1]+ROI[3], ROI[0]:ROI[0]+ROI[2]]
        max_h = WIN_H - sy - 60  # 留60px给底部文字
        rh_scale = min(5, max_h / max(ROI[3], 1))
        bw = min(ROI[2]*3, SIDEBAR_W-20)
        big = cv2.resize(roi, (bw, int(ROI[3]*rh_scale)),
                         interpolation=cv2.INTER_CUBIC)
        dh = min(big.shape[0], max_h)
        canvas[sy:sy+dh, sx:sx+big.shape[1]] = big[:dh]
        sy += dh+5

    cv2.putText(canvas, f"检测: {result_text}", (sx, sy+18), FONT, 0.5, (0, 255, 0), 2)
    sy += 25
    if SLOTS:
        cv2.putText(canvas, f"格子#{cur_slot+1}: ({SLOTS[cur_slot][0]},{SLOTS[cur_slot][1]})", (sx, sy+15), FONT, 0.35, (255, 255, 0), 1)
        sy += 20
    cv2.putText(canvas, f"OCR: ({ROI[0]},{ROI[1]}) {ROI[2]}x{ROI[3]}", (sx, sy+15), FONT, 0.35, (150, 150, 150), 1)
    sy += 25
    cv2.putText(canvas, "IJKL=移点位 Enter=点击+OCR []=切格 S=保存", (sx, sy+15), FONT, 0.35, (150, 150, 150), 1)

    cv2.imshow("背包检测", canvas)
    key = cv2.waitKey(30) & 0xFF
    if key == ord('q'): break
    # IJKL = 移动当前格子的点击坐标
    if SLOTS:
        if key == ord('j'): SLOTS[cur_slot][0] -= CLICK_STEP
        elif key == ord('l'): SLOTS[cur_slot][0] += CLICK_STEP
        elif key == ord('i'): SLOTS[cur_slot][1] -= CLICK_STEP
        elif key == ord('k'): SLOTS[cur_slot][1] += CLICK_STEP
    # Shift+IJKL = 调OCR框
    if key == ord('J'): ROI[2] -= 1
    elif key == ord('L'): ROI[2] += 1
    elif key == ord('I'): ROI[3] -= 1
    elif key == ord('K'): ROI[3] += 1
    elif key == ord('s'):
        with open(SAVE_FILE, 'w') as f: json.dump(ROI, f)
        with open(SLOT_FILE, 'w') as f: json.dump(SLOTS, f)
        print(f"已保存 ROI + {len(SLOTS)} 个格子")
    elif key == ord('[') and SLOTS:
        cur_slot = (cur_slot - 1) % len(SLOTS)
        print(f"[选择] 格子#{cur_slot+1} ({SLOTS[cur_slot][0]},{SLOTS[cur_slot][1]})")
    elif key == ord(']') and SLOTS:
        cur_slot = (cur_slot + 1) % len(SLOTS)
        print(f"[选择] 格子#{cur_slot+1} ({SLOTS[cur_slot][0]},{SLOTS[cur_slot][1]})")
    elif key == 13 and SLOTS:  # Enter
        sx_, sy_ = SLOTS[cur_slot]
        if ctrl: ctrl.click(sx_, sy_)
        last_click = (sx_, sy_, time.time())
        print(f"[点击] 格子#{cur_slot+1} ({sx_},{sy_})")
        time.sleep(0.3)
        # 读取OCR结果
        roi2 = frame[ROI[1]:ROI[1]+ROI[3], ROI[0]:ROI[0]+ROI[2]]
        big = cv2.resize(roi2, (ROI[2]*3, ROI[3]*3), interpolation=cv2.INTER_CUBIC)
        r = ocr_zh.readtext(big, detail=1)
        txt = " ".join([line[1] for line in r]) if r else ""
        found = [t for t in TARGETS if t in txt]
        result_text = ",".join(found) if found else f"-"
        print(f"[格子#{cur_slot+1}] 点击({sx_},{sy_}) | '{txt}' | {'✅'+result_text if found else '空'}")

cap.release(); cv2.destroyAllWindows()
