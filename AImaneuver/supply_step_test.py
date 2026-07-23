"""
补给扫描 - 手动逐步测试
Enter = 拖拽当前格子+OCR并自动跳到下一格  /  N/P=手动切换  Q=退出
"""
import cv2, numpy as np, json, os, time, re, easyocr
import win32gui, win32api, win32con
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(__file__)
FOOD_OCR_ROI_FILE = os.path.join(BASE, "food_ocr_roi.json")
OBS_CAM_ID = 1

# ---- 字体 ----
_FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
_FONT = ImageFont.truetype(_FONT_PATH, 16)
_FONT_BIG = ImageFont.truetype(_FONT_PATH, 20)

# ---- 找窗口 ----
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
print(f"hwnd=0x{hwnd:08X}")

# ---- OBS ----
cap = cv2.VideoCapture(OBS_CAM_ID, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
ret, test = cap.read()
if not ret: print("OBS未开!"); exit()
obs_w, obs_h = test.shape[1], test.shape[0]
print(f"OBS {obs_w}x{obs_h}")

# ---- OCR ----
ocr_zh = easyocr.Reader(["ch_sim"], gpu=True)
print("EasyOCR 就绪")

# ---- Food OCR ROI ----
FOOD_OCR_ROI = [1016, 436, 298, 164]
if os.path.exists(FOOD_OCR_ROI_FILE):
    FOOD_OCR_ROI = json.load(open(FOOD_OCR_ROI_FILE))
print(f"Food OCR ROI: {FOOD_OCR_ROI}")

# ---- 食物栏8格 ----
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

# ---- 后台操作 ----
def bg_drag(x1, y1, x2, y2, steps=10, step_time=0.03):
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

# ---- 状态 ----
cur_idx = 0
results = [None] * 8
status_msg = "就绪 | Enter=拖拽+OCR(自动下一格)  N/P=切换  Q=退出"

cv2.namedWindow("StepTest", cv2.WINDOW_NORMAL)
cv2.resizeWindow("StepTest", 900, 550)

def do_scan(idx):
    global cur_idx, status_msg
    name, sx, sy, start_y = FOOD_SLOTS[idx]

    t0 = time.time()

    # Step 1: 拖动
    print(f"\n[拖拽] {name} ({sx},{start_y})→({sx},{sy})  t=0.0s")
    bg_drag(sx, start_y, sx, sy)
    print(f"  拖拽完成  t={time.time()-t0:.1f}s")

    # Step 2: 等待 + 倒计时 (每秒检查帧是否真的更新)
    last_hash = None
    for sec in range(1, 0, -1):
        status_msg = f"{name}: OCR倒计时 {sec}s..."
        print(f"  OCR倒计时 {sec}s...")
        # 持续 drain + 泵消息
        deadline = time.time() + 0.8
        while time.time() < deadline:
            cap.grab()
            cv2.waitKey(1)
        # 拿一帧检查是否变化
        ret, test_f = cap.retrieve()
        if ret:
            fh = hash(test_f.tobytes()[:2000])
            tag = "变化" if fh != last_hash else "未变!!!"
            ts = time.strftime('%H:%M:%S')
            print(f"    [{ts}] 倒计时{sec}s hash={fh & 0xFFFF:04x} {tag}")
            last_hash = fh

    # Step 3: OCR! 先 grab 最新帧再 retrieve
    ocr_time = time.time() - t0
    print(f"  [OCR!] t={ocr_time:.1f}s  {time.strftime('%H:%M:%S')}")
    for _ in range(10):
        cap.grab()
        cv2.waitKey(1)
    ret, f = cap.retrieve()
    if not ret:
        print(f"  ❌ cap failed")
        status_msg = f"{name}: cap failed"
        cur_idx = min(7, cur_idx + 1)
        return

    # 保存 OCR 瞬间的全帧截图
    os.makedirs(os.path.join(BASE, "debug_step"), exist_ok=True)
    cv2.imwrite(os.path.join(BASE, "debug_step", f"{name}_FULL.png"), f)

    # 裁剪 tooltip ROI 并保存
    fx, fy, fw, fh = [int(v) for v in FOOD_OCR_ROI]
    fx = max(0, min(fx, obs_w - 2)); fy = max(0, min(fy, obs_h - 2))
    fw = min(fw, obs_w - fx); fh = min(fh, obs_h - fy)
    roi = f[fy:fy + fh, fx:fx + fw]
    cv2.imwrite(os.path.join(BASE, "debug_step", f"{name}_ROI.png"), roi)

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    big = cv2.resize(gray, (fw * 3, fh * 3), interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    enhanced = clahe.apply(big)
    r = ocr_zh.readtext(enhanced, detail=1)
    txt = " ".join([line[1] for line in r]) if r else ""

    # OCR 模糊匹配: 食→贪/饮 物→钩/饭 都是常见误读
    item_type = None; qty = None
    if re.search(r'[食贪饮][物钩饭]', txt) or re.search(r'食\S', txt):
        item_type = "食物"
    elif "水" in txt:
        item_type = "水"
    # 提取食物/水后面的数字: "食物 +20" "水+46" "食钩 +20" "贪物 +95"
    m = re.search(r'(?:[食贪饮][物钩饭]|水)\s*[+~-]?\s*(\d+)', txt)
    if m: qty = int(m.group(1))
    elif not item_type:
        nums = re.findall(r'\d+', txt)
        if nums: qty = int(nums[0])

    results[idx] = {"slot": name, "type": item_type, "qty": qty, "raw": txt}
    tag = f"{item_type} x{qty}" if item_type else "空"
    print(f"  [{tag}] raw='{txt[:100]}'")
    status_msg = f"{name}: {tag}"

    # 自动跳下一格
    if cur_idx < 7:
        cur_idx += 1
        status_msg += f"  → 下一格: {FOOD_SLOTS[cur_idx][0]}"


while True:
    ret, frame = cap.read()
    if not ret: time.sleep(0.01); continue

    mw, mh = 600, int(600 * obs_h / obs_w)
    disp = cv2.resize(frame, (mw, mh))
    ms = mw / obs_w

    # Food OCR ROI 黄色框
    fx, fy, fw, fh = FOOD_OCR_ROI
    cv2.rectangle(disp, (int(fx*ms), int(fy*ms)),
                  (int((fx+fw)*ms), int((fy+fh)*ms)), (0, 255, 255), 2)

    # 8个格子
    for i, (name, sx, sy, _) in enumerate(FOOD_SLOTS):
        cx, cy = int(sx * ms), int(sy * ms)
        col = (0, 0, 255) if i == cur_idx else (255, 150, 0)
        rad = 7 if i == cur_idx else 4
        cv2.circle(disp, (cx, cy), rad, col, -1)

    canvas = np.zeros((550, 900, 3), dtype=np.uint8)
    canvas[:mh, :mw] = disp

    # ---- PIL 渲染所有中文 ----
    pil = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)

    # 左侧标注
    draw.text((int(fx*ms)+2, int(fy*ms)+2), "Tooltip OCR", font=_FONT, fill=(0, 255, 255))
    for i, (name, sx, sy, _) in enumerate(FOOD_SLOTS):
        col = (255, 50, 50) if i == cur_idx else (255, 200, 100)
        draw.text((int(sx*ms)+10, int(sy*ms)-8), name, font=_FONT, fill=col)

    # 右侧结果列表
    rx = mw + 15
    draw.text((rx, 8), "扫描结果", font=_FONT_BIG, fill=(0, 255, 0))
    for i, (name, _, _, _) in enumerate(FOOD_SLOTS):
        mark = "▶ " if i == cur_idx else "   "
        r = results[i]
        if r:
            tag = f"{r['type']} x{r['qty']}" if r['type'] else "-"
            col = (0, 255, 0) if r['type'] else (120, 120, 120)
        else:
            tag = "?"
            col = (150, 150, 150)
        draw.text((rx, 35 + i*22), f"{mark}{name}: {tag}", font=_FONT, fill=col)

    # 底部状态栏
    draw.text((10, 530), status_msg, font=_FONT, fill=(255, 255, 255))
    draw.text((10, 510), "Enter=拖拽+OCR(自动下一格)  N/P=切换  Q=退出",
              font=_FONT, fill=(150, 150, 150))

    canvas = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    cv2.imshow("StepTest", canvas)
    key = cv2.waitKey(100) & 0xFF

    if key == ord('q'): break
    elif key == 13:  # Enter
        do_scan(cur_idx)
    elif key in (ord('n'), ord('N')):
        cur_idx = min(7, cur_idx + 1)
        status_msg = f"当前: {FOOD_SLOTS[cur_idx][0]} | 按 Enter 拖拽+OCR"
    elif key in (ord('p'), ord('P')):
        cur_idx = max(0, cur_idx - 1)
        status_msg = f"当前: {FOOD_SLOTS[cur_idx][0]} | 按 Enter 拖拽+OCR"

cap.release()
cv2.destroyAllWindows()
