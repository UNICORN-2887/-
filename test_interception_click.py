"""Interception 后台点击测试 - Enter=点击, Q=退出"""
import interception, time, win32gui, re, cv2, numpy as np

# 找游戏窗口
pat = re.compile(r'dead[\s]*maze', re.IGNORECASE)
exc = re.compile(r'vscode', re.IGNORECASE)
results = []
def cb(h, _):
    if win32gui.IsWindowVisible(h):
        t = win32gui.GetWindowText(h)
        if pat.search(t) and not exc.search(t):
            r = win32gui.GetWindowRect(h)
            if r[2] - r[0] > 800: results.append((h, r))
win32gui.EnumWindows(cb, None)
hwnd, rect = results[0]
gw, gh = rect[2] - rect[0], rect[3] - rect[1]
print(f"游戏: {gw}x{gh} @({rect[0]},{rect[1]})")
cx, cy = rect[0] + gw // 2, rect[1] + gh // 2

interception.auto_capture_devices()
print(f"Interception OK | Enter=点击({cx},{cy}) | Q=退出")

cv2.namedWindow("点击测试", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("点击测试", cv2.WND_PROP_TOPMOST, 1)
cv2.resizeWindow("点击测试", 400, 150)

while True:
    canvas = np.zeros((150, 400, 3), dtype=np.uint8)
    cv2.putText(canvas, "Enter=点击  Q=退出", (50, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.putText(canvas, f"目标: ({cx},{cy})", (50, 90),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
    cv2.imshow("点击测试", canvas)

    key = cv2.waitKey(100) & 0xFF
    if key == ord('q'): break
    if key == 13:  # Enter
        interception.move_to(cx, cy)
        time.sleep(0.02)
        interception.left_click()
        print(f"[点击] ({cx},{cy})")

cv2.destroyAllWindows()
