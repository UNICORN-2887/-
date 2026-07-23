"""
火堆补给检测 - 独立测试脚本
确认在火堆("开")状态 → 读取状态 → 拖拽扫8个食物栏 → OCR食物/水+数量

S=开始扫描  Q=退出
"""

import cv2, numpy as np, json, os, time, easyocr
import win32gui, win32api, win32con
from ultralytics import YOLO
from PIL import Image, ImageDraw, ImageFont

# 中文字体 (Windows)
_FONT_PATH = "C:/Windows/Fonts/msyh.ttc"  # 微软雅黑
_FONT_SM = ImageFont.truetype(_FONT_PATH, 16)
_FONT_MD = ImageFont.truetype(_FONT_PATH, 20)
_FONT_LG = ImageFont.truetype(_FONT_PATH, 26)

def put_text_cn(img, text, pos, font=_FONT_SM, color=(0, 255, 0)):
    """在cv2图片上画中文 (PIL渲染)"""
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    draw.text(pos, text, font=font, fill=color)
    rgb = np.array(pil)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    img[:] = bgr

# ========== 配置 ==========
OBS_CAM_ID = 1
MODEL_PATH = os.path.join(os.path.dirname(__file__),
    "runs", "detect", "deadmaze_combat", "weights", "best.pt")
CLICK_FILE = os.path.join(os.path.dirname(__file__), "click_points.json")
OFFSET_FILE = os.path.join(os.path.dirname(__file__), "click_offset.json")
OCR_ROI_FILE = os.path.join(os.path.dirname(__file__), "ocr_reader_roi.json")
HP_ROI_FILE = os.path.join(os.path.dirname(__file__), "hp_detector_roi.json")

# 食物栏8个格子 (名称, x, y, 拖拽起始x)
FOOD_SLOTS = [
    ("食物1-1", 885, 383, 1020),
    ("食物1-2", 900, 383, 1020),
    ("食物1-3", 950, 383, 1020),
    ("食物1-4", 970, 383, 1020),
    ("食物2-1", 885, 423, 1020),
    ("食物2-2", 900, 423, 1020),
    ("食物2-3", 950, 423, 1020),
    ("食物2-4", 970, 423, 1020),
]

DRAG_STEP_TIME = 0.03      # 拖拽每步间隔
DRAG_STEPS = 10            # 拖拽分几步
WAIT_AFTER_DRAG = 3.0      # 拖拽后等待OCR时间

# ========== 找游戏窗口 ==========
def find_game():
    results = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h) == 'Dead Maze':
            r = win32gui.GetWindowRect(h)
            if r[2] - r[0] > 800: results.append(h)
    win32gui.EnumWindows(cb, None)
    return results[0] if results else None

hwnd = find_game()
if not hwnd: print("未找到 Dead Maze!"); exit()
if win32gui.IsIconic(hwnd):
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE); time.sleep(0.2)
print(f"[Game] hwnd=0x{hwnd:08X}")

# 加载偏移
dx, dy = 0, 0
if os.path.exists(OFFSET_FILE):
    d = json.load(open(OFFSET_FILE))
    dx, dy = d.get('dx', 0), d.get('dy', 0)
    print(f"[偏移] dx={dx} dy={dy}")

# ========== OBS ==========
cap = cv2.VideoCapture(OBS_CAM_ID, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
ret, test = cap.read()
if not ret: print("OBS未开!"); exit()
obs_w, obs_h = test.shape[1], test.shape[0]
print(f"[OBS] {obs_w}x{obs_h}")

# ========== 模型 ==========
yolo = YOLO(MODEL_PATH)
ocr_en = easyocr.Reader(["en"], gpu=True)
ocr_zh = easyocr.Reader(["ch_sim"], gpu=True)
print("[模型] YOLO + EasyOCR(en+ch) 就绪")

# ========== 加载状态ROI ==========
OCR_REGIONS = [
    ("Exp", 972, 1053, 50, 25),
    ("Hunger", 1715, 1055, 50, 25),
    ("Thirst", 1632, 1057, 50, 25),
    ("Stamina", 1551, 1059, 50, 25),
    ("Threat", 898, 1056, 50, 25),
]
OPEN_ROI = [300, 300, 40, 30]  # "开"字检测区域

if os.path.exists(OCR_ROI_FILE):
    saved = json.load(open(OCR_ROI_FILE))
    print(f"[加载] ocr_reader_roi.json: {len(saved)} 区域")
    for r in saved:
        name = r[0]
        for i, orig in enumerate(OCR_REGIONS):
            if orig[0] == name:
                OCR_REGIONS[i] = tuple(r[:5])
                print(f"  {name}: ({r[1]},{r[2]}) {r[3]}x{r[4]}")
                break
        if name == "Open":
            OPEN_ROI = [int(r[1]), int(r[2]), int(r[3]), int(r[4])]
            print(f"  Open: ({OPEN_ROI[0]},{OPEN_ROI[1]}) {OPEN_ROI[2]}x{OPEN_ROI[3]}")

HP_ROI = [956, 336, 102, 4]
if os.path.exists(HP_ROI_FILE):
    HP_ROI = json.load(open(HP_ROI_FILE))
    print(f"[加载] hp_detector_roi.json: {HP_ROI}")

GREEN_LOW = np.array([35, 40, 40])
GREEN_HIGH = np.array([85, 255, 255])

print(f"[状态ROI] {len(OCR_REGIONS)} 状态 + HP + Open")

# ========== 窗口 ==========
cv2.namedWindow("SupplyCheck", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("SupplyCheck", cv2.WND_PROP_TOPMOST, 1)
cv2.resizeWindow("SupplyCheck", 900, 650)
FONT = cv2.FONT_HERSHEY_SIMPLEX

status = {}          # OCR状态结果
scan_results = []    # 食物扫描结果
scanning = False
scan_msg = "按 S 开始扫描补给"

# ========== 工具函数 ==========
def read_status(frame):
    """读取所有OCR状态 + HP"""
    s = {}
    for name, rx, ry, rw, rh in OCR_REGIONS:
        roi = frame[ry:ry+rh, rx:rx+rw]
        if roi.size == 0:
            s[name] = "?"
            continue
        # 放大 + 转灰度 + 自适应二值化提高识别率
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        big = cv2.resize(gray, (rw*6, rh*6), interpolation=cv2.INTER_CUBIC)
        # CLAHE 增强对比度
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4,4))
        enhanced = clahe.apply(big)
        r = ocr_en.readtext(enhanced, detail=1, allowlist="0123456789xp")
        txt = r[0][1] if r else "?"
        s[name] = txt

    # HP
    hx, hy, hw, hh = [max(1, v) for v in HP_ROI]
    hp_roi = frame[hy:hy+hh, hx:hx+hw]
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
    """检测画面中是否有'开'字 (使用标定的OPEN_ROI)"""
    ox, oy, ow, oh = OPEN_ROI
    roi = frame[oy:oy+oh, ox:ox+ow]
    if roi.size == 0: return False
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    big = cv2.resize(gray, (ow*5, oh*5), interpolation=cv2.INTER_CUBIC)
    # 直接灰度识别 (不二值化, 避免丢失信息)
    txt_list = ocr_zh.readtext(big, detail=0)
    txt = " ".join(txt_list)
    print(f"  [Open检测] raw='{txt}'")
    return any("开" in t for t in txt_list)

def drag_to(x1, y1, x2, y2):
    """后台拖拽: (x1,y1) → (x2,y2)"""
    # mousedown at start
    lp = win32api.MAKELONG(x1, y1)
    win32api.SendMessage(hwnd, win32con.WM_LBUTTONDOWN, 0, lp)
    time.sleep(0.02)
    # 分步移动
    for i in range(1, DRAG_STEPS + 1):
        cx = int(x1 + (x2 - x1) * i / DRAG_STEPS)
        cy = int(y1 + (y2 - y1) * i / DRAG_STEPS)
        lp = win32api.MAKELONG(cx, cy)
        win32api.SendMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lp)
        time.sleep(DRAG_STEP_TIME)
    # mouseup at end
    lp = win32api.MAKELONG(x2, y2)
    win32api.SendMessage(hwnd, win32con.WM_LBUTTONUP, 0, lp)
    time.sleep(0.02)

def scan_food_slot(frame, slot_name, sx, sy, dx_start):
    """拖拽扫一个食物格子，OCR检测食物/水+数量"""
    # 拖拽
    drag_to(dx_start, sy, sx, sy)
    time.sleep(WAIT_AFTER_DRAG)

    # 抓帧OCR (tooltip区域: 食物栏附近)
    ret, f = cap.read()
    if not ret:
        return None, None, None

    # Tolltip 通常出现在格子左上方, OCR 一个较大区域
    tx1 = max(0, sx - 200)
    ty1 = max(0, sy - 80)
    tx2 = min(obs_w, sx + 50)
    ty2 = min(obs_h, sy + 50)
    roi = f[ty1:ty2, tx1:tx2]
    if roi.size == 0:
        return None, None, None

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    big = cv2.resize(gray, ((tx2-tx1)*3, (ty2-ty1)*3),
                     interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4,4))
    enhanced = clahe.apply(big)
    r = ocr_zh.readtext(enhanced, detail=1)
    txt = " ".join([line[1] for line in r]) if r else ""

    # 检测食物/水
    item_type = None
    if "食物" in txt:
        item_type = "食物"
    elif "水" in txt:
        item_type = "水"

    # 提取数字 (绝对值)
    quantity = None
    import re
    nums = re.findall(r'\d+', txt)
    if nums:
        quantity = int(nums[0])

    return item_type, quantity, txt

# ========== 主循环 ==========
last_frame = None
yolo_frame = None
last_yolo = 0
last_status = 0  # 独立的状态更新计时器

while True:
    ret, frame = cap.read()
    if not ret:
        time.sleep(0.01)
        continue
    now = time.time()

    # YOLO (每1秒)
    if now - last_yolo > 1.0:
        det = yolo(frame, verbose=False, conf=0.3)[0]
        yolo_frame = det.plot()
        last_yolo = now

    # 读取状态 (每2秒, 不扫描时)
    if not scanning and now - last_status > 2.0:
        status = read_status(frame)
        last_status = now
        last_frame = frame

    # ===== 渲染 =====
    canvas = np.zeros((650, 900, 3), dtype=np.uint8)

    # 左侧: OBS+YOLO (缩小)
    mw, mh = 500, int(500 * obs_h / obs_w)
    if yolo_frame is not None:
        disp = cv2.resize(yolo_frame, (mw, mh))
    else:
        disp = cv2.resize(frame, (mw, mh))

    ms = mw / obs_w  # OBS → 显示缩放比

    # 绿框: 状态OCR区域
    for name, rx, ry, rw, rh in OCR_REGIONS:
        x, y = int(rx * ms), int(ry * ms)
        w, h = max(1, int(rw * ms)), max(1, int(rh * ms))
        cv2.rectangle(disp, (x, y), (x + w, y + h), (0, 255, 0), 1)

    # 绿框: HP区域
    hx, hy, hw, hh = HP_ROI
    cv2.rectangle(disp,
                 (int(hx * ms), int(hy * ms)),
                 (int((hx + hw) * ms), int((hy + hh) * ms)),
                 (0, 255, 0), 1)

    # 绿框: "开" 检测区域
    ox, oy, ow, oh = OPEN_ROI
    cv2.rectangle(disp, (int(ox * ms), int(oy * ms)),
                 (int((ox + ow) * ms), int((oy + oh) * ms)), (0, 255, 0), 1)

    # 8个食物格子的OCR扫描区（黄框, 半透明）
    for i, (slot_name, sx_val, sy_val, _) in enumerate(FOOD_SLOTS):
        tx1 = max(0, int((sx_val - 200) * ms))
        ty1 = max(0, int((sy_val - 80) * ms))
        tx2 = min(mw, int((sx_val + 50) * ms))
        ty2 = min(mh, int((sy_val + 50) * ms))
        is_cur = (scanning and len(scan_results) == i)
        col = (0, 0, 255) if is_cur else (120, 120, 80)  # 当前红色, 其他暗黄
        thick = 2 if is_cur else 1
        cv2.rectangle(disp, (tx1, ty1), (tx2, ty2), col, thick)

    canvas[:mh, :mw] = disp

    # ===== 右侧面板 — PIL 渲染中文 =====
    pil = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    sx = mw + 15

    draw.text((sx, 20), "=== 状态 ===", font=_FONT_MD, fill=(0, 255, 0))
    sy = 52
    for key in ["Exp", "Hunger", "Thirst", "Stamina", "Threat", "HP"]:
        val = status.get(key, "?")
        draw.text((sx, sy), f"{key}: {val}", font=_FONT_SM, fill=(0, 255, 0))
        sy += 22

    sy += 8
    draw.text((sx, sy), "=== 补给扫描 (OCR区) ===", font=_FONT_MD, fill=(255, 255, 0))
    sy += 25
    for i, (slot_name, sx_val, sy_val, _) in enumerate(FOOD_SLOTS):
        tx1 = max(0, sx_val - 200)
        ty1 = max(0, sy_val - 80)
        tx2 = max(0, sx_val + 50)
        ty2 = max(0, sy_val + 50)
        mark = ""
        if scan_results and i < len(scan_results):
            r = scan_results[i]
            if r['type']:
                mark = f" → {r['type']} x{r['qty']}"
            else:
                mark = " → -"
        draw.text((sx, sy), f"{slot_name}: OCR({tx1},{ty1})-({tx2},{ty2}){mark}",
                 font=_FONT_SM, fill=(200, 200, 200) if not mark else (255, 200, 0))
        sy += 12

    # 底部状态
    draw.text((10, 632), scan_msg, font=_FONT_MD, fill=(255, 255, 255))
    draw.text((10, 608), "S=扫描  T=OCR测试  Q=退出", font=_FONT_SM, fill=(150, 150, 150))

    canvas = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

    cv2.imshow("SupplyCheck", canvas)
    key = cv2.waitKey(100) & 0xFF

    if key == ord('q'):
        break
    elif key in (ord('t'), ord('T')):
        # 单次OCR测试: 打印所有状态 + "开"原始结果
        ret, f = cap.read()
        if ret:
            print("\n--- OCR 测试 ---")
            st = read_status(f)
            print(f"  状态: {st}")
            print(f"  OBS: {f.shape[1]}x{f.shape[0]}")
            for name, rx, ry, rw, rh in OCR_REGIONS:
                print(f"  {name}: ROI({rx},{ry}) {rw}x{rh}")
            print(f"  Open ROI: {OPEN_ROI}")
            detect_open(f)
            print("--- 测试完毕 ---\n")
    elif key in (ord('s'), ord('S')) and not scanning:
        scanning = True
        scan_msg = "扫描中..."
        scan_results = []

        # Step 1: 确认在火堆状态
        ret, f = cap.read()
        if ret and detect_open(f):
            print("[✓] 确认在火堆状态 ('开' 已检测)")
        else:
            print("[!] 警告: 未检测到'开'字, 可能不在火堆")

        # Step 2: 读取当前状态
        ret, f = cap.read()
        if ret:
            status = read_status(f)
            print(f"[状态] {status}")

        # Step 3: 扫描8个食物格子
        for slot_name, sx_val, sy_val, drag_start in FOOD_SLOTS:
            scan_msg = f"扫描 {slot_name}..."
            print(f"[扫描] {slot_name} ({sx_val},{sy_val}) 拖拽...")
            cv2.imshow("SupplyCheck", canvas)
            cv2.waitKey(1)

            item, qty, raw = scan_food_slot(f, slot_name, sx_val, sy_val, drag_start)
            result = {"slot": slot_name, "type": item, "qty": qty, "raw": raw}
            scan_results.append(result)

            if item:
                print(f"  ✅ {item} x{qty}  raw='{raw}'")
            else:
                print(f"  -  空  raw='{raw}'")

            # 刷新渲染
            cv2.waitKey(1)

        scan_msg = f"扫描完成! {len([r for r in scan_results if r['type']])} 个物品"
        print(f"\n{'='*40}")
        print(f"扫描结果: {scan_msg}")
        for r in scan_results:
            if r['type']:
                print(f"  {r['slot']}: {r['type']} x{r['qty']}")
        print(f"{'='*40}\n")
        scanning = False

cap.release()
cv2.destroyAllWindows()
