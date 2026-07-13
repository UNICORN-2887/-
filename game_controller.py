"""
DeadMaze - 后台游戏操控模块
通过 AttachThreadInput + WM_ACTIVATE 伪装窗口激活，
实现完全不抢前台的键盘鼠标操控。
"""

import re
import time
import ctypes

import win32gui
import win32api
import win32con
import win32process


MapVirtualKeyW = ctypes.windll.user32.MapVirtualKeyW


class DeadMazeController:
    """DeadMaze 后台操控器"""

    def __init__(self):
        self.hwnd = None
        self.target_hwnd = None  # 实际发送消息的窗口（子窗口或顶级）
        self.tid = None
        self._attached = False

    # ================================================================
    # 窗口管理
    # ================================================================
    def find_window(self):
        """查找 DeadMaze 窗口并选最大子窗口为目标"""
        results = []
        pattern = re.compile(r'dead[\s]*maze', re.IGNORECASE)
        exclude = re.compile(
            r'visual studio|vscode|截图采集', re.IGNORECASE
        )

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
            raise RuntimeError("未找到 DeadMaze 游戏窗口！")

        self.hwnd, title, rect = results[0]
        self.tid, pid = win32process.GetWindowThreadProcessId(self.hwnd)
        w, h = rect[2] - rect[0], rect[3] - rect[1]

        # 找最大子窗口（通常是渲染区域）
        self.target_hwnd = self.hwnd
        children = []
        win32gui.EnumChildWindows(self.hwnd, lambda h, _: children.append(h), None)
        if children:
            biggest = max(
                children,
                key=lambda h: (
                    lambda r: (r[2] - r[0]) * (r[3] - r[1])
                )(win32gui.GetWindowRect(h))
            )
            self.target_hwnd = biggest

        print(f"[Controller] 已连接: \"{title}\"")
        print(f"  顶级窗口: 0x{self.hwnd:08X}")
        print(f"  目标窗口: 0x{self.target_hwnd:08X}")
        print(f"  分辨率: {w}x{h}  PID: {pid}")
        return w, h

    # ================================================================
    # 伪装激活
    # ================================================================
    def _attach(self):
        """挂载输入线程（让消息能路由到游戏）"""
        if self._attached:
            return
        current_tid = win32api.GetCurrentThreadId()
        win32process.AttachThreadInput(current_tid, self.tid, True)
        self._attached = True

    def _detach(self):
        """解除挂载"""
        if not self._attached:
            return
        try:
            current_tid = win32api.GetCurrentThreadId()
            win32process.AttachThreadInput(current_tid, self.tid, False)
        except Exception:
            pass
        self._attached = False

    def activate(self):
        """伪装窗口激活（让游戏以为自己在前台）"""
        self._attach()
        h = self.hwnd
        win32gui.PostMessage(h, win32con.WM_ACTIVATEAPP, 1, self.tid)
        win32gui.PostMessage(h, win32con.WM_ACTIVATE, 1, 0)
        win32gui.PostMessage(h, win32con.WM_SETFOCUS, 0, 0)
        win32gui.PostMessage(h, win32con.WM_NCACTIVATE, 1, 0)
        time.sleep(0.02)

    def deactivate(self):
        """恢复"""
        h = self.hwnd
        win32gui.PostMessage(h, win32con.WM_ACTIVATEAPP, 0, self.tid)
        win32gui.PostMessage(h, win32con.WM_ACTIVATE, 0, 0)
        win32gui.PostMessage(h, win32con.WM_KILLFOCUS, 0, 0)
        win32gui.PostMessage(h, win32con.WM_NCACTIVATE, 0, 0)
        self._detach()

    # ================================================================
    # 按键
    # ================================================================

    # 虚拟键码常量
    VK_W = ord('W')
    VK_A = ord('A')
    VK_S = ord('S')
    VK_D = ord('D')
    VK_E = ord('E')
    VK_F = ord('F')
    VK_R = ord('R')
    VK_SPACE = win32con.VK_SPACE
    VK_TAB = win32con.VK_TAB
    VK_ESC = win32con.VK_ESCAPE
    VK_1 = ord('1')
    VK_2 = ord('2')
    VK_3 = ord('3')
    VK_M = ord('M')

    @staticmethod
    def _make_lparam(vk_code, is_up=False):
        scan = MapVirtualKeyW(vk_code, 0)
        lp = 1
        lp |= (scan & 0xFF) << 16
        if is_up:
            lp |= 1 << 31
        return lp

    def press(self, vk_code, hold_time=0.1):
        """按一下某个键（按下→等待→释放）"""
        target = self.target_hwnd
        lp_down = self._make_lparam(vk_code)
        lp_up = self._make_lparam(vk_code, is_up=True)

        self.activate()
        win32gui.PostMessage(target, win32con.WM_KEYDOWN, vk_code, lp_down)
        time.sleep(hold_time)
        win32gui.PostMessage(target, win32con.WM_KEYUP, vk_code, lp_up)
        time.sleep(0.02)

    def key_down(self, vk_code):
        """按下键（不释放，用于持续移动）"""
        target = self.target_hwnd
        lp_down = self._make_lparam(vk_code)
        self.activate()
        win32gui.PostMessage(target, win32con.WM_KEYDOWN, vk_code, lp_down)

    def key_up(self, vk_code):
        """释放键"""
        target = self.target_hwnd
        lp_up = self._make_lparam(vk_code, is_up=True)
        win32gui.PostMessage(target, win32con.WM_KEYUP, vk_code, lp_up)

    def hold(self, vk_code, duration):
        """按住键一段时间（持续移动，如前进0.5秒）"""
        self.key_down(vk_code)
        time.sleep(duration)
        self.key_up(vk_code)

    # ================================================================
    # 鼠标点击
    # ================================================================
    def click(self, x, y):
        """在游戏窗口坐标系 (x, y) 处点击"""
        target = self.target_hwnd
        lparam = (y << 16) | x

        self.activate()
        win32gui.PostMessage(
            target, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam
        )
        time.sleep(0.05)
        win32gui.PostMessage(
            target, win32con.WM_LBUTTONUP, 0, lparam
        )
        time.sleep(0.02)

    def right_click(self, x, y):
        """右键点击"""
        target = self.target_hwnd
        lparam = (y << 16) | x

        self.activate()
        win32gui.PostMessage(
            target, win32con.WM_RBUTTONDOWN, win32con.MK_RBUTTON, lparam
        )
        time.sleep(0.05)
        win32gui.PostMessage(
            target, win32con.WM_RBUTTONUP, 0, lparam
        )
        time.sleep(0.02)

    # ================================================================
    # 移动方法
    # ================================================================
    def move(self, direction, duration=0.3):
        """向指定方向移动
        direction: 'up' | 'down' | 'left' | 'right'
        """
        vk_map = {
            'up': self.VK_W,
            'down': self.VK_S,
            'left': self.VK_A,
            'right': self.VK_D,
        }
        vk = vk_map.get(direction)
        if vk:
            self.press(vk, duration)


# ================================================================
# 快速测试
# ================================================================
if __name__ == "__main__":
    print("DeadMaze 后台操控模块 - 快速测试")
    print("=" * 50)

    ctrl = DeadMazeController()
    ctrl.find_window()

    print("\n测试: W 键移动 0.3s...")
    ctrl.press(ctrl.VK_W, 0.3)

    print("测试: 鼠标点击 (1250, 1300)...")
    ctrl.click(1250, 1300)

    print("测试完成！")
