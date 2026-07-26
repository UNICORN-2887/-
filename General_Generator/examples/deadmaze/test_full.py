"""完整集成测试: DeadMaze tracker + framework Pathfinder + Navigator + Controller.

操作: 左键点地图=设起点 → 右键=终点 → Enter=导航 → Esc=停 Q=退
"""
import sys, os, cv2, numpy as np, time

# 加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from game_automator.mapping import Pathfinder
from game_automator.navigation import Navigator
from game_controller import DeadMazeController
from map_tracker import Tracker  # 原版 DeadMaze 追踪器

MAP = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                   "map", "MazonAcademy", "MazonAcademy.jpg")
RCH = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                    "map", "MazonAcademy", "MazonAcademy_reachable.png")

# DeadMaze 原版 8方向
DIR_VECTORS = [
    ( 0,-1, 'W'),( 1,-1, 'W','D'),( 1, 0, 'D'),( 1, 1, 'S','D'),
    ( 0, 1, 'S'),(-1, 1, 'S','A'),(-1, 0, 'A'),(-1,-1, 'W','A'),
]

def best_direction(dx, dy):
    best_i, best_dot = 0, -999
    for i, (vx, vy, *_) in enumerate(DIR_VECTORS):
        d = vx*dx + vy*dy
        if d > best_dot: best_dot, best_i = d, i
    return best_i

def main():
    print("[1/3] Pathfinder...")
    pf = Pathfinder(RCH, shrink=80)
    print(f"      grid={pf.grid_size}")

    print("[2/3] Tracker...")
    tracker = Tracker(MAP, camera_id=1)
    print(f"      map={tracker.mw}x{tracker.mh}")

    print("[3/3] Controller...")
    ctrl = DeadMazeController()
    ctrl.find_window()
    print(f"      hwnd={ctrl.target_hwnd:#x}")

    nav = Navigator(pf, waypoint_reach=25, lookahead=90)

    map_img = cv2.imread(MAP)
    mh, mw = map_img.shape[:2]
    scale_val = min(1200/mw, 800/mh, 1.0)
    dw, dh = int(mw*scale_val), int(mh*scale_val)

    start = goal = None
    navigating = False
    frame_cnt = 0

    def draw():
        disp = cv2.resize(map_img, (dw, dh))
        s2 = scale_val
        if start:
            sx, sy = int(start[0]*s2), int(start[1]*s2)
            cv2.drawMarker(disp, (sx, sy), (0,255,0), cv2.MARKER_CROSS, 15, 2)
        if goal:
            gx, gy = int(goal[0]*s2), int(goal[1]*s2)
            cv2.drawMarker(disp, (gx, gy), (0,0,255), cv2.MARKER_CROSS, 15, 2)
        if nav.path:
            for x, y in nav.path:
                cv2.circle(disp, (int(x*s2), int(y*s2)), 1, (255,0,0), -1)
        if tracker.last_position:
            tx, ty = tracker.last_position
            cv2.circle(disp, (int(tx*s2), int(ty*s2)), 6, (0,255,255), -1)
        return disp

    def on_mouse(event, x, y, flags, param):
        nonlocal start, goal
        mx, my = int(x/scale_val), int(y/scale_val)
        if event == cv2.EVENT_LBUTTONDOWN:
            start = (mx, my)
            tracker.last_position = start
            tracker.prev_frame = None
            tracker.need_click = False
            print(f"[Start] {start}")
        elif event == cv2.EVENT_RBUTTONDOWN:
            goal = (mx, my)
            nav.set_route(start, goal)
            print(f"[Goal] {goal} path={len(nav.path)}pts")

    cv2.namedWindow("FullTest")
    cv2.setMouseCallback("FullTest", on_mouse)
    print("L=Start R=Goal Enter=Go Esc=Stop Q=Quit")

    while True:
        # 追踪
        if tracker.need_click is False or tracker.last_position:
            tracker.track()

        key = cv2.waitKey(30) & 0xFF

        # 导航
        if navigating and not nav.arrived and tracker.last_position:
            pos = tracker.last_position
            action = nav.step(pos)

            if action is None:
                print(f"[Arrived]")
                navigating = False
                continue

            # 方向→按键(原版逻辑)
            tgt = nav.current_waypoint
            dx, dy = tgt[0]-pos[0], tgt[1]-pos[1]
            di = best_direction(dx, dy)
            keys = DIR_VECTORS[di][2:]
            all_vks = {'W':ctrl.VK_W,'A':ctrl.VK_A,'S':ctrl.VK_S,'D':ctrl.VK_D}
            needed = set(keys)

            for name, vk in all_vks.items():
                if name not in needed:
                    try: ctrl.key_up(vk)
                    except: pass
            for k in keys:
                try: ctrl.key_down(getattr(ctrl, f'VK_{k}'))
                except: pass
            time.sleep(0.5)  # DeadMaze MOVE_DURATION default
            for k in keys:
                try: ctrl.key_up(getattr(ctrl, f'VK_{k}'))
                except: pass

            frame_cnt += 1
            if frame_cnt % 10 == 0:
                print(f"[Nav] ({pos[0]},{pos[1]}) → ({tgt[0]},{tgt[1]}) "
                      f"k={keys} {nav._wp_index}/{len(nav.path)}")

        cv2.imshow("FullTest", draw())

        if key == 13 and start and goal:
            navigating = True
            nav.set_route(start, goal)
            print(f"[Go] {len(nav.path)}pts")
        elif key == 27:
            navigating = False; nav.cancel()
            for k in ['W','A','S','D']:
                try: ctrl.key_up(getattr(ctrl, f'VK_{k}'))
                except: pass
        elif key == ord('q'):
            break

    tracker.cap.release(); cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
