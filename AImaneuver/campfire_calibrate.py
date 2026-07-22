"""
火堆点击校准工具 - 独立脚本
YOLO实时检测火堆 → 偏移校准 → 后台点击测试 → 保存偏移

IJKL=调偏移  Enter=点击  S=保存  Q=退出
"""

import cv2, numpy as np, json, os, time
import win32gui, win32api, win32con
from ultralytics import YOLO

# ========== 配置 ==========
OBS_CAM_ID = 1
MODEL_PATH = os.path.join(os.path.dirname(__file__),
    "runs", "detect", "deadmaze_combat", "weights", "best.pt")
OFFSET_FILE = os.path.join(os.path.dirname(__file__), "click_offset.json")
CONF_THRESHOLD = 0.3

# ========== 找游戏窗口 ==========
def find_game():
    results = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h) == 'Dead Maze':
            r = win32gui.GetWindowRect(h)
            if r[2] - r[0] > 800:
                results.append(h)
    win32gui.EnumWindows(cb, None)
    return results[0] if results else None

hwnd = find_game()
if not hwnd:
    print("未找到 Dead Maze 窗口!")
    exit()
if win32gui.IsIconic(hwnd):
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    time.sleep(0.2)
print(f"[Game] hwnd=0x{hwnd:08X}")

# ========== OBS 摄像头 ==========
cap = cv2.VideoCapture(OBS_CAM_ID, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
ret, test = cap.read()
if not ret:
    print("OBS 摄像头未开!")
    exit()
obs_w, obs_h = test.shape[1], test.shape[0]
print(f"[OBS] {obs_w}x{obs_h}")

# ========== YOLO ==========
yolo = YOLO(MODEL_PATH)
print(f"[YOLO] 模型加载完成, 类别: {list(yolo.names.values())}")

# ========== 加载已保存偏移 ==========
dx, dy = 0, 0
if os.path.exists(OFFSET_FILE):
    saved = json.load(open(OFFSET_FILE))
    dx, dy = saved.get('dx', 0), saved.get('dy', 0)
    print(f"[偏移] 加载 dx={dx} dy={dy}")

# ========== 窗口 ==========
cv2.namedWindow("YOLO", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("YOLO", cv2.WND_PROP_TOPMOST, 1)

cv2.namedWindow("Calibrate", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("Calibrate", cv2.WND_PROP_TOPMOST, 1)
cv2.resizeWindow("Calibrate", 450, 280)

FONT = cv2.FONT_HERSHEY_SIMPLEX
STEP = 5
last_det = time.time()
campfire_cx, campfire_cy = None, None
annotated = None

print("\n" + "=" * 55)
print("火堆点击校准工具")
print("  IJKL = 调偏移  Enter = 测试点击")
print("  S = 保存偏移  R = 重置偏移")
print("  +/- = 调步长  Q = 退出")
print("=" * 55 + "\n")

while True:
    # 读取OBS帧
    ret, frame = cap.read()
    if not ret:
        time.sleep(0.01)
        continue

    # YOLO检测 (每0.5秒)
    now = time.time()
    if now - last_det > 0.5:
        det = yolo(frame, verbose=False, conf=CONF_THRESHOLD)[0]
        annotated = det.plot()
        last_det = now

        # 查找火堆
        campfire_cx, campfire_cy = None, None
        for b in det.boxes:
            cls_name = yolo.names[int(b.cls[0])]
            if cls_name.lower() == 'campfire':
                x1, y1, x2, y2 = map(int, b.xyxy[0])
                campfire_cx = (x1 + x2) // 2
                campfire_cy = (y1 + y2) // 2
                conf = float(b.conf[0])
                # 画十字
                cv2.drawMarker(annotated, (campfire_cx, campfire_cy),
                              (0, 255, 255), cv2.MARKER_CROSS, 25, 2)
                cv2.putText(annotated, f"Campfire {conf:.2f}",
                           (campfire_cx + 15, campfire_cy - 15),
                           FONT, 0.7, (0, 255, 255), 2)
                break

    # 缩小YOLO画面显示
    if annotated is not None:
        disp = cv2.resize(annotated, (obs_w // 2, obs_h // 2))
    else:
        disp = cv2.resize(frame, (obs_w // 2, obs_h // 2))

    # 标出偏移后的点击位置
    if campfire_cx is not None:
        click_x = campfire_cx + dx
        click_y = campfire_cy + dy
        cv2.drawMarker(disp, (click_x // 2, click_y // 2),
                      (0, 0, 255), cv2.MARKER_CROSS, 15, 1)
        cv2.putText(disp, f"click({click_x},{click_y})",
                   (click_x // 2 + 10, click_y // 2 - 10),
                   FONT, 0.5, (0, 0, 255), 1)

    cv2.imshow("YOLO", disp)

    # 校准面板
    panel = np.zeros((280, 450, 3), dtype=np.uint8)
    cv2.putText(panel, "=== Click Calibrate ===", (10, 25), FONT, 0.5, (0, 255, 0), 1)

    if campfire_cx is not None:
        cv2.putText(panel, f"Campfire OBS: ({campfire_cx}, {campfire_cy})",
                   (10, 55), FONT, 0.45, (255, 255, 0), 1)
        cv2.putText(panel, f"Offset: dx={dx} dy={dy}",
                   (10, 80), FONT, 0.45, (255, 200, 0), 1)
        cv2.putText(panel, f"Click -> ({campfire_cx + dx}, {campfire_cy + dy})",
                   (10, 105), FONT, 0.45, (0, 255, 255), 1)
    else:
        cv2.putText(panel, "Campfire: NOT DETECTED", (10, 55), FONT, 0.5, (0, 0, 255), 1)

    cv2.putText(panel, f"Step: {STEP}", (10, 145), FONT, 0.4, (150, 150, 150), 1)
    cv2.putText(panel, "IJKL=offset  Enter=click  S=save  R=reset  Q=quit",
               (10, 180), FONT, 0.4, (180, 180, 180), 1)
    cv2.putText(panel, "+/-=step  (in YOLO window: red=cross=click target)",
               (10, 210), FONT, 0.35, (150, 150, 150), 1)

    saved_text = f"Saved: dx={dx} dy={dy}" if os.path.exists(OFFSET_FILE) else "Not saved"
    cv2.putText(panel, saved_text, (10, 250), FONT, 0.4, (100, 100, 100), 1)

    cv2.imshow("Calibrate", panel)

    key = cv2.waitKey(100) & 0xFF

    if key == ord('q'):
        break
    elif key == ord('i'):
        dy -= STEP
    elif key == ord('k'):
        dy += STEP
    elif key == ord('j'):
        dx -= STEP
    elif key == ord('l'):
        dx += STEP
    elif key in (ord('+'), ord('=')):
        STEP = min(50, STEP + 1)
    elif key in (ord('-'), ord('_')):
        STEP = max(1, STEP - 1)
    elif key == ord('r'):
        dx, dy = 0, 0
        print(f"[重置] dx=0 dy=0")
    elif key == ord('s'):
        with open(OFFSET_FILE, 'w') as f:
            json.dump({'dx': dx, 'dy': dy}, f)
        print(f"[保存] dx={dx} dy={dy} → {OFFSET_FILE}")
    elif key == 13:  # Enter - 测试点击
        if campfire_cx is not None:
            cx = campfire_cx + dx
            cy = campfire_cy + dy
            lp = win32api.MAKELONG(cx, cy)
            win32api.SendMessage(hwnd, win32con.WM_LBUTTONDOWN, 0, lp)
            time.sleep(0.05)
            win32api.SendMessage(hwnd, win32con.WM_LBUTTONUP, 0, lp)
            print(f"[点击] ({cx}, {cy})")
        else:
            print("[点击] 跳过 - 未检测到火堆")

cap.release()
cv2.destroyAllWindows()
print("退出。偏移已保存到", OFFSET_FILE)
