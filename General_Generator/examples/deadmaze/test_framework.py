"""DeadMaze 框架集成测试 - 可直接运行验证完整链路.

前提: OBS 虚拟摄像头已启动, DeadMaze 游戏运行中.

操作:
  左键地图 = 设定起点 (角色当前位置)
  右键地图 = 设定终点 → A*规划
  Enter = 开始导航
  Esc = 停止
  Q = 退出
"""

import sys, os, cv2, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from game_automator.capture import OBSVideoCapture
from game_automator.mapping import PositionTracker, Pathfinder
from game_automator.navigation import Navigator, compute_direction
from examples.deadmaze.driver import DeadMazeDriver

MAP_IMG = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                       "map", "MazonAcademy", "MazonAcademy.jpg")
MAP_RCH = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                        "map", "MazonAcademy", "MazonAcademy_reachable.png")


def main():
    # 1. 初始化
    cam_id = OBSVideoCapture.find_obs() or 1
    print(f"[Camera] OBS #{cam_id}")
    cap = OBSVideoCapture(cam_id=cam_id)
    cap.warmup(5)

    pf = Pathfinder(MAP_RCH, shrink=80)
    print(f"[Grid] {pf.grid_size}")

    driver = DeadMazeDriver()
    nav = Navigator(pf, driver)

    map_img = cv2.imread(MAP_IMG)
    if map_img is None:
        print(f"[Error] 地图文件不存在: {MAP_IMG}")
        return

    tracker = None
    start = goal = None
    navigating = False
    scale = 1.0
    disp_w, disp_h = 1200, 800

    def draw_map():
        nonlocal scale, disp_w, disp_h
        # 缩小原图再画标记 (否则全尺寸下标记太小看不见)
        h, w = map_img.shape[:2]
        scale = min(1200/w, 800/h, 1.0)
        disp_w, disp_h = int(w*scale), int(h*scale)
        disp = cv2.resize(map_img, (disp_w, disp_h))
        r = max(1, int(scale))  # 显示缩放比, 用于调标记大小

        if start:
            sx, sy = int(start[0]*scale), int(start[1]*scale)
            cv2.drawMarker(disp, (sx, sy), (0, 255, 0),
                           cv2.MARKER_CROSS, 15, 2)
            cv2.putText(disp, "S", (sx+10, sy-5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        if goal:
            gx, gy = int(goal[0]*scale), int(goal[1]*scale)
            cv2.drawMarker(disp, (gx, gy), (0, 0, 255),
                           cv2.MARKER_CROSS, 15, 2)
            cv2.putText(disp, "G", (gx+10, gy-5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        if navigating and nav.path:
            for x, y in nav.path:
                cv2.circle(disp, (int(x*scale), int(y*scale)),
                           max(1, 2*r), (255, 0, 0), -1)
            if nav.current_waypoint:
                wx, wy = nav.current_waypoint
                cv2.drawMarker(disp, (int(wx*scale), int(wy*scale)),
                               (0, 255, 255), cv2.MARKER_CROSS, 12, 2)
        if tracker:
            tx, ty = tracker.position
            cv2.circle(disp, (int(tx*scale), int(ty*scale)),
                       max(3, 5*r), (0, 255, 255), -1)
            txt = f"pos=({tx},{ty}) c={tracker.confidence:.2f}"
            cv2.putText(disp, txt, (int(tx*scale)+10, int(ty*scale)-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5*r, (0, 255, 255), 1)
        return disp

    def on_mouse(event, x, y, flags, param):
        nonlocal start, goal, navigating, tracker, scale
        if navigating:
            return
        mx = int(x / scale)
        my = int(y / scale)
        if event == cv2.EVENT_LBUTTONDOWN:
            start = (mx, my)
            if tracker:
                tracker.reset_position(start)
            else:
                tracker = PositionTracker(MAP_IMG, start_pos=start)
            frame = cap.read()
            if frame is not None:
                tracker.set_reference(frame)
            print(f"[Start] {start}")
            goal = None
        elif event == cv2.EVENT_RBUTTONDOWN:
            goal = (mx, my)
            print(f"[Goal] {goal}")
            if start and goal:
                path = nav.set_route(start, goal)
                print(f"[Path] {len(path)} points")

    cv2.namedWindow("Integration Test", cv2.WINDOW_NORMAL)
    cv2.setMouseCallback("Integration Test", on_mouse)

    print("\n" + "="*50)
    print("左键=起点 | 右键=终点 | Enter=导航")
    print("Esc=停止 | Q=退出")
    print("="*50 + "\n")

    while True:
        frame = cap.read()
        if frame is None:
            continue

        # 定位更新
        if navigating and tracker:
            pos, conf = tracker.update(frame)
            action = nav.step(pos)
            if action:
                driver.execute(action, duration_ms=150)
            if nav.arrived:
                print("[Arrived!]")
                navigating = False
                driver.release_all()
            if conf < 0.2:
                print("[WARN] 定位丢失, 尝试重定位...")
                ok, c = tracker.relocalize(frame)
                if ok:
                    print(f"[OK] 重定位成功 c={c:.2f}")
                else:
                    print(f"[FAIL] 重定位失败 c={c:.2f}")

        canvas = draw_map()
        cv2.imshow("Integration Test", canvas)
        key = cv2.waitKey(1) & 0xFF

        if key == 13:  # Enter - 开始导航
            if start and goal:
                navigating = True
                nav.set_route(start, goal)
                print("[Navigate] Start!")
        elif key == 27:  # Esc
            navigating = False
            driver.release_all()
            print("[Stop]")
        elif key == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
