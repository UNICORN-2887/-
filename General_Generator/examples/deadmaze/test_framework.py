"""DeadMaze 框架测试 - 模拟位置版.

操作:
  左键=起点  右键=终点  Enter=导航  Esc=停止  Q=退出
"""

import sys, os, cv2, numpy as np, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from game_automator.capture import OBSVideoCapture
from game_automator.mapping import Pathfinder
from game_automator.navigation import Navigator
from game_automator.driver import Actions
from examples.deadmaze.driver import DeadMazeDriver

MAP_IMG = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                       "map", "MazonAcademy", "MazonAcademy.jpg")
MAP_RCH = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                        "map", "MazonAcademy", "MazonAcademy_reachable.png")

def main():
    cap = OBSVideoCapture(cam_id=OBSVideoCapture.find_obs() or 1)
    pf = Pathfinder(MAP_RCH, shrink=8)
    driver = DeadMazeDriver()
    nav = Navigator(pf, driver, waypoint_reach=40)

    map_img = cv2.imread(MAP_IMG)
    mh, mw = map_img.shape[:2]
    scale = min(1200/mw, 800/mh, 1.0)
    dw, dh = int(mw*scale), int(mh*scale)

    start = goal = None
    sim_pos = [0, 0]
    navigating = False
    last_action = None
    last_action_time = 0
    frame_cnt = 0

    def draw():
        disp = cv2.resize(map_img, (dw, dh))
        if start:
            sx, sy = int(start[0]*scale), int(start[1]*scale)
            cv2.drawMarker(disp, (sx, sy), (0,255,0), cv2.MARKER_CROSS, 15, 2)
            cv2.putText(disp, "S", (sx+10, sy-5), 0, 0.5, (0,255,0), 2)
        if goal:
            gx, gy = int(goal[0]*scale), int(goal[1]*scale)
            cv2.drawMarker(disp, (gx, gy), (0,0,255), cv2.MARKER_CROSS, 15, 2)
            cv2.putText(disp, "G", (gx+10, gy-5), 0, 0.5, (0,0,255), 2)
        if nav.path:
            for x, y in nav.path:
                cv2.circle(disp, (int(x*scale), int(y*scale)), 1, (255, 0, 0), -1)
            if nav.current_waypoint:
                wx, wy = nav.current_waypoint
                cv2.drawMarker(disp, (int(wx*scale), int(wy*scale)), (0,255,255), cv2.MARKER_CROSS, 10, 2)
        sx, sy = int(sim_pos[0]*scale), int(sim_pos[1]*scale)
        cv2.circle(disp, (sx, sy), 6, (0, 255, 255), -1)
        cv2.putText(disp, f"({sim_pos[0]},{sim_pos[1]})", (sx+8, sy-8), 0, 0.4, (0,255,255), 1)
        return disp

    def on_mouse(event, x, y, flags, param):
        nonlocal start, goal, nav, sim_pos, navigating
        if navigating: return
        mx, my = int(x / scale), int(y / scale)
        if event == cv2.EVENT_LBUTTONDOWN:
            start = (mx, my)
            sim_pos = [mx, my]
            print(f"[Start] {start}")
        elif event == cv2.EVENT_RBUTTONDOWN:
            goal = (mx, my)
            print(f"[Goal] {goal}")
            if start and goal:
                path = nav.set_route(start, goal)
                print(f"[Path] {len(path)} pts")

    cv2.namedWindow("Test")
    cv2.setMouseCallback("Test", on_mouse)

    print("左键=起点 右键=终点 Enter=导航 Esc=停止 Q=退出")

    while True:
        cap.read()  # keep camera alive
        key = cv2.waitKey(30) & 0xFF

        if navigating and not nav.arrived:
            frame_cnt += 1
            action = nav.step(tuple(sim_pos))

            if action is not None:
                # 每200ms发一次动作，同方向持续按住
                if action != last_action or time.time() - last_action_time > 0.2:
                    driver.execute(action, duration_ms=200)
                    last_action = action
                    last_action_time = time.time()

                # 模拟位移
                d = {Actions.MOVE_N:(0,-30), Actions.MOVE_S:(0,30),
                     Actions.MOVE_W:(-30,0), Actions.MOVE_E:(30,0),
                     Actions.MOVE_NE:(25,-25), Actions.MOVE_NW:(-25,-25),
                     Actions.MOVE_SE:(25,25), Actions.MOVE_SW:(-25,25)}
                dx, dy = d.get(action, (0,0))
                sim_pos[0] += dx
                sim_pos[1] += dy

            if frame_cnt % 20 == 0:
                wp = nav.current_waypoint
                print(f"[Nav] sp=({sim_pos[0]},{sim_pos[1]}) wp=({wp[0] if wp else '?'},{wp[1] if wp else '?'}) "
                      f"a={action.name if action else '?'} {nav._wp_index}/{len(nav.path)}")

            if nav.arrived:
                print(f"[Arrived!] ({sim_pos[0]},{sim_pos[1]})")
                navigating = False
                driver.release_all()

        cv2.imshow("Test", draw())

        if key == 13 and start and goal:  # Enter
            navigating = True
            nav.set_route(start, goal)
            sim_pos = [start[0], start[1]]
            print(f"[Go!] {len(nav.path)}pts")
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
