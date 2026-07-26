"""DeadMaze 集成测试 — 使用 GameAutomator 封装.

操作: 左键=起点 右键=终点 Enter=导航 Esc=停 Q=退
"""
import sys, os, cv2, numpy as np, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from game_automator import GameAutomator
from game_controller import DeadMazeController
from map_tracker import Tracker

MAP = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                   "map", "MazonAcademy", "MazonAcademy.jpg")
RCH = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                    "map", "MazonAcademy", "MazonAcademy_reachable.png")

# Actions → 按键映射
ACT_KEYS = {
    'MOVE_N': ['W'], 'MOVE_NE': ['W','D'], 'MOVE_E': ['D'],
    'MOVE_SE': ['S','D'], 'MOVE_S': ['S'], 'MOVE_SW': ['S','A'],
    'MOVE_W': ['A'], 'MOVE_NW': ['W','A'],
}

def main():
    auto = GameAutomator(MAP, RCH)
    tracker = Tracker(MAP, camera_id=1)
    ctrl = DeadMazeController()
    ctrl.find_window()

    img = cv2.imread(MAP)
    sc = min(1200/img.shape[1], 800/img.shape[0], 1.0)
    dw, dh = int(img.shape[1]*sc), int(img.shape[0]*sc)

    start = goal = None
    running = False

    def draw():
        d = cv2.resize(img, (dw, dh))
        if start:
            cv2.drawMarker(d, (int(start[0]*sc),int(start[1]*sc)), (0,255,0), cv2.MARKER_CROSS,15,2)
        if goal:
            cv2.drawMarker(d, (int(goal[0]*sc),int(goal[1]*sc)), (0,0,255), cv2.MARKER_CROSS,15,2)
        for x,y in auto.path:
            cv2.circle(d, (int(x*sc),int(y*sc)), 1, (255,0,0), -1)
        if auto.current_waypoint:
            wx,wy = auto.current_waypoint
            cv2.drawMarker(d, (int(wx*sc),int(wy*sc)), (0,255,255), cv2.MARKER_CROSS,10,2)
        if tracker.last_position:
            tx,ty = tracker.last_position
            cv2.circle(d, (int(tx*sc),int(ty*sc)), 6, (0,255,255), -1)
        return d

    def on_mouse(event, x, y, flags, param):
        nonlocal start, goal
        mx, my = int(x/sc), int(y/sc)
        if event == cv2.EVENT_LBUTTONDOWN:
            start = (mx, my)
            tracker.last_position = start
            tracker.prev_frame = None
            tracker.need_click = False
        elif event == cv2.EVENT_RBUTTONDOWN:
            goal = (mx, my)
            auto.set_route(start, goal)
            print(f"[Path] {len(auto.path)}pts")

    cv2.namedWindow("Test")
    cv2.setMouseCallback("Test", on_mouse)

    while True:
        key = cv2.waitKey(30) & 0xFF

        if not running and not tracker.need_click:
            tracker.track()

        if running and not auto.arrived:
            tracker.track()
            pos = tracker.last_position
            if not pos: continue

            action = auto.step(pos)  # 框架 API: pos→动作名
            if action is None:
                print(f"[Arrived] ({pos[0]},{pos[1]})"); running = False; continue

            keys = ACT_KEYS.get(action, ['W'])
            for name in ['W','A','S','D']:
                if name not in keys:
                    try: ctrl.key_up(getattr(ctrl, f'VK_{name}'))
                    except: pass
            for k in keys:
                try: ctrl.key_down(getattr(ctrl, f'VK_{k}'))
                except: pass
            time.sleep(0.5)
            for k in keys:
                try: ctrl.key_up(getattr(ctrl, f'VK_{k}'))
                except: pass

        cv2.imshow("Test", draw())

        if key == 13 and start and goal:
            running = True; auto.set_route(start, goal)
        elif key == 27:
            running = False; auto.cancel()
            for k in ['W','A','S','D']:
                try: ctrl.key_up(getattr(ctrl, f'VK_{k}'))
                except: pass
        elif key == ord('q'): break

    tracker.cap.release(); cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
