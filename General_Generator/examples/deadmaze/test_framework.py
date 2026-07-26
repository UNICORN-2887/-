"""框架路径+原版操控 集成测试.
复制原版 navigator 的导航逻辑: tracker.track() + best_direction + WM_KEYDOWN.
"""
import sys, os, cv2, numpy as np, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from game_automator.capture import OBSVideoCapture
from game_automator.mapping import Pathfinder
from game_automator.navigation import Navigator
from game_controller import DeadMazeController

MAP_IMG = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                       "map", "MazonAcademy", "MazonAcademy.jpg")
MAP_RCH = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                        "map", "MazonAcademy", "MazonAcademy_reachable.png")

# 原版 8方向 + 按键映射
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
    cap = OBSVideoCapture(cam_id=OBSVideoCapture.find_obs() or 1)
    pf = Pathfinder(MAP_RCH, shrink=8)  # DeadMaze pathfinder.py 默认
    map_img = cv2.imread(MAP_IMG)
    mh, mw = map_img.shape[:2]
    scale = min(1200/mw, 800/mh, 1.0)
    dw, dh = int(mw*scale), int(mh*scale)

    # 原版操控器
    ctrl = DeadMazeController()
    ctrl.find_window()
    print(f"[Ctrl] {ctrl.target_hwnd:#x}")

    start = goal = path = None
    nav = Navigator(pf, waypoint_reach=25)  # DeadMaze 默认 WP Reach
    navigating = False
    pos = (0, 0)
    frame_cnt = 0

    def draw():
        disp = cv2.resize(map_img, (dw, dh))
        if start:
            sx, sy = int(start[0]*scale), int(start[1]*scale)
            cv2.drawMarker(disp, (sx, sy), (0,255,0), cv2.MARKER_CROSS, 15, 2)
        if goal:
            gx, gy = int(goal[0]*scale), int(goal[1]*scale)
            cv2.drawMarker(disp, (gx, gy), (0,0,255), cv2.MARKER_CROSS, 15, 2)
        if path:
            for x, y in path:
                cv2.circle(disp, (int(x*scale), int(y*scale)), 1, (255,0,0), -1)
        px, py = int(pos[0]*scale), int(pos[1]*scale)
        cv2.circle(disp, (px, py), 6, (0,255,255), -1)
        return disp

    def on_mouse(event, x, y, flags, param):
        nonlocal start, goal, path
        mx, my = int(x/scale), int(y/scale)
        if event == cv2.EVENT_LBUTTONDOWN:
            start = (mx, my)
        elif event == cv2.EVENT_RBUTTONDOWN:
            goal = (mx, my)
            if start and goal:
                path = pf.plan(start, goal)
                print(f"[Path] {len(path) if path else 0} pts")

    cv2.namedWindow("Test")
    cv2.setMouseCallback("Test", on_mouse)
    print("L=Start R=Goal Enter=Go Esc=Stop Q=Quit")

    while True:
        cap.read()
        key = cv2.waitKey(30) & 0xFF

        if navigating and not nav.arrived:
            # 用框架 Navigator 步进
            action = nav.step(pos)
            if action is None:
                print(f"[Arrived] ({pos[0]},{pos[1]})")
                navigating = False
                continue

            # 从 home 的 compute_direction 拿到方向向量, 映射到按键
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
            time.sleep(0.3)
            for k in keys:
                try: ctrl.key_up(getattr(ctrl, f'VK_{k}'))
                except: pass

            # 模拟位移
            vx, vy = DIR_VECTORS[di][0], DIR_VECTORS[di][1]
            spd = 40 if vx and vy else 60
            pos = (pos[0]+vx*spd, pos[1]+vy*spd)

            frame_cnt += 1
            if frame_cnt % 5 == 0:
                print(f"[Nav] ({pos[0]},{pos[1]}) → ({tgt[0]},{tgt[1]}) "
                      f"d=({dx},{dy}) k={keys} {nav._wp_index}/{len(nav.path)}")

        cv2.imshow("Test", draw())

        if key == 13 and path:  # Enter
            navigating = True
            nav.set_route(start, goal)
            pos = start or path[0]
            print(f"[Go] {len(nav.path)}pts")
        elif key == 27:  # Esc
            navigating = False
            nav.cancel()
            for k in ['W','A','S','D']:
                try: ctrl.key_up(getattr(ctrl, f'VK_{k}'))
                except: pass
            print("[Stop]")
        elif key == ord('q'):
            break

    cap.release(); cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
