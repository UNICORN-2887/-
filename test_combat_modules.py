"""
战斗模块独立测试 — 数字键选择测试项
1=HP检测 5=僵尸检测 7=攻击点击 Q=退出
"""
import cv2, numpy as np, json, os, time
import win32gui, win32api, win32con

BASE = os.path.dirname(__file__)
HP_FILE = os.path.join(BASE, "AImaneuver", "hp_detector_roi.json")
CLICK_FILE = os.path.join(BASE, "AImaneuver", "click_points.json")
MODEL_PATH = os.path.join(BASE, "AImaneuver",
    "runs", "detect", "deadmaze_combat", "weights", "best.pt")

OBS_CAM = 1

# ---- 找窗口 ----
def find_game():
    results = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h) == 'Dead Maze':
            r = win32gui.GetWindowRect(h)
            if r[2] - r[0] > 800: results.append(h)
    win32gui.EnumWindows(cb, None)
    return results[0] if results else None

hwnd = find_game()
if not hwnd: print("未找到游戏!"); exit()
print(f"hwnd=0x{hwnd:08X}")

# ---- OBS ----
cap = cv2.VideoCapture(OBS_CAM, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

# ---- YOLO ----
try:
    from ultralytics import YOLO
    yolo = YOLO(MODEL_PATH)
    print("[YOLO] 已加载")
except Exception:
    yolo = None
    print("[YOLO] 未加载")

# ---- 窗口 ----
cv2.namedWindow("CombatTest", cv2.WINDOW_NORMAL)
cv2.resizeWindow("CombatTest", 700, 500)
FONT = cv2.FONT_HERSHEY_SIMPLEX

mode = "就绪"
hp = 100
zombies = []
last_click = 0

print("\n=== 战斗模块测试 ===")
print("1=HP检测  5=僵尸检测  7=攻击点击  Q=退出\n")

while True:
    ret, frame = cap.read()
    if not ret: time.sleep(0.01); continue

    canvas = np.zeros((500, 700, 3), dtype=np.uint8)
    key = cv2.waitKey(30) & 0xFF

    if key == ord('q'): break
    elif key == ord('1'): mode = "HP检测"
    elif key == ord('5'): mode = "僵尸检测"
    elif key == ord('7'): mode = "攻击点击"

    # ---- 1. HP检测 ----
    if mode == "HP检测":
        hp_roi = None
        if os.path.exists(HP_FILE):
            hp_roi = json.load(open(HP_FILE))
        if hp_roi:
            hx, hy, hw, hh = [max(1, int(v)) for v in hp_roi]
            roi = frame[hy:hy + hh, hx:hx + hw]
            if roi.size > 0:
                hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
                gm = cv2.inRange(hsv, np.array([35, 40, 40]),
                                 np.array([85, 255, 255]))
                hp = int(np.count_nonzero(gm) / gm.size * 100)
                # 绿框标注HP区域
                cv2.rectangle(frame, (hx, hy), (hx + hw, hy + hh), (0, 255, 0), 2)

    # ---- 5. 僵尸检测 ----
    if mode == "僵尸检测" and yolo:
        det = yolo(frame, verbose=False, conf=0.3)[0]
        zombies = []
        for b in det.boxes:
            name = yolo.names[int(b.cls[0])]
            if 'ZB' in name.upper() or 'ZOMBIE' in name.upper():
                x1, y1, x2, y2 = map(int, b.xyxy[0])
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2
                dist = int(np.hypot(cx - 960, cy - 1080))
                zombies.append((name, dist, (x1, y1, x2, y2)))
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                cv2.putText(frame, f"{name[-6:]} {dist}px", (x1, y1 - 5),
                           FONT, 0.35, (0, 0, 255), 1)
        zombies.sort(key=lambda z: z[1])
        frame = det.plot()

    # ---- 7. 攻击点击 ----
    if mode == "攻击点击":
        now = time.time()
        if now - last_click > 0.7:
            click_pts = json.load(open(CLICK_FILE))
            atk = click_pts.get("leave_campfire", {"x": 920, "y": 313})
            lp = win32api.MAKELONG(atk["x"], atk["y"])
            win32api.SendMessage(hwnd, win32con.WM_LBUTTONDOWN, 0, lp)
            time.sleep(0.02)
            win32api.SendMessage(hwnd, win32con.WM_LBUTTONUP, 0, lp)
            last_click = now
            print(f"[攻击] ({atk['x']},{atk['y']})")

    # ---- 渲染 ----
    disp = cv2.resize(frame, (600, 340))
    canvas[:340, :600] = disp

    cv2.putText(canvas, f"MODE: {mode}", (10, 360), FONT, 0.5, (0, 255, 0), 1)
    cv2.putText(canvas, f"HP: {hp}%", (10, 390), FONT, 0.5, (0, 255, 255), 1)

    if zombies:
        cv2.putText(canvas, "僵尸:", (10, 420), FONT, 0.4, (255, 100, 100), 1)
        for i, (name, dist, _) in enumerate(zombies[:6]):
            cv2.putText(canvas, f"  {name[-8:]}: {dist}px",
                       (10, 445 + i * 18), FONT, 0.35, (200, 200, 200), 1)

    cv2.putText(canvas, "1=HP 5=僵尸 7=攻击 Q=退出", (10, 485),
               FONT, 0.35, (150, 150, 150), 1)
    cv2.imshow("CombatTest", canvas)

cap.release()
cv2.destroyAllWindows()
