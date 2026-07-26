"""DeadMaze 底层驱动实现 — 对接 game_automator.

展示如何继承 AbstractDriver 将框架标准动作映射到 DeadMaze 游戏按键.
"""

import time
import ctypes
from ctypes import wintypes

from game_automator.driver import AbstractDriver, Actions

# ── Win32 虚拟键码 ──────────────────────────
VK = {
    "W": 0x57, "S": 0x53, "A": 0x41, "D": 0x44,
    "SPACE": 0x20, "E": 0x45, "F": 0x46,
    "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
}

user32 = ctypes.windll.user32


def _send_combo(vk1, vk2, duration_ms):
    """同时按住两个键 (对角线移动)."""
    class KI(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]
    class IU(ctypes.Union):
        _fields_ = [("ki", KI), ("mi", ctypes.c_char * 32)]
    class INP(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", IU)]
    d1 = INP(1, IU(ki=KI(vk1, 0, 0, 0, None)))
    d2 = INP(1, IU(ki=KI(vk2, 0, 0, 0, None)))
    u1 = INP(1, IU(ki=KI(vk1, 0, 2, 0, None)))
    u2 = INP(1, IU(ki=KI(vk2, 0, 2, 0, None)))
    user32.SendInput(1, ctypes.byref(d1), ctypes.sizeof(INP))
    user32.SendInput(1, ctypes.byref(d2), ctypes.sizeof(INP))
    time.sleep(duration_ms / 1000.0)
    user32.SendInput(1, ctypes.byref(u1), ctypes.sizeof(INP))
    user32.SendInput(1, ctypes.byref(u2), ctypes.sizeof(INP))

def _send_key(vk_code, duration_ms):
    """SendInput 发送按键 (持续时间 ms)."""
    class KI(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]
    class IU(ctypes.Union):
        _fields_ = [("ki", KI), ("mi", ctypes.c_char * 32)]
    class INP(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", IU)]
    down = INP(1, IU(ki=KI(vk_code, 0, 0, 0, None)))
    up = INP(1, IU(ki=KI(vk_code, 0, 2, 0, None)))
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INP))
    time.sleep(duration_ms / 1000.0)
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INP))


class DeadMazeDriver(AbstractDriver):
    """DeadMaze 游戏驱动: 标准动作 → 键盘 SendInput."""

    def execute(self, action: Actions, duration_ms: int = 100) -> None:
        keys = self._map_action(action)
        if not keys:
            return
        if isinstance(keys, tuple):
            # 对角线: 同时按两个键
            _send_combo(keys[0], keys[1], duration_ms)
        else:
            _send_key(keys, duration_ms)

    def release_all(self) -> None:
        pass  # SendInput 自动释放

    def click(self, x: int, y: int) -> None:
        # DeadMaze 点击: 需要后台操作, 这里留空 (让用户自己实现)
        pass

    @staticmethod
    def _map_action(action: Actions):
        """映射标准动作到 DeadMaze 按键."""
        mapping = {
            Actions.MOVE_N:  VK["W"],
            Actions.MOVE_S:  VK["S"],
            Actions.MOVE_W:  VK["A"],
            Actions.MOVE_E:  VK["D"],
            Actions.MOVE_NE: (VK["W"], VK["D"]),
            Actions.MOVE_NW: (VK["W"], VK["A"]),
            Actions.MOVE_SE: (VK["S"], VK["D"]),
            Actions.MOVE_SW: (VK["S"], VK["A"]),
            Actions.ATTACK:  0x01,   # 左键
            Actions.DASH:    VK["SPACE"],
            Actions.SKILL_1: VK["1"],
            Actions.SKILL_2: VK["2"],
            Actions.SKILL_3: VK["3"],
            Actions.SKILL_4: VK["4"],
            Actions.INTERACT: VK["F"],
        }
        return mapping.get(action)
