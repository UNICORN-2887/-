"""
启动器测试 — 任务计划程序跳过UAC + 模拟按键序列
"""
import subprocess, time, os, ctypes
from ctypes import wintypes

EXE_PATH = r"E:\Project\DeadMaze\Dead Maze Steam加速版.exe"
TASK_NAME = "DeadMazeLauncher"

user32 = ctypes.windll.user32
VK_CODES = {"insert": 0x2D, "delete": 0x2E, "f1": 0x70, "f3": 0x72}

def press_key(vk_code):
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]
    class INPUT_U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", ctypes.c_char * 32)]
    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", INPUT_U)]
    down = INPUT(1, INPUT_U(ki=KEYBDINPUT(vk_code, 0, 0, 0, None)))
    up = INPUT(1, INPUT_U(ki=KEYBDINPUT(vk_code, 0, 2, 0, None)))
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
    time.sleep(0.05)
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))

def launch_no_uac(exe_path):
    """通过注册表设RunAsAdmin + 直接启动"""
    if not os.path.exists(exe_path):
        print(f"[跳过] 文件不存在: {exe_path}")
        return False
    try:
        # 设置兼容性标志: 始终以管理员运行 (一次设置, 永久生效)
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers",
            0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, exe_path, 0, winreg.REG_SZ, "RUNASADMIN")
        winreg.CloseKey(key)
        print("[注册表] 已设RunAsAdmin")
    except Exception as e:
        print(f"[注册表] 设置失败: {e} (可能需要管理员权限)")

    # 直接启动exe
    subprocess.Popen(exe_path, shell=True)
    print(f"[启动] {exe_path}")
    time.sleep(3.0)
    return True

def run_sequence():
    sequence = ["insert", "delete", "f1", "f3", "f3", "f3"]
    for i, key in enumerate(sequence):
        vk = VK_CODES[key]
        print(f"[{i+1}/{len(sequence)}] 按 {key.upper()} ...")
        press_key(vk)
        print(f"       等待2秒...")
        time.sleep(2.0)
    print("序列完成!")

if __name__ == "__main__":
    print("=== 启动器测试 (注册表RunAsAdmin) ===")
    print(f"EXE: {EXE_PATH}")
    launch_no_uac(EXE_PATH)
    run_sequence()
    print("测试完成!")
