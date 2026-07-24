"""
武器槽空/满检测 — 独立测试
点击organize_bag整理背包 → 检测武器槽第一格是否为空

空槽颜色: RGB(80, 39, 19) ± 容差
O=整理背包  C=检测  Q=退出
"""
import cv2, numpy as np, json, os, time
import win32gui, win32api, win32con

BASE = os.path.dirname(__file__)
CLICK_FILE = os.path.join(BASE, "AImaneuver", "click_points.json")
OBS_CAM = 1

# ---- 武器槽检测区域 (画面坐标) ----
# 默认第一格武器槽位置, IJKL可调
ROI = [1300, 838, 30, 30]  # x, y, w, h

# 空槽参考颜色 RGB
EMPTY_RGB = (80, 39, 19)
TOLERANCE = 40  # 色差容忍度
EMPTY_THRESHOLD = 0.3  # 空槽像素占比>此值=空

# ---- 找游戏窗口 ----
def find_game():
    results = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h) == 'Dead Maze':
            r = win32gui.GetWindowRect(h)
            if r[2] - r[0] > 800: results.append(h)
    win32gui.EnumWindows(cb, None)
    return results[0] if results else None

hwnd = find_game()
if not hwnd: print("未找到 Dead Maze!"); exit()
print(f"hwnd=0x{hwnd:08X}")

# ---- 加载点击坐标 ----
click_pts = json.load(open(CLICK_FILE))

# ---- OBS ----
cap = cv2.VideoCapture(OBS_CAM, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

cv2.namedWindow("WeaponDetect", cv2.WINDOW_NORMAL)
cv2.resizeWindow("WeaponDetect", 900, 550)
FONT = cv2.FONT_HERSHEY_SIMPLEX

status = "就绪 | O=整理  C=检测  IJKL=调ROI  Q=退出"
last_result = None

def click_organize():
    """点击整理背包按钮"""
    org = click_pts.get("organize_bag", {"x": 1480, "y": 857})
    lp = win32api.MAKELONG(org["x"], org["y"])
    win32api.SendMessage(hwnd, win32con.WM_LBUTTONDOWN, 0, lp)
    time.sleep(0.02)
    win32api.SendMessage(hwnd, win32con.WM_LBUTTONUP, 0, lp)
    print(f"[整理] 点击 organize_bag ({org['x']},{org['y']})")

def detect_weapon():
    """检测武器槽是否为空"""
    time.sleep(0.3)  # 等UI更新
    # drain OBS
    for _ in range(3): cap.grab(); cv2.waitKey(1)
    ret, frame = cap.read()
    if not ret: return None, frame

    rx, ry, rw, rh = [max(1, int(v)) for v in ROI]
    rx = min(rx, frame.shape[1] - 2)
    ry = min(ry, frame.shape[0] - 2)
    rw = min(rw, frame.shape[1] - rx)
    rh = min(rh, frame.shape[0] - ry)
    roi = frame[ry:ry+rh, rx:rx+rw]
    if roi.size == 0: return None, frame

    # 计算与空槽颜色匹配的像素比例
    bgr_ref = np.array(EMPTY_RGB[::-1])  # RGB → BGR
    diff = np.abs(roi.astype(np.int16) - bgr_ref.astype(np.int16))
    dist = np.sqrt(np.sum(diff ** 2, axis=2))
    match_mask = dist < TOLERANCE
    match_ratio = np.count_nonzero(match_mask) / match_mask.size

    empty = match_ratio > EMPTY_THRESHOLD
    return {"empty": empty, "ratio": match_ratio, "roi": roi, "mask": match_mask}, frame

while True:
    ret, frame = cap.read()
    if not ret: time.sleep(0.01); continue

    canvas = np.zeros((550, 900, 3), dtype=np.uint8)

    # 左侧: OBS画面
    mw, mh = 650, int(650 * 1080 / 1920)
    disp = cv2.resize(frame, (mw, mh))
    ms = mw / 1920

    # 画检测ROI框
    rx, ry, rw, rh = ROI
    crx, cry = int(rx * ms), int(ry * ms)
    crw, crh = max(1, int(rw * ms)), max(1, int(rh * ms))
    col = (0, 0, 255) if (last_result and last_result.get("empty")) else (0, 255, 0)
    cv2.rectangle(disp, (crx, cry), (crx + crw, cry + crh), col, 2)
    cv2.putText(disp, "Weapon Slot", (crx, cry - 5), FONT, 0.35, col, 1)

    # 画organize_bag按钮位置
    org = click_pts.get("organize_bag", {"x": 1480, "y": 857})
    cv2.circle(disp, (int(org["x"]*ms), int(org["y"]*ms)), 4, (255, 255, 0), -1)
    cv2.putText(disp, "Org", (int(org["x"]*ms) + 5, int(org["y"]*ms)),
               FONT, 0.3, (255, 255, 0), 1)

    canvas[:mh, :mw] = disp

    # 右侧: 检测结果
    rx_p = mw + 15
    cv2.putText(canvas, "Weapon Detect", (rx_p, 20), FONT, 0.5, (0, 255, 0), 1)
    cv2.putText(canvas, f"ROI: ({ROI[0]},{ROI[1]}) {ROI[2]}x{ROI[3]}", (rx_p, 45),
               FONT, 0.3, (200, 200, 200), 1)
    cv2.putText(canvas, f"Ref RGB: {EMPTY_RGB} Tol: {TOLERANCE} Thr: {EMPTY_THRESHOLD}",
               (rx_p, 62), FONT, 0.3, (200, 200, 200), 1)

    if last_result:
        ratio = last_result["ratio"]
        empty = last_result["empty"]
        cv2.putText(canvas, f"Match: {ratio:.1%}", (rx_p, 85), FONT, 0.4,
                   (0, 0, 255) if empty else (0, 255, 0), 1)
        cv2.putText(canvas, "EMPTY - NO WEAPON!" if empty else "HAS WEAPON",
                   (rx_p, 110), FONT, 0.5,
                   (0, 0, 255) if empty else (0, 255, 0), 1)

        # ROI放大预览
        if "roi" in last_result:
            preview = cv2.resize(last_result["roi"], (120, 120), interpolation=cv2.INTER_NEAREST)
            canvas[200:320, rx_p:rx_p+120] = preview
            cv2.putText(canvas, "ROI Preview", (rx_p, 195), FONT, 0.3, (200, 200, 200), 1)

    # 调节提示
    y_b = 450
    cv2.putText(canvas, f"Ref RGB: {EMPTY_RGB}", (10, y_b), FONT, 0.35, (200, 200, 200), 1)
    cv2.putText(canvas, f"Tol={TOLERANCE} (R/F)  Thr={EMPTY_THRESHOLD} (T/G)",
               (10, y_b + 20), FONT, 0.35, (150, 150, 150), 1)
    cv2.putText(canvas, status, (10, 540), FONT, 0.35, (255, 255, 255), 1)

    cv2.imshow("WeaponDetect", canvas)
    key = cv2.waitKey(30) & 0xFF

    if key == ord('q'): break
    elif key in (ord('o'), ord('O')):
        click_organize()
        status = "已整理背包"
    elif key in (ord('c'), ord('C')):
        result, _ = detect_weapon()
        if result:
            last_result = result
            tag = "EMPTY!" if result["empty"] else "HAS WEAPON"
            status = f"{tag} match={result['ratio']:.1%}"
            print(f"[检测] {tag} (match={result['ratio']:.1%})")
        else:
            status = "检测失败"
    # IJKL 调ROI位置
    elif key == ord('i'): ROI[1] -= 2
    elif key == ord('k'): ROI[1] += 2
    elif key == ord('j'): ROI[0] -= 2
    elif key == ord('l'): ROI[0] += 2
    # 调ROI大小
    elif key == ord('I'): ROI[3] -= 2
    elif key == ord('K'): ROI[3] += 2
    elif key == ord('J'): ROI[2] -= 2
    elif key == ord('L'): ROI[2] += 2
    # 调容差
    elif key in (ord('r'), ord('R')): TOLERANCE = min(100, TOLERANCE + 5)
    elif key in (ord('f'), ord('F')): TOLERANCE = max(5, TOLERANCE - 5)
    # 调阈值
    elif key in (ord('t'), ord('T')): EMPTY_THRESHOLD = min(0.9, EMPTY_THRESHOLD + 0.05)
    elif key in (ord('g'), ord('G')): EMPTY_THRESHOLD = max(0.05, EMPTY_THRESHOLD - 0.05)

cap.release()
cv2.destroyAllWindows()
