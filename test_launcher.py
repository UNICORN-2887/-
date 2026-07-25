"""
启动器测试 — 启动exe + 模拟按键序列
Insert → 2s → Delete → 2s → F1 → 2s → F3 → 2s → F3 → 2s → F3
"""
import subprocess, time, os

EXE_PATH = r"E:\Project\DeadMaze\Dead Maze Steam加速版.exe"

# 模拟按键 (SendInput)
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

VK_CODES = {
    "insert": 0x2D, "delete": 0x2E,
    "f1": 0x70, "f3": 0x72,
}

def press_key(vk_code):
    """按下并释放一个键"""
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]
    class INPUT_U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", ctypes.c_char * 32)]
    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", INPUT_U)]

    down = INPUT(INPUT_KEYBOARD, INPUT_U(ki=KEYBDINPUT(vk_code, 0, 0, 0, None)))
    up = INPUT(INPUT_KEYBOARD, INPUT_U(ki=KEYBDINPUT(vk_code, 0, KEYEVENTF_KEYUP, 0, None)))
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
    time.sleep(0.05)
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))
    time.sleep(0.05)

def run_sequence():
    """执行按键序列"""
    sequence = ["insert", "delete", "f1", "f3", "f3", "f3"]
    for i, key in enumerate(sequence):
        vk = VK_CODES[key]
        print(f"[{i+1}/{len(sequence)}] 按 {key.upper()} ...")
        press_key(vk)
        print(f"       等待2秒...")
        time.sleep(2.0)
    print("序列完成!")

if __name__ == "__main__":
    print("=== 启动器测试 ===")
    print(f"EXE路径: {EXE_PATH}")

    if os.path.exists(EXE_PATH):
        print(f"启动: {EXE_PATH}")
        subprocess.Popen(EXE_PATH, shell=True)
        time.sleep(3.0)  # 等exe启动
        print("exe已启动, 开始按键序列...")
    else:
        print(f"[跳过] 文件不存在: {EXE_PATH}")
        print("直接测试按键序列...")

    run_sequence()
    print("测试完成!")
