"""
补给+点击 统一测试面板
========================
集成功能:
  1. OBS画面 + YOLO检测叠加
  2. 状态OCR (Hunger/Thirst/HP/Exp/Stamina/Threat)
  3. 火堆"开"字检测
  4. 8格食物栏拖拽扫描 + OCR (食物/水+数量)
  5. 补给决策引擎 (规则一/二/三)
  6. 点击/悬停/拖拽 测试面板 (所有 click_points.json 按钮)
  7. 后台SendMessage操控

快捷键:
  S     = 开始补给扫描 (确认火堆→读状态→扫8格→决策)
  T     = 单次OCR测试 (打印所有状态ROI结果)
  C     = 切换为 CLICK 模式
  H     = 切换为 HOVER 模式
  D     = 切换为 DRAG 模式
  1-9   = 快速点击对应按钮
  Q     = 退出
"""

import cv2, numpy as np, json, os, time, re, easyocr
import win32gui, win32api, win32con
from ultralytics import YOLO
from PIL import Image, ImageDraw, ImageFont

# ===================== 路径配置 =====================
BASE = os.path.dirname(__file__)
MODEL_PATH = os.path.join(BASE, "runs", "detect", "deadmaze_combat", "weights", "best.pt")
CLICK_FILE = os.path.join(BASE, "click_points.json")
OFFSET_FILE = os.path.join(BASE, "click_offset.json")
OCR_ROI_FILE = os.path.join(BASE, "ocr_reader_roi.json")
HP_ROI_FILE = os.path.join(BASE, "hp_detector_roi.json")
FOOD_OCR_ROI_FILE = os.path.join(BASE, "food_ocr_roi.json")

OBS_CAM_ID = 1
CONF_THRESHOLD = 0.3

# ===================== 中文字体 =====================
_FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
_FONT_SM = ImageFont.truetype(_FONT_PATH, 15)
_FONT_MD = ImageFont.truetype(_FONT_PATH, 19)
_FONT_LG = ImageFont.truetype(_FONT_PATH, 24)
_FONT_BTN = ImageFont.truetype(_FONT_PATH, 12)  # 按钮小字体


def put_text_cn(img, text, pos, font=_FONT_SM, color=(0, 255, 0)):
    """在cv2图片上用PIL画中文"""
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    draw.text(pos, text, font=font, fill=color)
    rgb = np.array(pil)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    img[:] = bgr


# ===================== 窗口查找 =====================
def find_game():
    results = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h) == 'Dead Maze':
            r = win32gui.GetWindowRect(h)
            if r[2] - r[0] > 800:
                results.append(h)

    win32gui.EnumWindows(cb, None)
    return results[0] if results else None


# ===================== 后台操控工具 =====================
def bg_click(hwnd, x, y):
    """后台点击"""
    lp = win32api.MAKELONG(x, y)
    win32api.SendMessage(hwnd, win32con.WM_LBUTTONDOWN, 0, lp)
    time.sleep(0.02)
    win32api.SendMessage(hwnd, win32con.WM_LBUTTONUP, 0, lp)


def bg_hover(hwnd, x, y):
    """后台悬停"""
    lp = win32api.MAKELONG(x, y)
    win32api.SendMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lp)


def bg_drag(hwnd, x1, y1, x2, y2, steps=10, step_time=0.03):
    """后台拖拽"""
    lp = win32api.MAKELONG(x1, y1)
    win32api.SendMessage(hwnd, win32con.WM_LBUTTONDOWN, 0, lp)
    time.sleep(0.02)
    for i in range(1, steps + 1):
        cx = int(x1 + (x2 - x1) * i / steps)
        cy = int(y1 + (y2 - y1) * i / steps)
        lp = win32api.MAKELONG(cx, cy)
        win32api.SendMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lp)
        time.sleep(step_time)
    lp = win32api.MAKELONG(x2, y2)
    win32api.SendMessage(hwnd, win32con.WM_LBUTTONUP, 0, lp)
    time.sleep(0.02)


# ===================== 补给决策引擎 =====================
def decide_food(status, items):
    """
    status: {'Hunger': int, 'Thirst': int}
    items: [{'name': str, 'food': int|None, 'water': int|None, 'slot': str, ...}]
    返回: ('eat', item, reason) | ('leave', None, reason) | ('none', None, reason)
    """
    hunger = status.get("Hunger", 0)
    thirst = status.get("Thirst", 0)

    if hunger > 100 and thirst > 100:
        return ("leave", None, "双值>100, 无需补给")
    if not items:
        return ("leave", None, "无可食用物品")

    rule1_candidates = []
    rule2_candidates = []

    for item in items:
        f = item.get("food") or 0
        w = item.get("water") or 0
        if f == 0 and w == 0:
            continue

        new_h = hunger + f
        new_t = thirst + w
        over_h = max(0, new_h - 130)
        over_t = max(0, new_t - 130)
        total_overflow = over_h + over_t
        total_benefit = f + w

        if total_overflow == 0:
            rule1_candidates.append((total_benefit, item))
        else:
            rule2_candidates.append((total_overflow, -total_benefit, item))

    if rule1_candidates:
        rule1_candidates.sort(key=lambda x: -x[0])
        best = rule1_candidates[0][1]
        return ("eat", best, f"规则一: {best['name']} (不超130)")

    if rule2_candidates:
        rule2_candidates.sort(key=lambda x: (x[0], x[1]))
        best = rule2_candidates[0][2]
        overflow = rule2_candidates[0][0]
        return ("eat", best, f"规则二: {best['name']} (溢出={overflow})")

    return ("leave", None, "无可用食物")


# ===================== 初始化 =====================
print("=" * 60)
print("  补给+点击 统一测试面板")
print("=" * 60)

# --- 游戏窗口 ---
hwnd = find_game()
if not hwnd:
    print("[错误] 未找到 Dead Maze 窗口!")
    exit(1)
if win32gui.IsIconic(hwnd):
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    time.sleep(0.2)
print(f"[游戏] hwnd=0x{hwnd:08X}")

# --- 偏移 ---
dx, dy = 0, 0
if os.path.exists(OFFSET_FILE):
    d = json.load(open(OFFSET_FILE))
    dx, dy = d.get('dx', 0), d.get('dy', 0)
    print(f"[偏移] dx={dx} dy={dy}")

# --- OBS ---
cap = cv2.VideoCapture(OBS_CAM_ID, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
ret, test = cap.read()
if not ret:
    print("[错误] OBS虚拟摄像头未开启!")
    exit(1)
obs_w, obs_h = test.shape[1], test.shape[0]
print(f"[OBS] {obs_w}x{obs_h}")

# --- 模型 ---
yolo = YOLO(MODEL_PATH)
ocr_en = easyocr.Reader(["en"], gpu=True)
ocr_zh = easyocr.Reader(["ch_sim"], gpu=True)
print("[模型] YOLO + EasyOCR(en+ch) 就绪")

# --- 状态ROI ---
OCR_REGIONS = [
    ("Exp", 972, 1053, 50, 25),
    ("Hunger", 1715, 1055, 50, 25),
    ("Thirst", 1632, 1057, 50, 25),
    ("Stamina", 1551, 1059, 50, 25),
    ("Threat", 898, 1056, 50, 25),
]
OPEN_ROI = [300, 300, 40, 30]

if os.path.exists(OCR_ROI_FILE):
    saved = json.load(open(OCR_ROI_FILE))
    print(f"[加载] ocr_reader_roi.json: {len(saved)} 区域")
    for r in saved:
        name = r[0]
        for i, orig in enumerate(OCR_REGIONS):
            if orig[0] == name:
                OCR_REGIONS[i] = tuple(r[:5])
                break
        if name == "Open":
            OPEN_ROI = [int(r[1]), int(r[2]), int(r[3]), int(r[4])]

HP_ROI = [956, 336, 102, 4]
if os.path.exists(HP_ROI_FILE):
    HP_ROI = json.load(open(HP_ROI_FILE))

# --- 食物/水 Tooltip OCR ROI (标定好的固定位置) ---
FOOD_OCR_ROI = [1016, 436, 298, 164]  # 默认: x, y, w, h
if os.path.exists(FOOD_OCR_ROI_FILE):
    FOOD_OCR_ROI = json.load(open(FOOD_OCR_ROI_FILE))
    print(f"[加载] food_ocr_roi.json: {FOOD_OCR_ROI}")
else:
    print(f"[警告] 未找到 food_ocr_roi.json, 使用默认 {FOOD_OCR_ROI}")

GREEN_LOW = np.array([35, 40, 40])
GREEN_HIGH = np.array([85, 255, 255])

# --- 按钮配置 (来自 click_points.json) ---
with open(CLICK_FILE) as f:
    click_pts = json.load(f)

BUTTON_GROUPS = [
    ("离开", 0, ["leave_campfire"]),
    ("食物C1", 840, ["food_col1_r1", "food_col1_r2", "food_col1_r3", "food_col1_r4"]),
    ("食物C2", 840, ["food_col2_r1", "food_col2_r2", "food_col2_r3", "food_col2_r4"]),
    ("技能", 0, ["skill_1", "skill_2", "skill_3", "skill_4"]),
    ("背包C0", 1250, ["bag_col0_r1", "bag_col0_r2", "bag_col0_r3", "bag_col0_r4", "bag_col0_r5", "bag_col0_r6"]),
    ("背包C1", 1580, ["bag_col1_r1", "bag_col1_r2", "bag_col1_r3", "bag_col1_r4"]),
    ("背包C2", 1580, ["bag_col2_r1", "bag_col2_r2", "bag_col2_r3", "bag_col2_r4"]),
    ("背包C3", 1580, ["bag_col3_r1", "bag_col3_r2", "bag_col3_r3", "bag_col3_r4"]),
    ("背包C4", 1580, ["bag_col4_r1", "bag_col4_r2", "bag_col4_r3", "bag_col4_r4"]),
    ("功能", 0, ["toggle_bag", "open_craft", "organize_bag"]),
]

# 构建拖拽起始点映射
drag_start = {}
for gname, ds, names in BUTTON_GROUPS:
    for n in names:
        drag_start[n] = ds

# 按钮布局参数
BTN_AREA_TOP = 520   # 按钮区域在Panel中的起始Y
BTN_W, BTN_H = 106, 20
BTN_GAP_X, BTN_GAP_Y = 112, 24

# 构建扁平按钮列表 (存储实际渲染坐标, 用于渲染+鼠标检测)
BUTTONS = []
bx, by = 10, 10  # 布局网格坐标
for gname, ds, names in BUTTON_GROUPS:
    for i, name in enumerate(names):
        label = f"{gname}:{i + 1}" if len(names) > 1 else gname
        # 存储实际渲染坐标: (label, render_x, render_y, w, h, name, drag_start)
        rx = bx
        ry = BTN_AREA_TOP + by
        BUTTONS.append((label, rx, ry, BTN_W, BTN_H, name, ds))
        bx += BTN_GAP_X
    bx = 10
    by += BTN_GAP_Y

# 食物栏8格 (用于补给扫描)
# 格式: (名称, x, y, 拖拽起始y)
# 第一列: 从 y=340 往下滑到格子  /  第二列: 从 y=460 往上滑到格子
FOOD_SLOTS = [
    ("食物1-1", 885, 383, 340),
    ("食物1-2", 900, 383, 340),
    ("食物1-3", 950, 383, 340),
    ("食物1-4", 970, 383, 340),
    ("食物2-1", 885, 423, 460),
    ("食物2-2", 900, 423, 460),
    ("食物2-3", 950, 423, 460),
    ("食物2-4", 970, 423, 460),
]

# --- 窗口 ---
PANEL_W, PANEL_H = 1100, 700
cv2.namedWindow("SupplyTestPanel", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("SupplyTestPanel", cv2.WND_PROP_TOPMOST, 1)
cv2.resizeWindow("SupplyTestPanel", PANEL_W, PANEL_H)

# ===================== 状态变量 =====================
action_mode = 0  # 0=CLICK, 1=HOVER, 2=DRAG
MODES = ["CLICK", "HOVER", "DRAG"]
MODE_COLORS = [(0, 255, 0), (0, 255, 255), (255, 200, 0)]

status = {}  # OCR状态结果
scan_results = []  # 食物扫描结果
decision = None  # 决策结果
scanning = False
scan_msg = "S=扫描  T=OCR  [1]点击 [2]悬停 [3/D/G]拖拽  Q=退出"

last_frame = None
yolo_frame = None
last_yolo = 0
last_status = 0


# ===================== 核心函数 =====================
def read_status(frame):
    """读取所有OCR状态 + HP"""
    s = {}
    for name, rx, ry, rw, rh in OCR_REGIONS:
        roi = frame[ry:ry + rh, rx:rx + rw]
        if roi.size == 0:
            s[name] = "?"
            continue
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        big = cv2.resize(gray, (rw * 6, rh * 6), interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        enhanced = clahe.apply(big)
        r = ocr_en.readtext(enhanced, detail=1, allowlist="0123456789xp")
        txt = r[0][1] if r else "?"
        s[name] = txt

    # HP绿条
    hx, hy, hw, hh = [max(1, v) for v in HP_ROI]
    hp_roi = frame[hy:hy + hh, hx:hx + hw]
    hp_pct = 0
    if hp_roi.size > 0:
        hsv = cv2.cvtColor(hp_roi, cv2.COLOR_BGR2HSV)
        gm = cv2.inRange(hsv, GREEN_LOW, GREEN_HIGH)
        hp_pct = np.count_nonzero(gm) / gm.size * 100
    s["HP"] = f"{hp_pct:.0f}%"

    # 数值约束
    for nm in ["Hunger", "Thirst", "Stamina"]:
        v = s.get(nm, "?")
        if v.isdigit():
            n = int(v)
            if n > 200: n = int(v[:2])
            s[nm] = str(n)
    ev = s.get("Exp", "?")
    en = int(''.join(c for c in ev if c.isdigit())) if any(c.isdigit() for c in ev) else None
    if en is not None:
        if en > 5000: en = int(str(en)[:-1])
        s["Exp"] = f"{en}xp" if en else "0xp"
    return s


def detect_open(frame):
    """检测'开'字"""
    ox, oy, ow, oh = OPEN_ROI
    roi = frame[oy:oy + oh, ox:ox + ow]
    if roi.size == 0: return False
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    big = cv2.resize(gray, (ow * 5, oh * 5), interpolation=cv2.INTER_CUBIC)
    txt_list = ocr_zh.readtext(big, detail=0)
    return any("开" in t for t in txt_list)


def scan_food_slot(slot_name, sx, sy, drag_start_y):
    """垂直拖拽 → drain OBS → OCR (与 step_test 完全一致)"""
    # Step 1: 拖拽
    bg_drag(hwnd, sx, drag_start_y, sx, sy)

    # Step 2: 持续 drain + 泵消息 (与step_test一致)
    for _ in range(1):  # 1秒
        deadline = time.time() + 0.8
        while time.time() < deadline:
            cap.grab()
            cv2.waitKey(1)
        cap.retrieve()  # 消耗掉, 确保下一轮 get 新帧

    # Step 3: grab 最新帧后 retrieve
    for _ in range(10):
        cap.grab()
        cv2.waitKey(1)
    ret, f = cap.retrieve()
    if not ret:
        return None, None, None, "(cap failed)"

    # tooltip ROI
    fx, fy, fw, fh = [int(v) for v in FOOD_OCR_ROI]
    fx = max(0, min(fx, obs_w - 2)); fy = max(0, min(fy, obs_h - 2))
    fw = min(fw, obs_w - fx); fh = min(fh, obs_h - fy)
    roi = f[fy:fy + fh, fx:fx + fw]
    if roi.size == 0:
        return None, None, None, "(roi empty)"

    # 调试截图
    debug_dir = os.path.join(BASE, "debug_ocr")
    os.makedirs(debug_dir, exist_ok=True)
    cv2.imwrite(os.path.join(debug_dir, f"food_{slot_name}.png"), roi)

    # OCR
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    big = cv2.resize(gray, (fw * 3, fh * 3), interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    enhanced = clahe.apply(big)
    r = ocr_zh.readtext(enhanced, detail=1)
    txt = " ".join([line[1] for line in r]) if r else ""

    print(f"    [OCR] raw='{txt[:80]}'  ROI=({fx},{fy}) {fw}x{fh}")

    # 同时提取食物和水 (不是二选一, 一个物品可以同时+食物+水)
    food_qty = None; water_qty = None
    # 匹配 "食物 +20" "食钩 +20" "贪物 +20"
    fm = re.search(r'[食贪饮][物钩饭]\s*[+~-]?\s*(\d+)', txt)
    if fm: food_qty = int(fm.group(1))
    # 匹配 "水 +46" "水+46"
    wm = re.search(r'水\s*[+~-]?\s*(\d+)', txt)
    if wm: water_qty = int(wm.group(1))

    # 类型标记
    if food_qty and water_qty:
        item_type = "食物+水"
    elif food_qty:
        item_type = "食物"
    elif water_qty:
        item_type = "水"
    else:
        item_type = None

    return item_type, food_qty, water_qty, txt


# 食物按钮垂直拖拽起点映射 (用于面板拖拽测试)
FOOD_VERT_DRAG = {
    "food_col1_r1": 340, "food_col1_r2": 340, "food_col1_r3": 340, "food_col1_r4": 340,
    "food_col2_r1": 460, "food_col2_r2": 460, "food_col2_r3": 460, "food_col2_r4": 460,
}

# ... (keep this before do_action)

def do_action(name):
    """执行点击/悬停/拖拽"""
    p = click_pts[name]
    x, y = p['x'], p['y']
    ds = drag_start.get(name, 0)

    if action_mode == 1:  # HOVER
        bg_hover(hwnd, x, y)
        print(f"[悬停] {name} ({x},{y})")
    elif action_mode == 2:  # DRAG
        if name in FOOD_VERT_DRAG:
            # 食物格子: 垂直拖拽
            start_y = FOOD_VERT_DRAG[name]
            bg_drag(hwnd, x, start_y, x, y)
            print(f"[拖拽-垂直] {name} ({x},{start_y})→({x},{y})")
        else:
            # 其他按钮: 水平拖拽
            start_x = ds if ds > 0 else x - 50
            bg_drag(hwnd, start_x, y, x, y)
            print(f"[拖拽-水平] {name} ({start_x},{y})→({x},{y})")
    else:  # CLICK
        bg_click(hwnd, x, y)
        print(f"[点击] {name} ({x},{y})")


# ===================== 鼠标回调 =====================
def on_mouse(event, sx, sy, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        for label, bx, by, bw, bh, name, ds in BUTTONS:
            if bx <= sx <= bx + bw and by <= sy <= by + bh:
                do_action(name)
                break


cv2.setMouseCallback("SupplyTestPanel", on_mouse)

# ===================== 主循环 =====================
while True:
    ret, frame = cap.read()
    if not ret:
        time.sleep(0.01)
        continue
    now = time.time()

    # YOLO (每1秒)
    if now - last_yolo > 1.0:
        det = yolo(frame, verbose=False, conf=CONF_THRESHOLD)[0]
        yolo_frame = det.plot()
        last_yolo = now

    # 读取状态 (每2秒, 不扫描时)
    if not scanning and now - last_status > 2.0:
        status = read_status(frame)
        last_status = now
        last_frame = frame

    # ===================== 渲染 =====================
    canvas = np.zeros((PANEL_H, PANEL_W, 3), dtype=np.uint8)

    # ---- 左侧: OBS+YOLO ----
    mw, mh = 570, int(570 * obs_h / obs_w)
    if yolo_frame is not None:
        disp = cv2.resize(yolo_frame, (mw, mh))
    else:
        disp = cv2.resize(frame, (mw, mh))
    ms = mw / obs_w

    # ---- 状态ROI (粗框 + 标签 + 当前值) ----
    for name, rx, ry, rw, rh in OCR_REGIONS:
        x, y = int(rx * ms), int(ry * ms)
        w, h = max(1, int(rw * ms)), max(1, int(rh * ms))
        # 粗彩色框
        cv2.rectangle(disp, (x, y), (x + w, y + h), (0, 255, 0), 2)
        # 半透明填充
        overlay = disp.copy()
        cv2.rectangle(overlay, (x, y), (x + w, y + h), (0, 255, 0), -1)
        disp = cv2.addWeighted(disp, 0.85, overlay, 0.15, 0)
        # 标签: 名字 + 当前OCR值
        val = status.get(name, "?")
        label = f"{name}:{val}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        # 标签背景
        ly = y - 4 if y - 4 > th else y + h + th + 4
        cv2.rectangle(disp, (x, ly - th - 2), (x + tw + 4, ly + 2), (0, 0, 0), -1)
        cv2.rectangle(disp, (x, ly - th - 2), (x + tw + 4, ly + 2), (0, 255, 0), 1)
        cv2.putText(disp, label, (x + 2, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

    # ---- HP ROI (红色粗框) ----
    hx, hy, hw_, hh = HP_ROI
    cx, cy = int(hx * ms), int(hy * ms)
    cw, ch = max(1, int(hw_ * ms)), max(1, int(hh * ms))
    cv2.rectangle(disp, (cx, cy), (cx + cw, cy + ch), (0, 100, 255), 2)
    hp_val = status.get("HP", "?")
    hp_label = f"HP:{hp_val}"
    cv2.putText(disp, hp_label, (cx + cw + 4, cy + 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 100, 255), 1)

    # ---- "开" ROI (黄色粗框) ----
    ox, oy, ow, oh = OPEN_ROI
    cv2.rectangle(disp, (int(ox * ms), int(oy * ms)),
                  (int((ox + ow) * ms), int((oy + oh) * ms)), (0, 255, 255), 2)
    cv2.putText(disp, "Open", (int(ox * ms), int(oy * ms) - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)

    # ---- 食物 Tooltip OCR 区域 (亮黄色粗框, 最重要!) ----
    fx, fy, fw, fh = FOOD_OCR_ROI
    ftx, fty = int(fx * ms), int(fy * ms)
    ftw, fth = max(1, int(fw * ms)), max(1, int(fh * ms))
    # 闪烁效果 (扫描时红色, 否则亮黄)
    if scanning:
        food_col = (0, 0, 255)  # 红色=正在扫描
    else:
        food_col = (0, 255, 255)  # 亮黄=待命
    cv2.rectangle(disp, (ftx, fty), (ftx + ftw, fty + fth), food_col, 3)
    # 半透明填充
    overlay = disp.copy()
    cv2.rectangle(overlay, (ftx, fty), (ftx + ftw, fty + fth), food_col, -1)
    disp = cv2.addWeighted(disp, 0.8, overlay, 0.2, 0)
    # 标签
    cv2.putText(disp, "Tooltip OCR", (ftx, fty - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, food_col, 2)

    # 食物格子点击位 (小黄点)
    for i, (slot_name, sx_val, sy_val, _) in enumerate(FOOD_SLOTS):
        sx = int(sx_val * ms)
        sy_ = int(sy_val * ms)
        is_cur = (scanning and len(scan_results) == i)
        col = (0, 0, 255) if is_cur else (0, 200, 255)
        cv2.circle(disp, (sx, sy_), 4, col, -1)
        cv2.putText(disp, slot_name[-3:], (sx + 6, sy_ + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, col, 1)

    canvas[:mh, :mw] = disp

    # ---- 右侧面板 (PIL 渲染中文) ----
    pil = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)

    rx_base = mw + 12  # 右侧起始x
    ry = 8

    # ---- 区块1: 状态OCR (含ROI坐标) ----
    draw.text((rx_base, ry), "◆ 角色状态 (ROI坐标)", font=_FONT_MD, fill=(0, 255, 0))
    ry += 26
    roi_map = {r[0]: r for r in OCR_REGIONS}
    for key in ["Hunger", "Thirst", "HP", "Exp", "Stamina", "Threat"]:
        val = status.get(key, "?")
        color = (0, 255, 0)
        if key == "Hunger":
            color = (255, 180, 0)
        elif key == "Thirst":
            color = (100, 180, 255)
        elif key == "HP":
            color = (0, 255, 100)
        # 显示ROI坐标
        coord_str = ""
        if key in roi_map:
            _, crx, cry, crw, crh = roi_map[key]
            coord_str = f"  ({crx},{cry}) {crw}x{crh}"
        elif key == "HP":
            coord_str = f"  ({HP_ROI[0]},{HP_ROI[1]}) {HP_ROI[2]}x{HP_ROI[3]}"
        draw.text((rx_base, ry), f"{key}: {val}{coord_str}", font=_FONT_SM, fill=color)
        ry += 19

    # Open ROI
    ox, oy, ow, oh = OPEN_ROI
    draw.text((rx_base, ry), f"Open: ({ox},{oy}) {ow}x{oh}",
              font=_FONT_SM, fill=(0, 255, 255))
    ry += 19

    # ---- 区块2: 补给扫描结果 ----
    ry += 6
    draw.text((rx_base, ry), "◆ 补给扫描", font=_FONT_MD, fill=(255, 255, 0))
    ry += 26
    # Food OCR ROI 坐标
    fx, fy, fw, fh = FOOD_OCR_ROI
    draw.text((rx_base, ry), f"Tooltip ROI: ({fx},{fy}) {fw}x{fh}",
              font=_FONT_SM, fill=(0, 255, 255))
    ry += 18
    for i, (slot_name, sx_val, sy_val, _) in enumerate(FOOD_SLOTS):
        mark = ""
        color = (160, 160, 160)
        if scan_results and i < len(scan_results):
            r = scan_results[i]
            if r['type']:
                parts = []
                if r['food']: parts.append(f"食x{r['food']}")
                if r['water']: parts.append(f"水x{r['water']}")
                mark = f" → {' '.join(parts)}"
                color = (255, 200, 0)
            else:
                mark = " → -"
        draw.text((rx_base, ry), f"{slot_name}{mark}", font=_FONT_SM, fill=color)
        ry += 15

    # ---- 区块3: 决策引擎 ----
    ry += 6
    draw.text((rx_base, ry), "◆ 决策引擎", font=_FONT_MD, fill=(255, 100, 255))
    ry += 24
    if decision:
        d_type, d_item, d_reason = decision
        if d_type == "eat":
            draw.text((rx_base, ry), f"✅ 吃: {d_item['name']}", font=_FONT_SM, fill=(0, 255, 0))
            ry += 18
            draw.text((rx_base, ry), f"   {d_reason}", font=_FONT_SM, fill=(200, 200, 200))
        elif d_type == "leave":
            draw.text((rx_base, ry), "🚪 离开火堆", font=_FONT_SM, fill=(255, 100, 100))
            ry += 18
            draw.text((rx_base, ry), f"   {d_reason}", font=_FONT_SM, fill=(200, 200, 200))
        else:
            draw.text((rx_base, ry), "— 等待扫描", font=_FONT_SM, fill=(150, 150, 150))
    else:
        draw.text((rx_base, ry), "— 等待扫描", font=_FONT_SM, fill=(150, 150, 150))
        ry += 18

    # ---- 区块4: 点击测试面板 ----
    ry += 28
    draw.text((rx_base, ry), "◆ 点击测试", font=_FONT_MD, fill=(200, 200, 200))
    ry += 24

    # ---- 按钮 (PIL 画矩形+中文标签) ----
    for label, bx, by_, bw, bh, name, ds in BUTTONS:
        p = click_pts[name]
        txt = f"{label} ({p['x']},{p['y']})"
        # PIL 画按钮背景 + 边框
        draw.rectangle([bx, by_, bx + bw, by_ + bh], fill=(60, 60, 60), outline=(0, 180, 0))
        # PIL 画按钮文字（支持中文）
        draw.text((bx + 3, by_ + 3), txt, font=_FONT_BTN, fill=(0, 220, 0))

    # 模式指示
    mode_str = f"模式: {MODES[action_mode]}"
    draw.text((rx_base, PANEL_H - 28), mode_str, font=_FONT_MD,
              fill=MODE_COLORS[action_mode])

    # ---- 底部状态栏 (PIL 中文) ----
    draw.text((10, PANEL_H - 22), scan_msg, font=_FONT_SM, fill=(255, 255, 255))

    # ---- PIL → cv2 转换 ----
    canvas = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

    cv2.imshow("SupplyTestPanel", canvas)
    key = cv2.waitKey(100) & 0xFF

    # ===================== 键盘处理 =====================
    if key == 0 or key == 255:
        pass  # 无按键
    elif key == ord('q') or key == ord('Q') or key == 27:  # Q / ESC
        break

    elif key == ord('t') or key == ord('T'):
        # 单次OCR测试
        ret, f = cap.read()
        if ret:
            print("\n--- OCR 测试 ---")
            st = read_status(f)
            print(f"  状态: {st}")
            print(f"  OBS: {f.shape[1]}x{f.shape[0]}")
            for name, rx, ry, rw, rh in OCR_REGIONS:
                print(f"  {name}: ROI({rx},{ry}) {rw}x{rh}")
            print(f"  Open ROI: {OPEN_ROI}")
            is_open = detect_open(f)
            print(f"  '开'检测: {is_open}")
            print("--- 测试完毕 ---\n")

    elif key == ord('c') or key == ord('C') or key == ord('1'):
        action_mode = 0
        print(f"[模式] CLICK (点击)")

    elif key == ord('h') or key == ord('H') or key == ord('2'):
        action_mode = 1
        print(f"[模式] HOVER (悬停)")

    elif key == ord('d') or key == ord('D') or key == ord('3') or key == ord('g') or key == ord('G'):
        action_mode = 2
        print(f"[模式] DRAG (拖拽)  keycode={key}")

    elif (key == ord('s') or key == ord('S')) and not scanning:
        # ===== 开始补给扫描 =====
        scanning = True
        scan_msg = "扫描中..."
        scan_results = []
        decision = None

        print("\n" + "=" * 50)
        print("  开始补给扫描")
        print("=" * 50)

        # Step 1: 确认火堆
        ret, f = cap.read()
        if ret and detect_open(f):
            print("[✓] 确认在火堆 ('开' 已检测)")
        else:
            print("[!] 警告: 未检测到'开'字")

        # Step 2: 读取状态
        ret, f = cap.read()
        if ret:
            status = read_status(f)
            print(f"[状态] {status}")

        # Step 3: 扫描8格
        for slot_name, sx_val, sy_val, drag_start_y in FOOD_SLOTS:
            scan_msg = f"扫描 {slot_name}..."
            print(f"[扫描] {slot_name} ({sx_val},{sy_val})")

            # 扫描间清缓冲 (模拟step_test主循环的cap.read效果)
            deadline = time.time() + 0.3
            while time.time() < deadline:
                cap.grab()
                cv2.waitKey(1)
            cap.retrieve()
            # 刷新UI
            cv2.imshow("SupplyTestPanel", canvas)
            cv2.waitKey(1)

            item_type, food_qty, water_qty, raw = scan_food_slot(slot_name, sx_val, sy_val, drag_start_y)
            result = {"slot": slot_name, "type": item_type,
                      "food": food_qty, "water": water_qty, "raw": raw}
            scan_results.append(result)

            if item_type:
                parts = []
                if food_qty: parts.append(f"食物 x{food_qty}")
                if water_qty: parts.append(f"水 x{water_qty}")
                print(f"  ✅ {' | '.join(parts)}  raw='{raw}'")
            else:
                print(f"  -  空  raw='{raw}'")

        # Step 4: 决策
        hunger_val = int(status.get("Hunger", "0")) if status.get("Hunger", "?").isdigit() else 0
        thirst_val = int(status.get("Thirst", "0")) if status.get("Thirst", "?").isdigit() else 0

        items_for_decision = []
        for r in scan_results:
            if r['type']:
                slot_idx = [s[0] for s in FOOD_SLOTS].index(r['slot'])
                slot_info = FOOD_SLOTS[slot_idx]
                items_for_decision.append({
                    "name": r['slot'],
                    "food": r['food'] or 0,
                    "water": r['water'] or 0,
                    "slot": r['slot'],
                    "x": slot_info[1],
                    "y": slot_info[2],
                    "drag_start": slot_info[3],
                })

        decision = decide_food({"Hunger": hunger_val, "Thirst": thirst_val}, items_for_decision)
        print(f"\n[决策] {decision[2]}")
        if decision[0] == "eat":
            print(f"  → 推荐: {decision[1]['name']} food+{decision[1]['food']} water+{decision[1]['water']}")

        scan_msg = f"扫描完成! {len([r for r in scan_results if r['type']])}个物品 | {decision[2]}"
        scanning = False
        print("=" * 50 + "\n")

# ===================== 清理 =====================
cap.release()
cv2.destroyAllWindows()
print("[退出] 面板已关闭")
