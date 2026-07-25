"""Config Web Panel - Flask server"""
import json, os, threading
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)
CFG_FILE = os.path.join(os.path.dirname(__file__), "navigator_config.json")

DEFAULTS = {
    "waypoint_reach": 25, "deviation": 100, "move_dur": 0.5,
    "goal_reach": 100, "lookahead": 90, "zombie_range": 600,
    "attack_range": 130, "chase_timeout": 7, "low_stat_thr": 15,
    "heal_hp": 80, "escape_hp": 20, "combat_entry_hp": 70,
    "max_zombies": 6, "weapon_tol": 20, "weapon_thr": 0.3,
    "weapon_check": 15, "return_thr": 15,
    "skill1_cd": 4, "skill2_cd": 12, "skill3_cd": 22, "skill4_cd": 32,
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

<button onclick="save()">SAVE CONFIG</button><span class="status" id="status"></span>
<button onclick="load_cfg()" style="background:#555;margin-left:10px">RELOAD</button>

<script>
const ids = ["waypoint_reach","deviation","move_dur","goal_reach","lookahead",
  "zombie_range","attack_range","chase_timeout","combat_entry_hp","max_zombies",
  "low_stat_thr","heal_hp","escape_hp","return_thr",
  "skill1_cd","skill2_cd","skill3_cd","skill4_cd",
  "weapon_tol","weapon_thr","weapon_check"];
function sync(r){
  let n=r.nextElementSibling, v=parseFloat(r.value);
  n.textContent=v; r.nextElementSibling.nextElementSibling.value=v
}
ids.forEach(id=>{
  let r=document.getElementById(id);
  r.addEventListener('input',()=>sync(r));
  r.nextElementSibling.nextElementSibling.addEventListener('change',function(){
    r.value=this.value;sync(r)
  })
});
async function load_cfg(){
  let r=await fetch('/get');let d=await r.json();
  ids.forEach(id=>{document.getElementById(id).value=d[id];sync(document.getElementById(id))})
}
async function save(){
  let d={};ids.forEach(id=>d[id]=parseFloat(document.getElementById(id).value));
  let r=await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});
  document.getElementById('status').textContent='Saved!';
  setTimeout(()=>document.getElementById('status').textContent='',2000)
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

def start(port=5050):
    t = threading.Thread(target=lambda: app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False), daemon=True)
    t.start()
    print(f"[Config Web] http://127.0.0.1:{port}")

if __name__ == '__main__':
    start()
    import time
    while True: time.sleep(1)
