"""Config Web Panel - Flask server"""
# ── 自动安装缺失依赖 ──
import subprocess as _sp, sys as _sys, importlib as _il
_AUTO_DEPS = {"flask": "flask", "cv2": "opencv-python", "numpy": "numpy",
    "pygrabber": "pygrabber", "easyocr": "easyocr", "pytesseract": "pytesseract"}
for _mod, _pkg in _AUTO_DEPS.items():
    try: _il.import_module(_mod)
    except ImportError:
        print(f"[自动安装] {_pkg}...")
        _sp.check_call([_sys.executable, "-m", "pip", "install", _pkg, "-q", "--user"])

import json, os, threading, time, ctypes, base64, socket
from ctypes import wintypes
from flask import Flask, render_template_string, request, jsonify

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

app = Flask(__name__)

@app.after_request
def _no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

CFG_FILE = os.path.join(os.path.dirname(__file__), "navigator_config.json")

DEFAULTS = {
    "waypoint_reach": 25, "deviation": 100, "move_dur": 0.5,
    "goal_reach": 100, "lookahead": 90, "zombie_range": 600,
    "attack_range": 130, "chase_timeout": 7, "low_stat_thr": 15,
    "heal_hp": 80, "escape_hp": 20, "combat_entry_hp": 70,
    "max_zombies": 6, "weapon_tol": 20, "weapon_thr": 0.3,
    "weapon_check": 15, "return_thr": 15,
    "skill1_cd": 4, "skill2_cd": 12, "skill3_cd": 22, "skill4_cd": 32,
    "launcher_path": "", "pushplus_token": "",
    "game_path": "", "obs_cam_id": 1,
}

def load_cfg():
    cfg = dict(DEFAULTS)
    if os.path.exists(CFG_FILE):
        with open(CFG_FILE) as f:
            saved = json.load(f)
        cfg.update(saved)  # 旧文件缺少的key用默认值
    return cfg

HTML = r'''
<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>DeadMaze Config</title>
<style>
  body{font:14px Arial;background:#1a1a2e;color:#eee;margin:0;padding:20px}
  h2{color:#0ff;border-bottom:1px solid #333;padding-bottom:5px;margin-top:20px}
  .row{display:flex;align-items:center;margin:8px 0;gap:12px}
  label{width:160px;font-weight:bold;color:#ccc}
  input[type=range]{flex:1;max-width:300px}
  input[type=number]{width:70px;background:#333;border:1px solid#555;color:#fff;padding:4px}
  .val{width:60px;text-align:right;color:#0f0}
  .desc{font-size:11px;color:#888;width:200px}
  .note{color:#f90;font-size:12px;margin:5px 0}
  button{background:#0a0;color:#fff;border:none;padding:10px 30px;font-size:16px;margin:20px 0;cursor:pointer}
  .status{color:#0f0;margin-left:10px}
</style></head><body>
<h1>DeadMaze 参数配置</h1>
<p class="note">⚠ 技能栏第2格必须放治疗技能 | 冷却时间=游戏CD+2秒 | 食物不超过8个否则OCR可能失效</p>

<h2>NAVIGATION 导航</h2>
<div class="row"><label>WP Reach (px)</label><input type="range" id="waypoint_reach" min="5" max="200"><span class="val"></span><input type="number"><span class="desc">到达途径点判定距离</span></div>
<div class="row"><label>Deviation (px)</label><input type="range" id="deviation" min="10" max="300"><span class="val"></span><input type="number"><span class="desc">偏离路径多远重规划</span></div>
<div class="row"><label>Move Dur (s)</label><input type="range" id="move_dur" min="0.05" max="3" step="0.05"><span class="val"></span><input type="number"><span class="desc">单次按键持续时长</span></div>
<div class="row"><label>Goal Reach (px)</label><input type="range" id="goal_reach" min="10" max="300"><span class="val"></span><input type="number"><span class="desc">到达终点判定距离</span></div>
<div class="row"><label>Lookahead (px)</label><input type="range" id="lookahead" min="10" max="300"><span class="val"></span><input type="number"><span class="desc">前向路标选择距离</span></div>

<h2>COMBAT 战斗</h2>
<div class="row"><label>Zombie Range (px)</label><input type="range" id="zombie_range" min="100" max="2000"><span class="val"></span><input type="number"><span class="desc">作战搜索半径</span></div>
<div class="row"><label>Attack Range (px)</label><input type="range" id="attack_range" min="20" max="500"><span class="val"></span><input type="number"><span class="desc">攻击距离</span></div>
<div class="row"><label>Chase Timeout (s)</label><input type="range" id="chase_timeout" min="1" max="30"><span class="val"></span><input type="number"><span class="desc">追击超时(超时换目标)</span></div>
<div class="row"><label>Combat Entry HP%</label><input type="range" id="combat_entry_hp" min="20" max="100"><span class="val"></span><input type="number"><span class="desc">血量高于此值才进战斗</span></div>
<div class="row"><label>Max Zombies</label><input type="range" id="max_zombies" min="1" max="20"><span class="val"></span><input type="number"><span class="desc">进入战斗的最大僵尸数</span></div>

<h2>STATUS 状态</h2>
<div class="row"><label>Low Stat Thr</label><input type="range" id="low_stat_thr" min="1" max="100"><span class="val"></span><input type="number"><span class="desc">H/T/S低于此值触发返航</span></div>
<div class="row"><label>Heal HP%</label><input type="range" id="heal_hp" min="20" max="100"><span class="val"></span><input type="number"><span class="desc">HP低于此值用skill_2补血</span></div>
<div class="row"><label>Escape HP%</label><input type="range" id="escape_hp" min="5" max="50"><span class="val"></span><input type="number"><span class="desc">HP低于此值空格脱战</span></div>
<div class="row"><label>Return Thr</label><input type="range" id="return_thr" min="1" max="100"><span class="val"></span><input type="number"><span class="desc">等同于Low Stat(O/P快捷键)</span></div>

<h2>SKILLS 技能冷却</h2>
<div class="row"><label>Skill 1 CD (s)</label><input type="range" id="skill1_cd" min="1" max="60"><span class="val"></span><input type="number"><span class="desc">技能1冷却(战斗技能)</span></div>
<div class="row"><label>Skill 2 CD (s)</label><input type="range" id="skill2_cd" min="1" max="60"><span class="val"></span><input type="number"><span class="desc">技能2冷却(治疗!放第2格)</span></div>
<div class="row"><label>Skill 3 CD (s)</label><input type="range" id="skill3_cd" min="1" max="60"><span class="val"></span><input type="number"><span class="desc">技能3冷却(战斗技能)</span></div>
<div class="row"><label>Skill 4 CD (s)</label><input type="range" id="skill4_cd" min="1" max="60"><span class="val"></span><input type="number"><span class="desc">技能4冷却(战斗技能)</span></div>

<h2>WEAPON 武器</h2>
<div class="row"><label>W Tolerance</label><input type="range" id="weapon_tol" min="5" max="100"><span class="val"></span><input type="number"><span class="desc">空槽颜色容差</span></div>
<div class="row"><label>W Threshold</label><input type="range" id="weapon_thr" min="0.05" max="0.9" step="0.05"><span class="val"></span><input type="number"><span class="desc">空槽判定阈值(高于此值=空)</span></div>
<div class="row"><label>W Check (s)</label><input type="range" id="weapon_check" min="5" max="60"><span class="val"></span><input type="number"><span class="desc">武器检测间隔</span></div>

<h2>NOTIFY 通知</h2>
<div class="row"><label>PushPlus Token</label><input type="text" id="pushplus_token" style="flex:1;max-width:400px;background:#333;border:1px solid#555;color:#fff;padding:4px" placeholder="留空则不推送"><span class="desc">停止时微信推送通知 (pushplus.plus)</span></div>

<h2>GAME 游戏设置</h2>
<div class="row"><label>游戏路径</label><input type="text" id="game_path" style="flex:1;max-width:400px;background:#333;border:1px solid#555;color:#fff;padding:4px" placeholder="DeadMaze.exe完整路径"><span class="desc">游戏本体exe路径，用于导航连接</span></div>

<h2>LAUNCHER 启动器</h2>
<div class="row"><label>加速器路径</label><input type="text" id="launcher_path" style="flex:1;max-width:400px;background:#333;border:1px solid#555;color:#fff;padding:4px" placeholder="留空则不启动"><span class="desc">加速版exe路径 (可选)</span></div>
<div style="margin:10px 0">
  <a href="/calibrate" target="_blank" style="color:#ff0;text-decoration:underline">→ 前往标定中心 (调整ROI位置)</a>
</div>
<button onclick="save_then_launch()" style="background:#e90;margin-top:5px">💾 保存并启动游戏</button><span class="status" id="launch_status"></span>

<button onclick="save()">SAVE CONFIG</button><span class="status" id="status"></span>
<button onclick="load_cfg()" style="background:#555;margin-left:10px">RELOAD</button>

<script>
const ids = ["waypoint_reach","deviation","move_dur","goal_reach","lookahead",
  "zombie_range","attack_range","chase_timeout","combat_entry_hp","max_zombies",
  "low_stat_thr","heal_hp","escape_hp","return_thr",
  "skill1_cd","skill2_cd","skill3_cd","skill4_cd",
  "weapon_tol","weapon_thr","weapon_check","launcher_path","pushplus_token","game_path"];
function sync(r){
  let n=r.nextElementSibling, v=parseFloat(r.value);
  n.textContent=v; r.nextElementSibling.nextElementSibling.value=v
}
ids.forEach(id=>{
  let r=document.getElementById(id);
  if(r.type==='range'){
    r.addEventListener('input',()=>sync(r));
    r.nextElementSibling.nextElementSibling.addEventListener('change',function(){
      r.value=this.value;sync(r)
    })
  }
});
async function load_cfg(){
  let r=await fetch('/get');let d=await r.json();
  ids.forEach(id=>{
    let el=document.getElementById(id);
    el.value=d[id];
    let strIds=['launcher_path','pushplus_token','game_path'];
    if(!strIds.includes(id))sync(el);
  })
}
async function save(){
  let d={};ids.forEach(id=>{
    let el=document.getElementById(id);
    let strIds=['launcher_path','pushplus_token','game_path'];
    d[id]=strIds.includes(id)?el.value:parseFloat(el.value)
  });
  let r=await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});
  document.getElementById('status').textContent='Saved!';
  setTimeout(()=>document.getElementById('status').textContent='',2000)
}
async function save_then_launch(){
  await save();
  let r=await fetch('/launch',{method:'POST'});
  let j=await r.json();
  document.getElementById('launch_status').textContent=j.ok||j.error;
  setTimeout(()=>document.getElementById('launch_status').textContent='',5000)
}
load_cfg();
</script></body></html>
'''

@app.route('/')
def index(): return render_template_string(HTML)

@app.route('/get')
def get_cfg(): return jsonify(load_cfg())

@app.route('/save', methods=['POST'])
def save_cfg():
    data = request.get_json()
    with open(CFG_FILE, 'w') as f: json.dump(data, f)
    return jsonify({"ok": True})

@app.route('/launch', methods=['POST'])
def launch_game():
    cfg = load_cfg()
    exe = cfg.get("launcher_path", "")
    if not exe or not os.path.exists(exe):
        return jsonify({"error": f"文件不存在: {exe}"})
    print(f"[Launcher] 启动: {exe}")

    # 确保 RUNASADMIN 标志 (该exe必需)
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers",
            0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, exe, 0, winreg.REG_SZ, "RUNASADMIN")
        winreg.CloseKey(key)
    except Exception:
        pass

    # 用 ShellExecuteEx 启动 (已验证可用)
    import ctypes.wintypes as wt
    class SEI(ctypes.Structure):
        _fields_ = [
            ("cbSize", wt.DWORD), ("fMask", wt.ULONG), ("hwnd", wt.HWND),
            ("lpVerb", wt.LPCWSTR), ("lpFile", wt.LPCWSTR),
            ("lpParameters", wt.LPCWSTR), ("lpDirectory", wt.LPCWSTR),
            ("nShow", ctypes.c_int), ("hInstApp", wt.HINSTANCE),
            ("lpIDList", wt.LPVOID), ("lpClass", wt.LPCWSTR),
            ("hkeyClass", wt.HKEY), ("dwHotKey", wt.DWORD),
            ("hIcon", wt.HANDLE), ("hProcess", wt.HANDLE),
        ]
    sei = SEI()
    sei.cbSize = ctypes.sizeof(SEI)
    sei.fMask = 0  # 不跟踪进程, 让exe独立运行
    sei.lpVerb = "open"
    sei.lpFile = exe
    sei.lpDirectory = os.path.dirname(exe)
    sei.nShow = 1  # SW_SHOWNORMAL
    ok = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))
    if not ok:
        err = ctypes.GetLastError()
        print(f"[Launcher] ShellExecuteEx 失败, 错误码={err}")
        return jsonify({"error": f"启动失败, 错误码={err}"})

    print(f"[Launcher] ShellExecuteEx 成功, hInstApp={sei.hInstApp}")
    # 后台线程发按键, 不阻塞HTTP响应
    threading.Thread(target=_launch_delayed_keys, daemon=True).start()
    return jsonify({"ok": "游戏已启动, 10秒后发送按键序列"})

def _launch_delayed_keys():
    """后台线程: 等10秒后发送按键序列"""
    time.sleep(10.0)
    try:
        _send_keys()
        print("[Launcher] 按键序列完成")
    except Exception as e:
        print(f"[Launcher] 按键序列失败: {e}")

def _send_keys():
    """SendInput 按键序列: Ins Del F1 F3×3 PgUp PgDn"""
    seq = [0x2D, 0x2E, 0x70, 0x72, 0x72, 0x72, 0x21, 0x22]
    user32 = ctypes.windll.user32
    class _KI(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]
    class _IU(ctypes.Union):
        _fields_ = [("ki", _KI), ("mi", ctypes.c_char * 32)]
    class _INP(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _IU)]
    def _send(vk):
        d = _INP(1, _IU(ki=_KI(vk, 0, 0, 0, None)))
        u = _INP(1, _IU(ki=_KI(vk, 0, 2, 0, None)))
        user32.SendInput(1, ctypes.byref(d), ctypes.sizeof(_INP))
        time.sleep(0.05)
        user32.SendInput(1, ctypes.byref(u), ctypes.sizeof(_INP))
    print(f"[Launcher] 按键序列: {[hex(v) for v in seq]}")
    for vk in seq:
        _send(vk)
        time.sleep(2.0)

# ============================================================
# 标定中心: /calibrate
# ============================================================
ROI_FILES = {
    "ocr_exp":     ("AImaneuver/ocr_reader_roi.json", "ocr", 0),
    "ocr_hunger":  ("AImaneuver/ocr_reader_roi.json", "ocr", 1),
    "ocr_thirst":  ("AImaneuver/ocr_reader_roi.json", "ocr", 2),
    "ocr_stamina": ("AImaneuver/ocr_reader_roi.json", "ocr", 3),
    "ocr_threat":  ("AImaneuver/ocr_reader_roi.json", "ocr", 4),
    "ocr_open":    ("AImaneuver/ocr_reader_roi.json", "ocr", 5),
    "hp":          ("AImaneuver/hp_detector_roi.json", "list", None),
    "weapon":      ("weapon_roi.json", "dict", None),
    "inventory":   ("AImaneuver/inventory_roi.json", "list", None),
    "food":        ("AImaneuver/food_ocr_roi.json", "list", None),
}

def _find_obs_cam():
    """返回OBS虚拟摄像头索引, 失败返回-1"""
    try:
        from pygrabber.dshow_graph import FilterGraph
        graph = FilterGraph()
        for i, name in enumerate(graph.get_input_devices()):
            if "obs" in name.lower():
                return i
    except Exception:
        pass
    return 0  # 回退到0

_live_cap = None  # 持久摄像头连接
_live_count = 0   # 帧计数器(调试)

def _capture_frame():
    """获取当前帧: 优先navigator共享截图 > 持久OBS摄像头"""
    global _live_cap, _live_count
    if not HAS_CV2:
        return None
    snap = os.path.join(os.path.dirname(__file__), "temp_snapshot.jpg")
    if os.path.exists(snap):
        # 只有被navigator活跃更新时才使用 (5秒内修改过)
        if time.time() - os.path.getmtime(snap) < 5:
            frame = cv2.imread(snap)
            if frame is not None:
                _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                return base64.b64encode(buf).decode()

    # 独立模式: 持久打开摄像头 (使用配置的ID)
    if _live_cap is None or not _live_cap.isOpened():
        cfg = load_cfg()
        cam_id = cfg.get("obs_cam_id", _find_obs_cam())
        print(f"[Camera] Opening camera #{cam_id}...")
        _live_cap = cv2.VideoCapture(cam_id, cv2.CAP_DSHOW)
        _live_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        _live_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        _live_count = 0
        # 预热
        for i in range(10):
            _live_cap.read()
        print(f"[Camera] Ready, warmed up 10 frames")

    if _live_cap.isOpened():
        # 读空缓冲取最新帧
        for _ in range(4):
            _live_cap.read()
        ret, frame = _live_cap.read()
        _live_count += 1
        if ret:
            if _live_count <= 3 or _live_count % 10 == 0:
                print(f"[Camera] Frame #{_live_count} ok, shape={frame.shape}")
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            return base64.b64encode(buf).decode()
        else:
            print(f"[Camera] Frame #{_live_count} FAILED")
    return None

def _load_rois():
    """加载所有ROI数据, 拆分为独立条目"""
    base = os.path.dirname(__file__)
    result = {}
    for key, (fname, fmt, idx) in ROI_FILES.items():
        fpath = os.path.join(base, fname)
        if not os.path.exists(fpath):
            result[key] = [0, 0, 50, 25] if fmt in ("ocr", "list") else {"roi": [0, 0, 30, 30], "tol": 20, "thr": 0.3}
            continue
        with open(fpath, encoding="utf-8") as f:
            raw = json.load(f)
        if fmt == "ocr":
            # raw = [[name, x, y, w, h, charset], ...]
            entry = raw[idx]
            result[key] = [entry[1], entry[2], entry[3], entry[4]]
        elif fmt == "list":
            result[key] = raw  # [x, y, w, h]
        elif fmt == "dict":
            result[key] = raw  # {"roi": [x,y,w,h], "tol": n, "thr": n}
    return result

def _save_rois(data):
    """保存所有ROI数据, 合并OCR条目回原格式"""
    base = os.path.dirname(__file__)
    # 先收集所有OCR更新
    ocr_updates = {}
    for key, (fname, fmt, idx) in ROI_FILES.items():
        if fmt == "ocr" and key in data:
            ocr_updates.setdefault(fname, {})[idx] = data[key]
    # 处理OCR文件
    for fname, updates in ocr_updates.items():
        fpath = os.path.join(base, fname)
        if os.path.exists(fpath):
            with open(fpath, encoding="utf-8") as f:
                ocr_list = json.load(f)
        else:
            ocr_list = [["", 0, 0, 50, 25, ""] for _ in range(6)]
        for idx, new_roi in updates.items():
            # new_roi = [x, y, w, h], 保留原有的name和charset
            ocr_list[idx][1] = new_roi[0]
            ocr_list[idx][2] = new_roi[1]
            ocr_list[idx][3] = new_roi[2]
            ocr_list[idx][4] = new_roi[3]
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(ocr_list, f, ensure_ascii=False, indent=2)
    # 处理非OCR文件
    for key, (fname, fmt, idx) in ROI_FILES.items():
        if fmt == "ocr" or key not in data:
            continue
        fpath = os.path.join(base, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data[key], f, ensure_ascii=False, indent=2)
    return True

@app.route("/calibrate")
def calibrate_page():
    html_path = os.path.join(os.path.dirname(__file__), "calibrate.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()

@app.route("/api/cameras")
def api_cameras():
    """列出所有可用摄像头"""
    cams = []
    try:
        from pygrabber.dshow_graph import FilterGraph
        graph = FilterGraph()
        for i, name in enumerate(graph.get_input_devices()):
            cams.append({"id": i, "name": name, "is_obs": "obs" in name.lower()})
    except Exception:
        # 回退: OpenCV枚举
        for i in range(5):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened():
                cams.append({"id": i, "name": f"Camera {i}", "is_obs": False})
                cap.release()
    # 读取已保存的摄像头ID
    cfg = load_cfg()
    current = cfg.get("obs_cam_id", _find_obs_cam())
    return jsonify({"cameras": cams, "current": current})

@app.route("/api/camera_test", methods=["POST"])
def api_camera_test():
    """测试指定摄像头: 返回一帧画面"""
    data = request.get_json() or {}
    cam_id = data.get("cam_id", _find_obs_cam())
    cap = cv2.VideoCapture(cam_id, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    for _ in range(5):
        cap.read()  # 预热
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return jsonify({"error": f"无法读取摄像头 #{cam_id}"})
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return jsonify({"ok": True, "image": base64.b64encode(buf).decode(),
                    "cam_id": cam_id, "shape": list(frame.shape[:2])})

@app.route("/api/save_cam_id", methods=["POST"])
def api_save_cam_id():
    """保存选定的摄像头ID到配置"""
    data = request.get_json() or {}
    cam_id = data.get("cam_id", 1)
    cfg = load_cfg()
    cfg["obs_cam_id"] = int(cam_id)
    cfg_path = os.path.join(os.path.dirname(__file__), "navigator_config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True, "cam_id": cam_id})

@app.route("/api/capture", methods=["POST"])
def api_capture():
    img = _capture_frame()
    if img:
        return jsonify({"ok": True, "image": img})
    return jsonify({"error": "截取失败, OBS是否已打开?"})

@app.route("/api/preview", methods=["POST"])
def api_preview():
    """实时预览: 截图 + OCR + HP + 武器检测"""
    b64 = _capture_frame()
    if not b64:
        return jsonify({"error": "截取失败"})
    import base64 as _b64
    raw = _b64.b64decode(b64)
    arr = np.frombuffer(raw, np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    rois = _load_rois()

    # === OCR状态值 ===
    ocr_results = {}
    for key, (_, fmt, idx) in ROI_FILES.items():
        if not key.startswith("ocr_"):
            continue
        d = rois.get(key)
        if not d or not isinstance(d, list) or len(d) < 4:
            continue
        x, y, w, h = d[0], d[1], d[2], d[3]
        if w < 2 or h < 2:
            continue
        crop = frame[y:y+h, x:x+w]
        if crop.size == 0:
            continue
        txt = _run_ocr(crop, key)
        # 规则: 状态值<200, 只取数字部分
        name = key.replace("ocr_", "")
        if txt and txt.replace(" ", "").isdigit():
            val = int(txt.replace(" ", ""))
            if val > 200:
                val = int(str(val)[:2])
            ocr_results[key] = str(val)
        elif key == "ocr_open":
            ocr_results[key] = txt if "开" in txt else ""
        else:
            ocr_results[key] = txt

    # === HP 血量 (绿色像素占比) ===
    hp_pct = 0
    hp_data = rois.get("hp")
    if hp_data and isinstance(hp_data, list) and len(hp_data) >= 4:
        hx, hy, hw, hh = [max(1, int(v)) for v in hp_data[:4]]
        hp_roi = frame[hy:hy+hh, hx:hx+hw]
        if hp_roi.size > 0:
            hsv = cv2.cvtColor(hp_roi, cv2.COLOR_BGR2HSV)
            gm = cv2.inRange(hsv, np.array([35, 40, 40]), np.array([85, 255, 255]))
            hp_pct = int(np.count_nonzero(gm) / gm.size * 100)

    # === 武器检测 (颜色匹配) ===
    weapon_status = "unknown"
    weapon_data = rois.get("weapon")
    if weapon_data and isinstance(weapon_data, dict):
        wr = weapon_data.get("roi", [1300, 838, 30, 30])
        tol = weapon_data.get("tol", 20)
        thr = weapon_data.get("thr", 0.3)
        wx, wy, ww, wh = [max(1, int(v)) for v in wr[:4]]
        w_roi = frame[wy:wy+wh, wx:wx+ww]
        if w_roi.size > 0:
            bgr_ref = np.array([19, 39, 80])  # BGR = RGB(80,39,19) reversed
            diff = np.abs(w_roi.astype(np.int16) - bgr_ref.astype(np.int16))
            dist = np.sqrt(np.sum(diff ** 2, axis=2))
            match_ratio = np.count_nonzero(dist < tol) / dist.size
            weapon_status = "空" if match_ratio > thr else "有"
            weapon_status += f" ({match_ratio:.0%})"

    # === 终端打印 ===
    print(f"\n{'='*60}")
    print(f"[标定预览] HP={hp_pct}% | Hunger={ocr_results.get('ocr_hunger','?')} | "
          f"Thirst={ocr_results.get('ocr_thirst','?')} | Stamina={ocr_results.get('ocr_stamina','?')} | "
          f"Threat={ocr_results.get('ocr_threat','?')} | Exp={ocr_results.get('ocr_exp','?')}")
    print(f"[标定预览] Open='{ocr_results.get('ocr_open','?')}' | Weapon={weapon_status}")
    print(f"{'='*60}")

    return jsonify({"ok": True, "image": b64, "ocr": ocr_results,
                    "hp": hp_pct, "weapon": weapon_status})

@app.route("/api/reset", methods=["POST"])
def api_reset():
    """重置为本地JSON文件的值"""
    rois = _load_rois()
    return jsonify({"ok": True, "rois": rois})

# 全局OCR实例 (延迟加载)
_ocr_reader = None  # en数字
_ocr_zh = None       # ch_sim中文(开字)

def _run_ocr(crop, key):
    """对裁剪区域运行OCR (与navigator._read_status_values保持一致)"""
    global _ocr_reader
    txt = ""
    try:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        # 与navigator一致: 放大6倍 + cubic插值
        h, w = gray.shape
        big = cv2.resize(gray, (w*6, h*6), interpolation=cv2.INTER_CUBIC)
        # EasyOCR (与navigator一致: en, allowlist只有数字)
        if _ocr_reader is None:
            try:
                import easyocr
                _ocr_reader = easyocr.Reader(["en"], gpu=True, verbose=False)
            except Exception:
                _ocr_reader = False
        if key == "ocr_open":
            # "开"字: EasyOCR ch_sim (Tesseract经常未安装)
            global _ocr_zh
            try:
                if _ocr_zh is None:
                    import easyocr as _eo
                    _ocr_zh = _eo.Reader(["ch_sim"], gpu=True, verbose=False)
                results = _ocr_zh.readtext(big, detail=0)
                if results:
                    txt = " ".join(results)
                print(f"[OCR:Open] easyocr_ch={txt}")
            except Exception as e:
                print(f"[OCR:Open] err={e}")
        elif _ocr_reader and _ocr_reader is not False:
            rt = _ocr_reader.readtext(big, detail=1, allowlist="0123456789")
            if rt:
                parts = [r[1].strip() for r in rt if r[1].strip().isdigit()]
                txt = "".join(parts)
        # 回退 Tesseract
        if not txt and key != "ocr_open":
            try:
                import pytesseract
                raw = pytesseract.image_to_string(big,
                    config="--psm 7 -c tessedit_char_whitelist=0123456789xpXP").strip()
                if raw:
                    txt = raw
            except Exception:
                pass
    except Exception:
        pass
    return txt

@app.route("/api/rois")
def api_rois():
    return jsonify(_load_rois())

@app.route("/api/save_rois", methods=["POST"])
def api_save_rois():
    data = request.get_json()
    _save_rois(data)
    return jsonify({"ok": True, "saved": list(data.keys())})

# HTML 模板
CALIBRATE_HTML = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>DeadMaze 标定中心</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font:13px 'Microsoft YaHei',Arial;background:#1a1a2e;color:#eee;display:flex;height:100vh}
  #main{flex:1;overflow:auto;position:relative;background:#111}
  canvas{display:block;cursor:crosshair}
  #side{width:340px;background:#222;border-left:1px solid#444;overflow-y:auto;padding:12px;display:flex;flex-direction:column}
  h2{color:#0ff;font-size:15px;margin-bottom:4px}
  .sub{color:#888;font-size:11px;margin-bottom:10px}
  button{padding:8px 14px;border:none;cursor:pointer;font-size:12px;border-radius:3px;font-family:inherit}
  .btn-cap{background:#09f;color:#fff;margin:6px 0;width:100%}
  .btn-save{background:#0a0;color:#fff;width:100%;margin-top:8px;padding:10px;font-size:14px}
  .btn-nav{background:#555;color:#ccc;margin-bottom:6px;font-size:11px;padding:5px 10px}
  .section{border-bottom:1px solid#333;padding:8px 0}
  .section:last-child{border-bottom:none}
  .sect-title{color:#0ff;font-size:12px;font-weight:bold;margin-bottom:4px;text-transform:uppercase;letter-spacing:1px}
  .roi-card{background:#2a2a2a;padding:8px 10px;margin:3px 0;border-radius:4px;cursor:pointer;
             border-left:3px solid #666;transition:all .15s}
  .roi-card:hover{background:#333;border-left-color:#fff}
  .roi-card.active{border-left-color:#0f0!important;background:#1a2a1a}
  .roi-card .rname{font-weight:bold;font-size:12px}
  .roi-card .rinfo{color:#999;font-size:10px;margin:2px 0}
  .roi-card .rpos{color:#aaa;font-family:monospace;font-size:11px}
  .roi-card .rpos span{color:#0f0}
  .dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px;vertical-align:middle}
  input.roi-num{width:52px;background:#333;border:1px solid#555;color:#fff;padding:2px 3px;
                 font-size:10px;font-family:monospace;text-align:center}
  label.roi-lbl{font-size:9px;color:#777;margin:0 1px}
  #status{position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:99;
          background:rgba(0,0,0,.85);color:#0f0;padding:6px 20px;border-radius:4px;display:none;font-size:13px}
  .legend{display:flex;flex-wrap:wrap;gap:4px 12px;margin:4px 0}
  .legend span{font-size:10px;color:#aaa}
</style></head><body>
<div id="main"><canvas id="canvas"></canvas></div>
<div id="side">
  <a href="/"><button class="btn-nav">← 返回配置</button></a>
  <h2>标定中心 v2</h2>
  <div class="sub">截取OBS画面后, 所有ROI区域位置会叠加显示在图上</div>
  <button class="btn-cap" onclick="capture()">📷 截取OBS画面</button>
  <div class="sub" id="imgInfo"></div>
  <div id="roiSections"></div>
  <button class="btn-save" onclick="saveAll()">💾 保存全部</button>
  <div class="sub" style="margin-top:8px;color:#666;text-align:center">
    🖱 拖拽 = 移动ROI | WASD/方向键 = 微调 | Shift = 加速
  </div>
  <div id="status"></div>
</div>

<script>
let img=null, canvas=document.getElementById('canvas'), ctx=canvas.getContext('2d');
let dragging=false, dragOX=0, dragOY=0, roiData=null, activeKey=null;

// 每个ROI的颜色
const COLORS={
  ocr_exp:'#ff0',ocr_hunger:'#f80',ocr_thirst:'#09f',ocr_stamina:'#0f0',
  ocr_threat:'#f0f',ocr_open:'#0ff',
  hp:'#f00',weapon:'#ff0',inventory:'#f80',food:'#09f'
};

const DESCS={
  ocr_exp:'经验值数字区域 (x表示经验倍数)',
  ocr_hunger:'饱食度数字',
  ocr_thirst:'口渴度数字',
  ocr_stamina:'体力值数字',
  ocr_threat:'威胁值数字 (x表示威胁倍数)',
  ocr_open:'火堆交互提示"开"字',
  hp:'绿色血量条位置',
  weapon:'武器槽颜色检测区',
  inventory:'背包物品OCR区域',
  food:'食物/水 tooltip OCR区域'
};

const SECTIONS={
  'OCR状态识别':['ocr_exp','ocr_hunger','ocr_thirst','ocr_stamina','ocr_threat','ocr_open'],
  '战斗检测':['hp','weapon'],
  '背包补给':['inventory','food']
};

// --- 截图 ---
async function capture(){
  showMsg('截取中...');
  let r=await fetch('/api/capture',{method:'POST'});
  let j=await r.json();
  if(j.error){showMsg(j.error,'#f44');return}
  img=new Image();
  img.onload=()=>{
    canvas.width=img.width; canvas.height=img.height;
    ctx.drawImage(img,0,0);
    document.getElementById('imgInfo').textContent='分辨率: '+img.width+'×'+img.height+' (原生)';
    drawAllRois();
    showMsg('截取成功');
  };
  img.src='data:image/jpeg;base64,'+j.image;
}

// --- 绘制所有ROI ---
function drawAllRois(){
  if(!img||!roiData)return;
  ctx.drawImage(img,0,0);
  for(let key in roiData){
    let c=getCoords(key), color=COLORS[key]||'#888';
    if(!c)continue;
    let [x,y,w,h]=c;
    let isActive=key===activeKey;
    // 极淡填充 + 边框
    ctx.fillStyle=color+'0c';
    ctx.fillRect(x,y,w,h);
    ctx.strokeStyle=color; ctx.lineWidth=isActive?2.5:1;
    ctx.strokeRect(x,y,w,h);
    // 标签 (画在框外侧)
    let label=key.replace('ocr_','').replace('_',' ');
    ctx.fillStyle=color; ctx.font='bold 10px monospace';
    let ty=y-3; if(ty<12)ty=y+h+13;
    ctx.fillText(label, x+2, ty);
    if(isActive){
      // 高亮边框
      ctx.strokeStyle='#fff'; ctx.lineWidth=1;
      ctx.setLineDash([4,2]); ctx.strokeRect(x-1,y-1,w+2,h+2); ctx.setLineDash([]);
    }
  }
}

function getCoords(key){
  // 返回ROI数据的引用 (修改返回值会直接影响roiData)
  let d=roiData[key]; if(!d)return null;
  if(Array.isArray(d)&&d.length>=4)return d;
  if(d.roi&&Array.isArray(d.roi))return d.roi;
  return null;
}

// --- 坐标: 处理canvas CSS缩放后的真实像素 ---
function canvasPos(e){
  let r=canvas.getBoundingClientRect();
  return {
    x:(e.clientX-r.left)*(canvas.width/r.width),
    y:(e.clientY-r.top)*(canvas.height/r.height)
  };
}

// --- 鼠标拖拽移动ROI ---
canvas.onmousedown=e=>{
  if(!img||!activeKey)return;
  let p=canvasPos(e);
  let c=getCoords(activeKey); if(!c)return;
  let [rx,ry,rw,rh]=c;
  if(p.x>=rx&&p.x<=rx+rw&&p.y>=ry&&p.y<=ry+rh){
    dragging=true; dragOX=p.x-rx; dragOY=p.y-ry;
    canvas.style.cursor='grabbing';
  }
};
canvas.onmousemove=e=>{
  if(!dragging||!img||!activeKey)return;
  let p=canvasPos(e);
  let c=getCoords(activeKey); if(!c)return;
  c[0]=Math.round(p.x-dragOX); c[1]=Math.round(p.y-dragOY);
  drawAllRois(); updateCardValues(activeKey);
};
canvas.onmouseup=()=>{dragging=false;canvas.style.cursor='crosshair';};
canvas.onmouseleave=()=>{dragging=false;canvas.style.cursor='crosshair';};

// --- WASD/方向键 微调选中的ROI ---
document.addEventListener('keydown',e=>{
  if(!activeKey||!roiData||!img)return;
  // 只在标定页处理 (不在输入框内)
  if(document.activeElement&&document.activeElement.tagName==='INPUT')return;
  let c=getCoords(activeKey); if(!c)return;
  let step=e.shiftKey?10:1;
  switch(e.key){
    case 'w':case 'ArrowUp':   c[1]-=step;break;
    case 's':case 'ArrowDown': c[1]+=step;break;
    case 'a':case 'ArrowLeft': c[0]-=step;break;
    case 'd':case 'ArrowRight':c[0]+=step;break;
    default:return;
  }
  e.preventDefault();
  drawAllRois(); updateCardValues(activeKey);
});

// --- 右侧面板 ---
async function loadRois(){
  let r=await fetch('/api/rois'); roiData=await r.json();
  renderSections();
}

function renderSections(){
  let html='';
  for(let sec in SECTIONS){
    html+='<div class="section"><div class="sect-title">'+sec+'</div>';
    for(let key of SECTIONS[sec]){
      let c=getCoords(key), isActive=key===activeKey;
      let color=COLORS[key]||'#888';
      let posTxt=c?`[<span>${c[0]}</span>, <span>${c[1]}</span> <span>${c[2]}</span>×<span>${c[3]}</span>]`:'未标定';
      html+=`<div class="roi-card${isActive?' active':''}" onclick="selectRoi('${key}')" style="border-left-color:${color}">
        <div class="rname"><span class="dot" style="background:${color}"></span>${key.replace('ocr_','').toUpperCase()}</div>
        <div class="rinfo">${DESCS[key]||''}</div>
        <div class="rpos">${posTxt}</div>`;
      if(c){
        html+=`<div style="margin-top:4px" onclick="event.stopPropagation()">
          <label class="roi-lbl">X</label><input class="roi-num" value="${c[0]}" onchange="updateCoord('${key}',0,this.value)">
          <label class="roi-lbl">Y</label><input class="roi-num" value="${c[1]}" onchange="updateCoord('${key}',1,this.value)">
          <label class="roi-lbl">W</label><input class="roi-num" value="${c[2]}" onchange="updateCoord('${key}',2,this.value)">
          <label class="roi-lbl">H</label><input class="roi-num" value="${c[3]}" onchange="updateCoord('${key}',3,this.value)">
        </div>`;
      }
      // weapon特殊
      if(key==='weapon'&&roiData.weapon&&roiData.weapon.tol!==undefined){
        html+=`<div style="margin-top:2px;font-size:10px;color:#666" onclick="event.stopPropagation()">
          Tol:<input class="roi-num" style="width:45px" value="${roiData.weapon.tol}" onchange="roiData.weapon.tol=parseInt(this.value)||20">
          Thr:<input class="roi-num" style="width:45px" value="${roiData.weapon.thr}" onchange="roiData.weapon.thr=parseFloat(this.value)||0.3">
          (脚本预设)
        </div>`;
      }
      html+='</div>';
    }
    html+='</div>';
  }
  document.getElementById('roiSections').innerHTML=html;
}

function selectRoi(key){
  activeKey=key;
  renderSections();
  if(img)drawAllRois();
}

function updateCoord(key, idx, val){
  let v=parseInt(val)||0;
  let d=roiData[key];
  if(Array.isArray(d))d[idx]=v;
  else if(d&&d.roi)d.roi[idx]=v;
  updateCardValues(key);
  if(img)drawAllRois();
}

function updateCardValues(key){
  if(!img||!roiData)return;
  renderSections(); // 重绘右侧面板
  if(key===activeKey)drawAllRois(); // 重绘canvas高亮
}

async function saveAll(){
  let r=await fetch('/api/save_rois',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(roiData)});
  let j=await r.json();
  showMsg('已保存: '+j.saved.join(', '));
}

function showMsg(msg, color='#0f0'){
  let s=document.getElementById('status');
  s.textContent=msg; s.style.display='block'; s.style.color=color;
  setTimeout(()=>s.style.display='none',2500);
}

loadRois();
</script></body></html>"""

def start(port=5050):
    """在后台线程启动Flask (供navigator调用, 端口冲突则跳过)"""
    # 检查端口是否已被占用 (如config_server独立运行中)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    in_use = sock.connect_ex(('127.0.0.1', port)) == 0
    sock.close()
    if in_use:
        print(f"[Config Web] 端口{port}已占用 (可能已在独立模式运行), 跳过启动")
        return
    t = threading.Thread(target=lambda: app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False), daemon=True)
    t.start()
    print(f"[Config Web] http://127.0.0.1:{port} (配置) | http://127.0.0.1:{port}/calibrate (标定)")

if __name__ == '__main__':
    print("=" * 56)
    print("  DeadMaze 配置 & 标定中心 (独立模式)")
    print("  可单独运行，不需要启动 navigator")
    print("=" * 56)
    start()
    print("  按 Ctrl+C 退出")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("\n已退出")
