"""
通过 DirectShow 设备名精确匹配 OBS 虚拟摄像头
"""

import json
import os
from pygrabber.dshow_graph import FilterGraph


CFG_FILE = os.path.join(os.path.dirname(__file__), "camera_config.json")


def find_obs_camera():
    """查找 OBS Virtual Camera 索引"""

    # 已保存的优先
    if os.path.exists(CFG_FILE):
        with open(CFG_FILE) as f:
            idx = json.load(f).get("obs_cam_id", -1)
        graph = FilterGraph()
        devices = graph.get_input_devices()
        if idx < len(devices) and "obs" in devices[idx].lower():
            return idx

    # 扫描所有设备
    graph = FilterGraph()
    devices = graph.get_input_devices()

    for i, name in enumerate(devices):
        if "obs" in name.lower():
            with open(CFG_FILE, "w") as f:
                json.dump({"obs_cam_id": i}, f)
            print(f"OBS 虚拟摄像头: [{i}] {name}")
            return i

    # 回退: 手动
    print("可用摄像头:")
    for i, name in enumerate(devices):
        print(f"  [{i}] {name}")
    choice = input("OBS 索引: ").strip()
    idx = int(choice) if choice.isdigit() else 0
    with open(CFG_FILE, "w") as f:
        json.dump({"obs_cam_id": idx}, f)
    return idx


if __name__ == "__main__":
    print(f"OBS_CAM_ID = {find_obs_camera()}")
