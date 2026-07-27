"""DeadMaze 使用 game_automator 框架的示例.

展示完整流程: 采集 → 建图 → 标定 → 寻路 → 导航.
"""

import sys
sys.path.insert(0, "..")  # 开发模式下导入本地 game_automator

from game_automator.capture import OBSVideoCapture
from game_automator.stitching import MapStitcher
from game_automator.mapping import Pathfinder, ReachabilityEditor
from game_automator.navigation import Navigator
from game_automator.calibration import CalibrationServer
from game_automator.driver import Actions
from examples.deadmaze.driver import DeadMazeDriver
import cv2
import numpy as np


def example_stitch():
    """示例 1: 光流法建图."""
    cam_id = OBSVideoCapture.find_obs() or 1
    cap = OBSVideoCapture(cam_id=cam_id)
    cap.warmup(10)
    stitcher = MapStitcher(min_movement=25)

    print("A=自动 C=手动 S=保存 Q=退出")
    auto = False
    while True:
        frame = cap.read()
        if frame is None:
            continue
        if auto:
            stitcher.add_frame(frame)

        disp = stitcher.canvas or frame
        h, w = disp.shape[:2]
        scale = min(900/w, 900/h, 1.0)
        if scale < 1.0:
            disp = cv2.resize(disp, (int(w*scale), int(h*scale)))
        cv2.imshow("stitch", disp)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('a'):
            auto = not auto
        elif key == ord('c'):
            stitcher.add_frame(frame)
        elif key == ord('s'):
            stitcher.save("map_output.jpg")
    cap.release()
    cv2.destroyAllWindows()


def example_calibrate():
    """示例 2: ROI 标定."""
    cam_id = OBSVideoCapture.find_obs() or 1
    cap = OBSVideoCapture(cam_id=cam_id)
    calib = CalibrationServer(cap, roi_file="my_rois.json")
    # 添加需要标定的区域
    calib.add_roi("exp", 963, 1045, 50, 25, "经验值")
    calib.add_roi("hunger", 1714, 1048, 50, 25, "饱食度")
    calib.add_roi("thirst", 1631, 1047, 50, 25, "口渴度")
    calib.add_roi("stamina", 1552, 1047, 50, 25, "体力值")
    calib.add_roi("threat", 875, 1045, 50, 25, "威胁值")
    calib.add_roi("open", 968, 337, 40, 30, "火堆开字")
    calib.start()


def example_navigate():
    """示例 3: 导航 + 驱动."""
    # 1. 初始化
    pf = Pathfinder("map/MazonAcademy/MazonAcademy_reachable.png")
    driver = DeadMazeDriver()
    nav = Navigator(pf, driver)

    # 2. 规划
    start = (5000, 6000)
    goal = (8000, 4000)
    path = nav.set_route(start, goal)
    print(f"路径: {len(path)} 个点")

    # 3. 导航循环 (需要定位回调)
    # while not nav.arrived:
    #     pos = get_player_position()  # 你的定位实现
    #     action = nav.step(pos)
    #     if action:
    #         driver.execute(action)


if __name__ == "__main__":
    print("game-automator + DeadMaze 集成示例")
    print("1. python main.py stitch     # 建图")
    print("2. python main.py calibrate  # 标定")
    print("3. python main.py navigate   # 导航")
