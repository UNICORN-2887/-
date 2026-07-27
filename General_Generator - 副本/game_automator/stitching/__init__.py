"""光流法地图拼接.

基于 ORB 特征匹配 + 光流追踪, 将连续的游戏画面帧拼接为完整大地图.
支持固定画布尺寸和自动扩展模式.
"""

from typing import Optional, Tuple
import numpy as np
import cv2


class MapStitcher:
    """光流法地图拼接器.

    Usage:
        cap = OBSVideoCapture()
        stitcher = MapStitcher(min_movement=25)
        stitcher.add_frame(cap.read())        # 初始帧
        while moving:
            canvas, dx, dy, conf = stitcher.add_frame(cap.read())
        stitcher.save("map.jpg")
    """

    def __init__(self,
                 min_movement: int = 25,
                 canvas_w: Optional[int] = None,
                 canvas_h: Optional[int] = None):
        self.canvas: Optional[np.ndarray] = None
        self.canvas_x = 0
        self.canvas_y = 0
        self.total_dx = 0.0
        self.total_dy = 0.0
        self.frame_count = 0
        self.min_movement = min_movement
        self.canvas_w = canvas_w      # None = 自动扩展
        self.canvas_h = canvas_h

        self._prev_gray = None
        self._prev_color = None
        self._orb = cv2.ORB_create(nfeatures=1500)
        self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

    # ── 核心 ────────────────────────────────────
    def add_frame(self, color_frame: np.ndarray
                  ) -> Tuple[Optional[np.ndarray], float, float, float]:
        """拼接一帧. 返回 (canvas, dx, dy, confidence)."""
        gray = cv2.cvtColor(color_frame, cv2.COLOR_BGR2GRAY)
        h, w = color_frame.shape[:2]

        if self.canvas is None:
            return self._init_canvas(color_frame, gray, h, w)

        dx, dy, conf = self._compute_offset(self._prev_gray, gray)
        movement = np.hypot(dx, dy)
        if movement < self.min_movement or conf < 0.3:
            return self.canvas, dx, dy, conf

        self.total_dx += dx
        self.total_dy += dy
        self._prev_gray, self._prev_color = gray, color_frame
        self.frame_count += 1
        return self._paste_frame(color_frame, gray, int(self.total_dx), int(self.total_dy))

    # ── 内部 ────────────────────────────────────
    def _init_canvas(self, cf, gray, h, w):
        if self.canvas_w and self.canvas_h:
            self.canvas = np.zeros((self.canvas_h, self.canvas_w, 3), dtype=np.uint8)
            px = (self.canvas_w - w) // 2
            py = (self.canvas_h - h) // 2
            self.canvas[py:py+h, px:px+w] = cf
            self.canvas_x, self.canvas_y = -px, -py
        else:
            self.canvas = cf.copy()
            self.canvas_x = self.canvas_y = 0
        self._prev_gray, self._prev_color = gray, cf
        self.frame_count = 1
        return self.canvas, 0.0, 0.0, 0.0

    def _compute_offset(self, prev_gray, curr_gray):
        kp1, des1 = self._orb.detectAndCompute(prev_gray, None)
        kp2, des2 = self._orb.detectAndCompute(curr_gray, None)
        if des1 is None or des2 is None or len(des1) < 10 or len(des2) < 10:
            return 0.0, 0.0, 0.0
        matches = self._matcher.match(des1, des2)
        if len(matches) < 8:
            return 0.0, 0.0, 0.0
        matches = sorted(matches, key=lambda m: m.distance)
        dx_list, dy_list = [], []
        for m in matches[:50]:
            p1 = kp1[m.queryIdx].pt
            p2 = kp2[m.trainIdx].pt
            dx_list.append(p2[0] - p1[0])
            dy_list.append(p2[1] - p1[1])
        dx = np.median(dx_list)
        dy = np.median(dy_list)
        inliers = sum(1 for ddx, ddy in zip(dx_list, dy_list)
                       if abs(ddx - dx) < 5 and abs(ddy - dy) < 5)
        conf = inliers / len(dx_list) if dx_list else 0.0
        return -dx, -dy, conf

    def _paste_frame(self, cf, gray, new_x, new_y):
        h, w = cf.shape[:2]
        ch, cw = self.canvas.shape[:2]
        ocx, ocy = self.canvas_x, self.canvas_y

        if self.canvas_w and self.canvas_h:
            left, top = ocx, ocy
        else:
            left = min(ocx, new_x)
            top = min(ocy, new_y)
            right = max(ocx + cw, new_x + w)
            bottom = max(ocy + ch, new_y + h)
            nw, nh = right - left, bottom - top
            new_canvas = np.zeros((nh, nw, 3), dtype=np.uint8)
            new_canvas[ocy-top:ocy-top+ch, ocx-left:ocx-left+cw] = self.canvas
            self.canvas = new_canvas

        fx = new_x - left
        fy = new_y - top
        sx1, sy1 = max(0, fx), max(0, fy)
        sx2, sy2 = min(cw, fx+w), min(ch, fy+h)
        if sx2 > sx1 and sy2 > sy1:
            _, mask = cv2.threshold(gray, 5, 255, cv2.THRESH_BINARY)
            mask3 = cv2.merge([mask, mask, mask])
            roi = self.canvas[sy1:sy2, sx1:sx2]
            src = cf[sy1-fy:sy2-fy, sx1-fx:sx2-fx]
            msk = mask3[sy1-fy:sy2-fy, sx1-fx:sx2-fx]
            np.copyto(roi, src, where=(msk > 0))

        self.canvas_x, self.canvas_y = left, top
        return self.canvas, 0.0, 0.0, 0.0

    # ── 工具 ────────────────────────────────────
    def save(self, path: str = "map_output.jpg") -> None:
        if self.canvas is not None:
            cv2.imwrite(path, self.canvas)

    def reset(self) -> None:
        self.canvas = None
        self.total_dx = 0.0
        self.total_dy = 0.0
        self.frame_count = 0

    @property
    def size(self) -> Optional[Tuple[int, int]]:
        return self.canvas.shape[1::-1] if self.canvas is not None else None
