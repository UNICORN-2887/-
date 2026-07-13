"""
DeadMaze - 后台操控测试 v3
尝试：子窗口发送消息、伪装窗口激活
"""

import re
import sys
import time
import ctypes

import win32gui
import win32api
import win32con
import win32process

MapVirtualKeyW = ctypes.windll.user32.MapVirtualKeyW


def find_deadmaze_window():
    results = []
    pattern = re.compile(r'dead[\s]*maze', re.IGNORECASE)
    exclude = re.compile(r'visual studio|vscode|截图采集', re.IGNORECASE)

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if pattern.search(title) and not exclude.search(title):
                rect = win32gui.GetWindowRect(hwnd)
                w, h = rect[2] - rect[0], rect[3] - rect[1]
                if 800 <= w <= 2560 and 600 <= h <= 1440:
                    results.append((hwnd, title, rect))
    win32gui.EnumWindows(cb, None)

    if not results:
        print("[错误] 未找到 DeadMaze 游戏窗口！")
        sys.exit(1)
    if len(results) > 1:
        for i, (hwnd, title, rect) in enumerate(results):
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            print(f"  [{i}] 0x{hwnd:08X} \"{title}\" ({w}x{h})")
        c = input(f"选 (0-{len(results)-1}): ").strip()
        try:
            return results[int(c)]
        except (ValueError, IndexError):
            return results[0]
    return results[0]


def enum_child_windows(hwnd):
    """遍历所有子窗口"""
    children = []

    def cb(child_hwnd, _):
        cls = win32gui.GetClassName(child_hwnd)
        title = win32gui.GetWindowText(child_hwnd)
        rect = win32gui.GetWindowRect(child_hwnd)
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        children.append((child_hwnd, cls, title, w, h))

    win32gui.EnumChildWindows(hwnd, cb, None)
    return children


def make_lparam(vk_code, is_up=False):
    scan = MapVirtualKeyW(vk_code, 0)
    lp = 1  # repeat count
    lp |= (scan & 0xFF) << 16
    if is_up:
        lp |= 1 << 31
    return lp


def send_key(hwnd, vk, hold=0.15):
    """SendMessage + 扫描码"""
    lp_down = make_lparam(vk)
    lp_up = make_lparam(vk, is_up=True)
    win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, lp_down)
    time.sleep(hold)
    win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk, lp_up)
    time.sleep(0.03)


def activate_window(hwnd):
    """伪装窗口激活（告诉游戏它被激活了）"""
    tid = win32process.GetWindowThreadProcessId(hwnd)[0]
    current_tid = win32api.GetCurrentThreadId()
    # Attach 输入线程（让消息可以正常路由）
    win32process.AttachThreadInput(current_tid, tid, True)
    # 发送激活消息
    win32gui.PostMessage(hwnd, win32con.WM_ACTIVATEAPP, 1, tid)
    win32gui.PostMessage(hwnd, win32con.WM_ACTIVATE, 1, 0)
    win32gui.PostMessage(hwnd, win32con.WM_SETFOCUS, 0, 0)
    win32gui.PostMessage(hwnd, win32con.WM_NCACTIVATE, 1, 0)
    time.sleep(0.05)


def deactivate_window(hwnd):
    """恢复"""
    tid = win32process.GetWindowThreadProcessId(hwnd)[0]
    win32gui.PostMessage(hwnd, win32con.WM_ACTIVATEAPP, 0, tid)
    win32gui.PostMessage(hwnd, win32con.WM_ACTIVATE, 0, 0)
    win32gui.PostMessage(hwnd, win32con.WM_KILLFOCUS, 0, 0)
    win32gui.PostMessage(hwnd, win32con.WM_NCACTIVATE, 0, 0)
    try:
        win32process.AttachThreadInput(
            win32api.GetCurrentThreadId(), tid, False
        )
    except Exception:
        pass


def run_tests(top_hwnd):
    vk = ord('W')
    hold = 0.25

    # ---- 遍历子窗口 ----
    print(f"\n{'='*60}")
    print("子窗口结构：")
    children = enum_child_windows(top_hwnd)
    for hwnd, cls, title, w, h in children:
        print(f"  0x{hwnd:08X} [{cls}] \"{title}\" ({w}x{h})")

    # 找最大的子窗口（通常是渲染区域）
    target = top_hwnd
    if children:
        biggest = max(children, key=lambda c: c[3] * c[4])
        target = biggest[0]
        print(f"\n  → 选最大子窗口为目标: 0x{target:08X}")

    # ---- 测试 ----
    print(f"\n{'='*60}")
    print(f"测试方案（按住 {hold}s）")
    print(f"{'='*60}")

    # 测试1: 直接向顶级窗口发送
    input("\n1. 直接发送到顶级窗口 → Enter")
    send_key(top_hwnd, vk, hold)
    print("   完成。")

    # 测试2: 向子窗口发送
    input("\n2. 发送到子窗口 → Enter")
    send_key(target, vk, hold)
    print("   完成。")

    # 测试3: 先伪装激活 → 再向顶级窗口发
    input("\n3. 伪装激活 + 顶级窗口 → Enter")
    activate_window(top_hwnd)
    send_key(top_hwnd, vk, hold)
    deactivate_window(top_hwnd)
    print("   完成。")

    # 测试4: 伪装激活 → 子窗口
    input("\n4. 伪装激活 + 子窗口 → Enter")
    activate_window(top_hwnd)
    send_key(target, vk, hold)
    deactivate_window(top_hwnd)
    print("   完成。")

    # 测试5: SendInput 对照（影响前台）
    print(f"\n{'='*60}")
    print("5. SendInput 对照（会抢你键盘！准备好）")
    input("→ Enter")
    scan = MapVirtualKeyW(vk, 0)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT_U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", ctypes.c_char * 32)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("u", INPUT_U)]

    down = INPUT()
    down.type = 1
    down.u.ki.wVk = vk
    down.u.ki.wScan = scan
    down.u.ki.dwFlags = 0

    up = INPUT()
    up.type = 1
    up.u.ki.wVk = vk
    up.u.ki.wScan = scan
    up.u.ki.dwFlags = 0x0002

    user32 = ctypes.windll.user32
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
    time.sleep(hold)
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))
    print("   完成。")

    print(f"\n{'='*60}")
    print("全部完成！反馈哪些有效。")
    print(f"{'='*60}")


if __name__ == "__main__":
    hwnd, title, rect = find_deadmaze_window()
    print(f"✅ \"{title}\" (0x{hwnd:08X})")
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.3)
    run_tests(hwnd)
