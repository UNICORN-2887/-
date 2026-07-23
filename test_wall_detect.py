"""
墙检测测试 — YOLO画面中标注僵尸是否被墙阻挡
绿框=可攻击  红框=墙后(不可攻击)
"""
import cv2, numpy as np, json, os, time, math

BASE = os.path.dirname(__file__)
MODEL_PATH = os.path.join(BASE, "AImaneuver",
    "runs", "detect", "deadmaze_combat", "weights", "best.pt")
OBS_CAM = 1

# ---- 加载可达图 (DS=50 降采样, 与navigator一致) ----
DS = 50
raw = cv2.imread("map_output_reachable.png", cv2.IMREAD_GRAYSCALE)
if raw is None:
    print("请先运行 reachability_map.py 生成 map_output_reachable.png")
    exit(1)
raw_h, raw_w = raw.shape[:2]
gw2, gh2 = raw_w // DS, raw_h // DS
grid = cv2.resize((raw > 128).astype(np.uint8), (gw2, gh2),
                  interpolation=cv2.INTER_NEAREST)
GW, GH = gw2, gh2
print(f"[可达图] 原{raw_w}x{raw_h} → DS{DS} → {GW}x{GH}")

# ---- YOLO ----
from ultralytics import YOLO
yolo = YOLO(MODEL_PATH)
print("[YOLO] 已加载")

# ---- OBS ----
cap = cv2.VideoCapture(OBS_CAM, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

cv2.namedWindow("WallDetect", cv2.WINDOW_NORMAL)
cv2.resizeWindow("WallDetect", 900, 650)
FONT = cv2.FONT_HERSHEY_SIMPLEX

# 玩家在可达图上的位置 (手动点击设置)
player_gx, player_gy = GW // 2, GH // 2  # 默认中心
print(f"\n在画面上点击设置玩家在可达图上的位置")
print("Q=退出\n")

def on_mouse(event, sx, sy, flags, param):
    global player_gx, player_gy
    if event == cv2.EVENT_LBUTTONDOWN:
        # 小地图在canvas位置(600,350), 大小300x300
        mm_x, mm_y, mm_s = 600, 350, 300
        if mm_x <= sx <= mm_x + mm_s and mm_y <= sy <= mm_y + mm_s:
            player_gx = int((sx - mm_x) * GW / mm_s)
            player_gy = int((sy - mm_y) * GH / mm_s)
            player_gx = max(0, min(GW - 1, player_gx))
            player_gy = max(0, min(GH - 1, player_gy))
            print(f"[玩家] 可达图: ({player_gx}, {player_gy})")

cv2.setMouseCallback("WallDetect", on_mouse)

def is_blocked(zx, zy):
    """锥形射线检测 — 3条射线取最优"""
    dx = zx - 960; dy = zy - 540
    dist = math.hypot(dx, dy)
    if dist < 20: return False, 0
    base = math.atan2(dy, dx)
    # 网格步长: DS=50, 屏幕距离→网格距离 (1px ≈ 0.2格)
    grid_dist = int(dist * 0.2)
    step = max(1, grid_dist // 30); max_steps = grid_dist
    best_ratio = 1.0
    for offset in [0, -0.26, 0.26]:
        angle = base + offset
        blocked = 0; total = 0
        for i in range(step, max_steps + 1, step):
            wx = int(player_gx + i * math.cos(angle))
            wy = int(player_gy + i * math.sin(angle))
            if 0 <= wx < GW and 0 <= wy < GH:
                total += 1
                if grid[wy, wx] == 0:
                    blocked += 1
        if total > 2:
            best_ratio = min(best_ratio, blocked / total)
    return best_ratio > 0.5, best_ratio

while True:
    ret, frame = cap.read()
    if not ret: time.sleep(0.01); continue

    det = yolo(frame, verbose=False, conf=0.3)[0]
    disp = det.plot()

    # 标注僵尸 + 墙检测
    zombies = []
    for b in det.boxes:
        name = yolo.names[int(b.cls[0])]
        if 'ZB' in name.upper() or 'ZOMBIE' in name.upper():
            x1, y1, x2, y2 = map(int, b.xyxy[0])
            cx = (x1 + x2) // 2; cy = (y1 + y2) // 2
            dist = int(math.hypot(cx - 960, cy - 540))
            blocked, ratio = is_blocked(cx, cy)
            zombies.append((cx, cy, name, dist, blocked, ratio, (x1, y1, x2, y2)))

    zombies.sort(key=lambda z: z[3])

    for cx, cy, name, dist, blocked, ratio, (x1, y1, x2, y2) in zombies:
        col = (0, 0, 255) if blocked else (0, 255, 0)  # 红=墙后 绿=可打
        thick = 1 if blocked else 2
        cv2.rectangle(disp, (x1, y1), (x2, y2), col, thick)
        tag = f"{name[-8:]} {dist}px"
        if blocked: tag += f" [墙{ratio:.0%}]"
        cv2.putText(disp, tag, (x1, y1 - 5), FONT, 0.35, col, 1)
        # 从中心画射线
        cv2.line(disp, (960, 540), (cx, cy),
                (100, 100, 255) if blocked else (100, 255, 100), 1)

    # 渲染
    canvas = np.zeros((650, 900, 3), dtype=np.uint8)
    mw = 650
    mh = int(650 * 1080 / 1920)
    disp2 = cv2.resize(disp, (mw, mh))
    canvas[:mh, :mw] = disp2

    # 右侧面板
    rx = mw + 10
    cv2.putText(canvas, "僵尸目标:", (rx, 20), FONT, 0.5, (0, 255, 0), 1)
    cv2.putText(canvas, "绿=可攻击 红=墙后", (rx, 42), FONT, 0.35, (150, 150, 150), 1)
    cv2.putText(canvas, f"玩家网格: ({player_gx},{player_gy})", (rx, 65),
               FONT, 0.35, (255, 255, 0), 1)
    y = 90
    valid_count = 0
    for cx, cy, name, dist, blocked, ratio, _ in zombies[:8]:
        if not blocked: valid_count += 1
        short = name.replace('ZB', '').replace('Zombie', 'Z')
        col = (100, 100, 255) if blocked else (0, 255, 0)
        tag = f" [墙]" if blocked else " [可]"
        cv2.putText(canvas, f"{short}: {dist}px{tag}",
                   (rx, y), FONT, 0.35, col, 1)
        y += 20

    cv2.putText(canvas, f"可攻击: {valid_count}/{len(zombies)}",
               (rx, y + 10), FONT, 0.4, (0, 255, 255), 1)

    # 可达图小地图 (右下)
    mm = cv2.resize(grid * 255, (300, 300))
    mm_color = cv2.cvtColor(mm, cv2.COLOR_GRAY2BGR)
    cv2.circle(mm_color, (player_gx * 300 // GW, player_gy * 300 // GH),
              4, (0, 255, 255), -1)
    canvas[350:650, 600:900] = mm_color
    cv2.putText(canvas, "可达图(点击设玩家位置)", (605, 345),
               FONT, 0.3, (200, 200, 200), 1)
    cv2.putText(canvas, "Q=退出", (10, 640), FONT, 0.35, (150, 150, 150), 1)

    cv2.imshow("WallDetect", canvas)
    key = cv2.waitKey(30) & 0xFF
    if key == ord('q'): break

cap.release()
cv2.destroyAllWindows()
