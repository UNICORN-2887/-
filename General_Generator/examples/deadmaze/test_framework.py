"""光流追踪 + 导航测试."""
import sys, os, cv2, numpy as np, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from game_automator.capture import OBSVideoCapture
from game_automator.mapping import Pathfinder, PositionTracker
from game_automator.navigation import Navigator, compute_direction

# 直接用 DeadMaze 原版后台操控 (SendMessage WM_KEYDOWN)
import sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from game_controller import DeadMazeController

MAP_IMG = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                       "map", "MazonAcademy", "MazonAcademy.jpg")
MAP_RCH = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                        "map", "MazonAcademy", "MazonAcademy_reachable.png")

def main():
    cap = OBSVideoCapture(cam_id=OBSVideoCapture.find_obs() or 1)
    pf = Pathfinder(MAP_RCH, shrink=8)
    nav = Navigator(pf, waypoint_reach=40)

    # 用原版 DeadMazeController (SendMessage 后台操控)
    ctrl = DeadMazeController()
    ctrl.find_window()
    print(f"[Ctrl] {ctrl.target_hwnd:#x}")

    # 方向 → 按键映射 (同名 DeadMaze DIR_VECTORS)
    DIR_KEYS = {
        0: ['W'], 1: ['W','D'], 2: ['D'], 3: ['S','D'],
        4: ['S'], 5: ['S','A'], 6: ['A'], 7: ['W','A'],
    }
    # 8方向向量 (同原版 best_direction)
    DIR_VEC = [
        ( 0,-1),( 1,-1),( 1, 0),( 1, 1),
        ( 0, 1),(-1, 1),(-1, 0),(-1,-1),
    ]

    def best_dir(dx, dy):
        best_i, best_dot = 0, -999
        for i, (vx, vy) in enumerate(DIR_VEC):
            d = vx*dx + vy*dy
            if d > best_dot: best_dot, best_i = d, i
        return best_i

    def move_keys(dx, dy):
        """发送方向键 (同原版 _move_8dir)."""
        i = best_dir(dx, dy)
        keys = DIR_KEYS[i]
        vks = [getattr(ctrl, f'VK_{k}', ord(k)) for k in keys]
        for vk in vks:
            try: ctrl.key_down(vk)
            except: pass
        time.sleep(0.2)
        for vk in vks:
            try: ctrl.key_up(vk)
            except: pass
    map_img = cv2.imread(MAP_IMG)
    mh, mw = map_img.shape[:2]
    scale = min(1200/mw, 800/mh, 1.0)
    dw, dh = int(mw*scale), int(mh*scale)

    start = goal = None
    navigating = False
    tracker = None
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
        if tracker:
            tx, ty = tracker.position
            sx, sy = int(tx*scale), int(ty*scale)
            cv2.circle(disp, (sx, sy), 6, (0, 255, 255), -1)
            cv2.putText(disp, f"({tx},{ty}) c={tracker.confidence:.2f}", (sx+8, sy-8), 0, 0.4, (0,255,255), 1)
        return disp

    def on_mouse(event, x, y, flags, param):
        nonlocal start, goal, nav, tracker
        if navigating: return
        mx, my = int(x / scale), int(y / scale)
        if event == cv2.EVENT_LBUTTONDOWN:
            start = (mx, my)
            tracker = PositionTracker(MAP_IMG, start_pos=start, crop=(160, 60, 1600, 960))
            frame = cap.read()
            if frame is not None: tracker.init_tracking(frame)
            print(f"[Start] {start}")
        elif event == cv2.EVENT_RBUTTONDOWN:
            goal = (mx, my)
            print(f"[Goal] {goal}")
            if start and goal:
                path = nav.set_route(start, goal)
                print(f"[Path] {len(path)} pts")

    cv2.namedWindow("Test")
    cv2.setMouseCallback("Test", on_mouse)
    print("Left=Start Right=Goal Enter=Go Esc=Stop Q=Quit")

    while True:
        frame = cap.read()
        cv2.imshow("Test", draw())
        key = cv2.waitKey(30) & 0xFF

        if navigating and not nav.arrived:
            frame_cnt += 1
            # 光流追踪位置
            if tracker:
                pos, conf = tracker.update(frame)
            else:
                pos = start or (0, 0)

            # 跳过已到达的路标
            while nav._wp_index < len(nav.path):
                tgt = nav.path[nav._wp_index]
                if np.hypot(pos[0]-tgt[0], pos[1]-tgt[1]) < 40:
                    nav._wp_index += 1
                else:
                    break

            if nav._wp_index >= len(nav.path):
                nav.arrived = True
            else:
                tgt = nav.path[nav._wp_index]
                dx, dy = tgt[0]-pos[0], tgt[1]-pos[1]
                move_keys(dx, dy)

            if frame_cnt % 10 == 0:
                tgt = nav.path[nav._wp_index] if nav._wp_index < len(nav.path) else pos
                print(f"[Nav] pos=({pos[0]},{pos[1]}) tgt=({tgt[0]},{tgt[1]}) "
                      f"dx={tgt[0]-pos[0]} dy={tgt[1]-pos[1]} wp={nav._wp_index}/{len(nav.path)}")

            if nav.arrived:
                print(f"[Arrived!] ({pos[0]},{pos[1]})")
                navigating = False

        if key == 13 and start and goal:
            navigating = True
            nav._wp_index = 0
            print(f"[Go!] {len(nav.path)}pts")
        elif key == 27:
            navigating = False; print("[Stop]")
        elif key == ord('q'):
            break

    cap.release(); cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
