"""画面采集源: OBS虚拟摄像头 / 屏幕截取 / ADB模拟器.

所有采集源实现统一的 read() -> np.ndarray 接口.
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple, List
import time

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


# ── 抽象基类 ──────────────────────────────────
class CaptureSource(ABC):
    """画面采集抽象基类."""

    @abstractmethod
    def read(self) -> Optional[np.ndarray]:
        """返回当前帧 (BGR, H×W×3), 失败返回 None."""
        ...

    @abstractmethod
    def resolution(self) -> Tuple[int, int]:
        """返回 (width, height)."""
        ...

    def release(self) -> None:
        """释放资源."""
        pass

    def warmup(self, n: int = 10) -> None:
        """预热: 读 n 帧丢弃 (让摄像头稳定)."""
        for _ in range(n):
            self.read()


# ── OBS 虚拟摄像头 ────────────────────────────
class OBSVideoCapture(CaptureSource):
    """通过 OBS 虚拟摄像头采集 (推荐方案)."""

    def __init__(self, cam_id: int = 0, width: int = 1920, height: int = 1080):
        if not HAS_CV2:
            raise ImportError("opencv-python 未安装")
        self._cam_id = cam_id
        self._w, self._h = width, height
        self._cap = None
        self._open()

    def _open(self):
        self._cap = cv2.VideoCapture(self._cam_id, cv2.CAP_DSHOW)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._w)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._h)

    def read(self) -> Optional[np.ndarray]:
        if self._cap is None:
            return None
        ret, frame = self._cap.read()
        return frame if ret else None

    def resolution(self) -> Tuple[int, int]:
        return (self._w, self._h)

    def release(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None

    @staticmethod
    def list_cameras() -> List[Tuple[int, str]]:
        """枚举所有可用摄像头."""
        result = []
        try:
            from pygrabber.dshow_graph import FilterGraph
            for i, name in enumerate(FilterGraph().get_input_devices()):
                result.append((i, name))
        except Exception:
            if HAS_CV2:
                for i in range(5):
                    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                    if cap.isOpened():
                        result.append((i, f"Camera {i}"))
                        cap.release()
        return result

    @staticmethod
    def find_obs() -> Optional[int]:
        """自动查找 OBS 虚拟摄像头 ID, 找不到返回 None."""
        for idx, name in OBSVideoCapture.list_cameras():
            if "obs" in name.lower():
                return idx
        return None


# ── MSS 屏幕截取 ─────────────────────────────
class MSSScreenCapture(CaptureSource):
    """通过 mss 截屏 (需要游戏窗口可见)."""

    def __init__(self, monitor: int = 1, region: Optional[dict] = None):
        import mss
        self._sct = mss.mss()
        self._mon = monitor
        self._region = region  # {"top":0,"left":0,"width":1920,"height":1080}

    def read(self) -> Optional[np.ndarray]:
        img = self._sct.grab(self._region or self._sct.monitors[self._mon])
        return np.array(img)[:, :, :3]  # BGRA -> BGR

    def resolution(self) -> Tuple[int, int]:
        r = self._region or self._sct.monitors[self._mon]
        return (r["width"], r["height"])

    def release(self) -> None:
        self._sct.close()


# ── ADB 模拟器截图 ───────────────────────────
class ADBVideoCapture(CaptureSource):
    """通过 ADB 从 MuMu/雷电等模拟器截图 + 推送到本地."""

    def __init__(self, device: str = "127.0.0.1:5555",
                 adb_path: str = "adb",
                 tmpfile: str = "/sdcard/_automator_frame.png"):
        import subprocess
        self._adb = adb_path
        self._dev = device
        self._tmp = tmpfile

    def read(self) -> Optional[np.ndarray]:
        if not HAS_CV2:
            return None
        import subprocess
        dev_arg = ["-s", self._dev] if self._dev else []
        subprocess.run([self._adb] + dev_arg +
                       ["shell", "screencap", "-p", self._tmp],
                       capture_output=True, timeout=5)
        result = subprocess.run([self._adb] + dev_arg +
                                ["pull", self._tmp, "-"],
                                capture_output=True, timeout=5)
        if result.returncode != 0:
            return None
        arr = np.frombuffer(result.stdout, np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    def resolution(self) -> Tuple[int, int]:
        frame = self.read()
        if frame is not None:
            return (frame.shape[1], frame.shape[0])
        return (1920, 1080)
