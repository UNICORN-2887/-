"""ROI 标定工具.

CalibrationServer 提供与 DeadMaze 标定中心相同的网页界面,
用户通过浏览器拖拽调整 ROI 位置.
"""

from typing import Dict, List, Optional, Callable
import json
import os
import base64
import time

import cv2
import numpy as np

from game_automator.capture import CaptureSource


class CalibrationServer:
    """Flask 标定网页服务.

    Usage:
        cap = OBSVideoCapture()
        calib = CalibrationServer(cap, roi_file="my_rois.json")
        calib.add_roi("exp", 963, 1045, 50, 25, desc="经验值")
        calib.add_roi("hunger", 1714, 1048, 50, 25, desc="饱食度")
        calib.start()
    """

    def __init__(self, capture: CaptureSource,
                 roi_file: Optional[str] = None):
        from flask import Flask, render_template_string, request, jsonify
        self._cap = capture
        self._roi_file = roi_file
        self._rois: Dict[str, dict] = {}  # name -> {x,y,w,h,desc}
        self._app = Flask(__name__)

        @self._app.route("/api/rois")
        def get_rois():
            return jsonify(self._rois)

        @self._app.route("/api/save", methods=["POST"])
        def save():
            data = request.get_json() or {}
            # data: {"name": [x,y,w,h], ...}
            for name, coords in data.items():
                if name in self._rois and len(coords) >= 4:
                    self._rois[name]["x"] = coords[0]
                    self._rois[name]["y"] = coords[1]
                    self._rois[name]["w"] = coords[2]
                    self._rois[name]["h"] = coords[3]
            if self._roi_file:
                with open(self._roi_file, "w") as f:
                    json.dump(self._export_dict(), f, indent=2)
            return jsonify({"ok": True})

        @self._app.route("/api/capture", methods=["POST"])
        def capture():
            frame = self._cap.read()
            if frame is None:
                return jsonify({"error": "截取失败"})
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            return jsonify({"ok": True,
                            "image": base64.b64encode(buf).decode(),
                            "shape": list(frame.shape[:2])})

    def add_roi(self, name: str, x: int, y: int,
                w: int, h: int, desc: str = ""):
        self._rois[name] = {"x": x, "y": y, "w": w, "h": h, "desc": desc}

    def _export_dict(self) -> dict:
        out = {}
        for name, r in self._rois.items():
            out[name] = [r["x"], r["y"], r["w"], r["h"], r.get("desc", "")]
        return out

    def load_from_file(self, path: str) -> None:
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            for name, coords in data.items():
                if len(coords) >= 4:
                    self.add_roi(name, *coords[:4],
                                 desc=coords[4] if len(coords) > 4 else "")

    def start(self, port: int = 5050, blocking: bool = True):
        print(f"[Calibration] http://127.0.0.1:{port}/calibrate")
        self._app.run(host="127.0.0.1", port=port,
                       debug=False, use_reloader=False)

    def start_threaded(self, port: int = 5050):
        from threading import Thread
        t = Thread(target=self.start, kwargs={"port": port, "blocking": True},
                   daemon=True)
        t.start()
        return t
