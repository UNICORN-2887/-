"""完整集成: DeadMaze Tracker + framework Pathfinder + Navigator + Controller."""
import sys, os, cv2, numpy as np, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from game_automator.mapping import Pathfinder
from game_automator.navigation import Navigator, compute_direction
from game_automator.driver import Actions
from game_controller import DeadMazeController
from map_tracker import Tracker

MAP = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                   "map", "MazonAcademy", "MazonAcademy.jpg")
RCH = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                    "map", "MazonAcademy", "MazonAcademy_reachable.png")

# Actions -> keys
ACT_KEYS = {
    Actions.MOVE_N: ['W'], Actions.MOVE_NE: ['W','D'], Actions.MOVE_E: ['D'],
    Actions.MOVE_SE: ['S','D'], Actions.MOVE_S: ['S'], Actions.MOVE_SW: ['S','A'],
    Actions.MOVE_W: ['A'], Actions.MOVE_NW: ['W','A'],
}

def main():
    pf = Pathfinder(RCH, shrink=80)
    print(f"[PF] grid={pf.grid_size}")
    tracker = Tracker(MAP, camera_id=1)
    print(f"[TK] map={tracker.mw}x{tracker.mh}")
    ctrl = DeadMazeController()
    ctrl.find_window()
    print(f"[CT] hwnd={ctrl.target_hwnd:#x}")

    nav = Navigator(pf, waypoint_reach=25, lookahead=90)
    img = cv2.imread(MAP)
    mh, mw = img.shape[:2]
    s = min(1200/mw, 800/mh, 1.0)
    dw, dh = int(mw*s), int(mh*s)

    start = goal = None
    running = False

    def draw():
        d = cv2.resize(img, (dw, dh))
        if start:
            cv2.drawMarker(d, (int(start[0]*s),int(start[1]*s)), (0,255,0), cv2.MARKER_CROSS, 15, 2)
        if goal:
            cv2.drawMarker(d, (int(goal[0]*s),int(goal[1]*s)), (0,0,255), cv2.MARKER_CROSS, 15, 2)
        for x, y in nav.path:
            cv2.circle(d, (int(x*s), int(y*s)), 1, (255,0,0), -1)
        if nav.current_waypoint:
            wx, wy = nav.current_waypoint
            cv2.drawMarker(d, (int(wx*s), int(wy*s)), (0,255,255), cv2.MARKER_CROSS, 10, 2)
        if tracker.last_position:
            tx, ty = tracker.last_position
            cv2.circle(d, (int(tx*s), int(ty*s)), 6, (0,255,255), -1)
        return d

    def on_mouse(event, x, y, flags, param):
        nonlocal start, goal
        mx, my = int(x/s), int(y/s)
        if event == cv2.EVENT_LBUTTONDOWN:
            start = (mx, my)
            tracker.last_position = start
            tracker.prev_frame = None
            tracker.need_click = False
        elif event == cv2.EVENT_RBUTTONDOWN:
            goal = (mx, my)
            nav.set_route(start, goal)
            print(f"[Path] {len(nav.path)}pts")

    cv2.namedWindow("Test")
    cv2.setMouseCallback("Test", on_mouse)

    while True:
        key = cv2.waitKey(30) & 0xFF

        # 后台追踪
        if not running and not tracker.need_click:
            tracker.track()

        # 导航步进 (完全抄原版 navigate_step 时序)
        if running and not nav.arrived:
            tracker.track()
            pos = tracker.last_position
            if not pos:
                continue

            action = nav.step(pos)
            if action is None:
                print(f"[Arrived] ({pos[0]},{pos[1]})")
                running = False
                continue

            keys = ACT_KEYS.get(action, ['W'])
            for name in ['W','A','S','D']:
                if name not in keys:
                    vk = getattr(ctrl, f'VK_{name}')
                    try: ctrl.key_up(vk)
                    except: pass
            for k in keys:
                vk = getattr(ctrl, f'VK_{k}')
                try: ctrl.key_down(vk)
                except: pass
            time.sleep(0.5)
            for k in keys:
                vk = getattr(ctrl, f'VK_{k}')
                try: ctrl.key_up(vk)
                except: pass

        cv2.imshow("Test", draw())

        if key == 13 and start and goal:
            running = True
            nav.set_route(start, goal)
        elif key == 27:
            running = False; nav.cancel()
            for k in ['W','A','S','D']:
                try: ctrl.key_up(getattr(ctrl, f'VK_{k}'))
                except: pass
        elif key == ord('q'):
            break

    tracker.cap.release(); cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
