"""点击/悬停/拖动测试面板"""
import json, os, time, re
import win32gui, win32api, win32con, cv2, numpy as np

CFG = os.path.join(os.path.dirname(__file__), "AImaneuver", "click_points.json")
with open(CFG) as f: points = json.load(f)

def find_game():
    results = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h) == 'Dead Maze':
            r = win32gui.GetWindowRect(h)
            if r[2] - r[0] > 800: results.append((h, r))
    win32gui.EnumWindows(cb, None)
    return results[0] if results else None

hwnd, rect = find_game()
if not hwnd: print("未找到 Dead Maze!"); exit()
if win32gui.IsIconic(hwnd):
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE); time.sleep(0.2)

groups = [
    ("Leave", 0, ["leave_campfire"]),
    ("Food C1", 1020, ["food_col1_r1","food_col1_r2","food_col1_r3","food_col1_r4"]),
    ("Food C2", 1020, ["food_col2_r1","food_col2_r2","food_col2_r3","food_col2_r4"]),
    ("Skills", 0, ["skill_1","skill_2","skill_3","skill_4"]),
    ("Bag C0", 1250, ["bag_col0_r1","bag_col0_r2","bag_col0_r3","bag_col0_r4","bag_col0_r5","bag_col0_r6"]),
    ("Bag C1", 1580, ["bag_col1_r1","bag_col1_r2","bag_col1_r3","bag_col1_r4"]),
    ("Bag C2", 1580, ["bag_col2_r1","bag_col2_r2","bag_col2_r3","bag_col2_r4"]),
    ("Bag C3", 1580, ["bag_col3_r1","bag_col3_r2","bag_col3_r3","bag_col3_r4"]),
    ("Bag C4", 1580, ["bag_col4_r1","bag_col4_r2","bag_col4_r3","bag_col4_r4"]),
    ("Actions", 0, ["toggle_bag","open_craft","organize_bag"]),
]

drag_start = {}
for gname, ds, names in groups:
    for n in names: drag_start[n] = ds

BUTTONS = []
bx, by = 10, 10
for gname, ds, names in groups:
    for i, name in enumerate(names):
        label = f"{gname}:{i+1}" if len(names) > 1 else gname
        BUTTONS.append((label, bx, by, 100, 22, name))
        bx += 108
    bx = 10; by += 26
WIN_W, WIN_H = 800, by + 30

action_mode = 0  # 0=click 1=hover 2=drag

def do_action(name):
    p = points[name]; x, y = p['x'], p['y']
    ds = drag_start.get(name, 0)
    lp = win32api.MAKELONG(x, y)
    if action_mode == 1:
        win32api.SendMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lp)
        print(f"[hover] {name} ({x},{y})")
    elif action_mode == 2 and ds > 0:
        lp_s = win32api.MAKELONG(ds, y)
        win32api.SendMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lp_s)
        time.sleep(0.02)
        win32api.SendMessage(hwnd, win32con.WM_LBUTTONDOWN, 0, lp_s)
        time.sleep(0.02)
        win32api.SendMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lp)
        time.sleep(0.02)
        win32api.SendMessage(hwnd, win32con.WM_LBUTTONUP, 0, lp)
        print(f"[drag] {name} ({ds},{y})->({x},{y})")
    else:
        win32api.SendMessage(hwnd, win32con.WM_LBUTTONDOWN, 0, lp)
        win32api.SendMessage(hwnd, win32con.WM_LBUTTONUP, 0, lp)
        print(f"[click] {name} ({x},{y})")

def on_mouse(event, sx, sy, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        for label, bx, by, bw, bh, name in BUTTONS:
            if bx <= sx <= bx+bw and by <= sy <= by+bh:
                do_action(name)

cv2.namedWindow("Click Panel", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("Click Panel", cv2.WND_PROP_TOPMOST, 1)
cv2.setMouseCallback("Click Panel", on_mouse)

modes = ["CLICK", "HOVER", "DRAG"]
colors = [(0,255,0), (0,255,255), (255,200,0)]

while True:
    canvas = np.zeros((WIN_H, WIN_W, 3), dtype=np.uint8)
    for label, x, y, w, h, name in BUTTONS:
        p = points[name]; txt = f"{label} ({p['x']},{p['y']})"
        cv2.rectangle(canvas, (x,y), (x+w,y+h), (80,80,80), -1)
        cv2.rectangle(canvas, (x,y), (x+w,y+h), (0,200,0), 1)
        cv2.putText(canvas, txt, (x+3,y+16), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0,255,0), 1)

    cv2.putText(canvas, f"MODE: {modes[action_mode]} (H=switch)",
                (10, WIN_H-20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, colors[action_mode], 1)
    cv2.putText(canvas, "Q=quit", (10, WIN_H-5), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (150,150,150), 1)
    cv2.imshow("Click Panel", canvas)
    key = cv2.waitKey(100) & 0xFF
    if key == ord('q'): break
    if key in (ord('h'), ord('H')):
        action_mode = (action_mode + 1) % 3
        print(f"[mode] {modes[action_mode]}")

cv2.destroyAllWindows()
