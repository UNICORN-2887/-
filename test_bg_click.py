"""
后台鼠标点击测试 - SendMessage(WM_LBUTTONDOWN)
IJKL=移动点击坐标, Enter=点击, Q=退出
"""
import win32gui, win32api, win32con, time, re, cv2, numpy as np

# 找游戏窗口
def find_game():
    results = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h) == 'Dead Maze':
            r = win32gui.GetWindowRect(h)
            if r[2] - r[0] > 800: results.append((h, r))
    win32gui.EnumWindows(cb, None)
    return results[0] if results else None

hwnd, rect = find_game()
gw, gh = rect[2] - rect[0], rect[3] - rect[1]
print(f"游戏: {gw}x{gh} hwnd=0x{hwnd:08X}")
if win32gui.IsIconic(hwnd):
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE); time.sleep(0.2)

cx, cy = gw // 2, gh // 2
step = 5

cv2.namedWindow("后台点击测试", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("后台点击测试", cv2.WND_PROP_TOPMOST, 1)
cv2.resizeWindow("后台点击测试", 400, 200)

while True:
    canvas = np.zeros((200, 400, 3), dtype=np.uint8)
    cv2.putText(canvas, f"XY: ({cx},{cy})  step:{step}", (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    cv2.putText(canvas, "IJKL=move  Enter=click  R/T=step  Q=quit", (20, 80),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
    cv2.imshow("后台点击测试", canvas)

    key = cv2.waitKey(100) & 0xFF
    if key == ord('q'): break
    elif key == ord('i'): cy -= step
    elif key == ord('k'): cy += step
    elif key == ord('j'): cx -= step
    elif key == ord('l'): cx += step
    elif key == ord('r'): step = max(1, step - 1)
    elif key == ord('t'): step += 1
    elif key == 13:  # Enter
        lp = win32api.MAKELONG(cx, cy)
        win32api.SendMessage(hwnd, win32con.WM_LBUTTONDOWN, 0, lp)
        win32api.SendMessage(hwnd, win32con.WM_LBUTTONUP, 0, lp)
        print(f"[点击] ({cx},{cy})")

cv2.destroyAllWindows()
