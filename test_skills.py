"""
技能自动释放测试 — 冷却好了自动按1/2/3/4
Q=退出  E=开关  1/2/3/4=手动释放
"""
import time, cv2, numpy as np
import win32gui, win32api, win32con

# ---- 技能冷却管理器 (与navigator一致) ----
class SkillCooldown:
    def __init__(self):
        self.cooldowns = [3.0, 5.0, 8.0, 12.0]
        self.last_used = [0.0, 0.0, 0.0, 0.0]
        self.enabled = True
    def use(self, idx, hwnd):
        now = time.time()
        if not self.is_ready(idx, now): return False
        self.last_used[idx] = now
        vk = [ord('1'), ord('2'), ord('3'), ord('4')][idx]
        lp = 0  # lparam for key
        win32api.SendMessage(hwnd, win32con.WM_KEYDOWN, vk, lp)
        time.sleep(0.05)
        win32api.SendMessage(hwnd, win32con.WM_KEYUP, vk, lp)
        print(f"  [释放] skill_{idx+1}  冷却{self.cooldowns[idx]}s")
        return True
    def is_ready(self, idx, now=None):
        if now is None: now = time.time()
        return (now - self.last_used[idx]) >= self.cooldowns[idx]
    def remaining(self, idx, now=None):
        if now is None: now = time.time()
        return max(0, self.cooldowns[idx] - (now - self.last_used[idx]))
    def all_ready(self, now=None):
        return [i for i in range(4) if self.is_ready(i, now)]

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
if not hwnd: print("未找到 Dead Maze!"); exit()
print(f"游戏窗口: 0x{hwnd:08X}")

skills = SkillCooldown()

cv2.namedWindow("SkillTest", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("SkillTest", cv2.WND_PROP_TOPMOST, 1)
cv2.resizeWindow("SkillTest", 400, 220)

print("技能自动释放测试 — 冷却好了自动按")
print("默认CD: 3/5/8/12s | Q=退出 | 1/2/3/4=手动 | E=开关\n")

while True:
    canvas = np.zeros((220, 400, 3), dtype=np.uint8)
    FONT = cv2.FONT_HERSHEY_SIMPLEX
    now = time.time()

    # 自动释放冷却好的技能
    if skills.enabled:
        ready = skills.all_ready(now)
        if ready:
            for idx in ready:
                skills.use(idx, hwnd)
                break

    # 面板
    cv2.putText(canvas, "技能冷却 (自动)", (5, 20), FONT, 0.5, (0, 255, 255), 1)
    state = "ON" if skills.enabled else "OFF"
    cv2.putText(canvas, f"自动释放: {state} (E切换)", (5, 40), FONT, 0.35, (150, 150, 150), 1)

    for i in range(4):
        y = 65 + i * 30
        cd = skills.cooldowns[i]
        rem = skills.remaining(i, now)
        ready = rem <= 0
        col = (0, 255, 0) if ready else (100, 100, 255)
        bar_w = int(150 * (1 - rem / cd)) if cd > 0 else 150

        cv2.putText(canvas, f"skill_{i+1}  CD={cd}s", (5, y), FONT, 0.35, (200, 200, 200), 1)
        # 冷却条
        cv2.rectangle(canvas, (5, y + 4), (155, y + 18), (50, 50, 50), -1)
        cv2.rectangle(canvas, (5, y + 4), (5 + bar_w, y + 18), col, -1)
        cv2.rectangle(canvas, (5, y + 4), (155, y + 18), (100, 100, 100), 1)
        txt2 = "READY" if ready else f"{rem:.1f}s"
        cv2.putText(canvas, txt2, (160, y + 15), FONT, 0.35, col, 1)

    cv2.putText(canvas, "Q=退出 1-4=手动 E=开关", (5, 205), FONT, 0.3, (150, 150, 150), 1)

    cv2.imshow("SkillTest", canvas)
    key = cv2.waitKey(100) & 0xFF

    if key == ord('q'): break
    elif key in (ord('1'), ord('2'), ord('3'), ord('4')):
        idx = key - ord('1')
        if skills.use(idx, hwnd):
            print(f"[手动] skill_{idx+1}")
        else:
            print(f"[手动] skill_{idx+1} 冷却中 ({skills.remaining(idx):.1f}s)")
    elif key in (ord('e'), ord('E')):
        skills.enabled = not skills.enabled
        print(f"[开关] 自动释放: {'ON' if skills.enabled else 'OFF'}")

cv2.destroyAllWindows()
