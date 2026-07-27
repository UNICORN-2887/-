"""导航控制器 + Flask REST API.

Navigator: Python SDK 直接调用.
NavigationServer: Flask HTTP API, 非 Python 用户通过 REST 调用.
"""

from typing import Optional, Tuple, List, Callable
from queue import Queue
from threading import Thread
import time
import os
import json

import numpy as np

from game_automator.driver import Actions, AbstractDriver
from game_automator.mapping import Pathfinder


# ── 8方向 + 最佳匹配 (直搬 DeadMaze best_direction) ──
_DIR_VECTORS = [
    ( 0, -1, Actions.MOVE_N),        # 0: N
    ( 1, -1, Actions.MOVE_NE),       # 1: NE
    ( 1,  0, Actions.MOVE_E),        # 2: E
    ( 1,  1, Actions.MOVE_SE),       # 3: SE
    ( 0,  1, Actions.MOVE_S),        # 4: S
    (-1,  1, Actions.MOVE_SW),       # 5: SW
    (-1,  0, Actions.MOVE_W),        # 6: W
    (-1, -1, Actions.MOVE_NW),       # 7: NW
]


def compute_direction(from_pos: Tuple[int, int],
                      to_pos: Tuple[int, int]) -> Actions:
    """向量 (dx, dy) → 最接近的8方向 (内积最大)."""
    dx = to_pos[0] - from_pos[0]
    dy = to_pos[1] - from_pos[1]
    if dx == 0 and dy == 0:
        return None
    best_i, best_dot = 0, -999
    for i, (vx, vy, _) in enumerate(_DIR_VECTORS):
        d = vx * dx + vy * dy
        if d > best_dot:
            best_dot = d
            best_i = i
    return _DIR_VECTORS[best_i][2]


# ── 导航控制器 ────────────────────────────────
class Navigator:
    """Python SDK 导航控制器.

    Usage:
        nav = Navigator(pathfinder, driver)
        nav.set_route(start, goal)
        while not nav.arrived:
            pos = tracker.get_position()   # 用户提供定位回调
            action = nav.step(pos)
            if action: driver.execute(action)
    """

    def __init__(self,
                 pathfinder: Pathfinder,
                 driver: Optional[AbstractDriver] = None,
                 waypoint_reach: int = 25,
                 goal_reach: int = 100,
                 lookahead: int = 90,
                 move_duration_ms: int = 300):
        self._pf = pathfinder
        self._driver = driver
        self.waypoint_reach = waypoint_reach
        self.goal_reach = goal_reach
        self.lookahead = lookahead
        self.move_duration_ms = move_duration_ms

        self._path: List[Tuple[int, int]] = []
        self._wp_index = 0
        self._goal: Optional[Tuple[int, int]] = None
        self.arrived = False

    # ── 设置 ──────────────────────────────────
    def set_route(self, start: Tuple[int, int],
                  goal: Tuple[int, int]) -> List[Tuple[int, int]]:
        self._path = self._pf.plan(start, goal) or []
        self._wp_index = 0
        self._goal = goal
        self.arrived = False
        return self._path

    def set_waypoints(self, waypoints: List[Tuple[int, int]]) -> None:
        """设置途径点列表用于巡逻."""
        self._path = waypoints
        self._wp_index = 0
        self._goal = waypoints[-1] if waypoints else None
        self.arrived = False

    def step(self, current_pos: Tuple[int, int]) -> Optional[Actions]:
        """传入当前位置, 返回应执行的动作 (None=到达)."""
        if not self._path:
            self.arrived = True
            return None

        # 距终点 < goal_reach → 到达
        last = self._path[-1]
        if np.hypot(current_pos[0]-last[0], current_pos[1]-last[1]) < self.goal_reach:
            self.arrived = True
            return None

        # 跳过已到达的路标
        while self._wp_index < len(self._path):
            tgt = self._path[self._wp_index]
            if np.hypot(current_pos[0]-tgt[0], current_pos[1]-tgt[1]) < self.waypoint_reach:
                self._wp_index += 1
            else:
                break

        if self._wp_index >= len(self._path):
            self.arrived = True
            return None

        # 找到路径上距当前位置最近的点 (跳过身后点)
        min_dist = float('inf')
        nearest_idx = self._wp_index
        for i in range(self._wp_index, len(self._path)):
            wx, wy = self._path[i]
            d = np.hypot(wx - current_pos[0], wy - current_pos[1])
            if d < min_dist:
                min_dist = d
                nearest_idx = i
        # current_waypoint 只进不退 (原版有 max(current_waypoint, wpidx-2))
        self._wp_index = nearest_idx

        # 向前找第一个距离 >= lookahead 的点
        for i in range(self._wp_index, len(self._path)):
            wx, wy = self._path[i]
            if np.hypot(wx - current_pos[0], wy - current_pos[1]) >= self.lookahead:
                self._wp_index = i
                break
        target = self._path[min(self._wp_index + 10, len(self._path) - 1)]

        return compute_direction(current_pos, target)

    def _deviation_distance(self, pos):
        if self._wp_index >= len(self._path):
            return 0.0
        seg_start = self._path[max(0, self._wp_index - 1)]
        seg_end = self._path[self._wp_index]
        return self._point_to_segment_dist(pos, seg_start, seg_end)

    @staticmethod
    def _point_to_segment_dist(p, a, b):
        ax, ay = a; bx, by = b
        abx, aby = bx - ax, by - ay
        if abx == 0 and aby == 0:
            return np.hypot(p[0] - ax, p[1] - ay)
        t = max(0, min(1, ((p[0]-ax)*abx + (p[1]-ay)*aby) / (abx*abx + aby*aby)))
        px = ax + t * abx
        py = ay + t * aby
        return np.hypot(p[0] - px, p[1] - py)

    @property
    def current_waypoint(self) -> Optional[Tuple[int, int]]:
        if self._wp_index < len(self._path):
            return self._path[self._wp_index]
        return None

    @property
    def path(self) -> List[Tuple[int, int]]:
        return list(self._path)

    def cancel(self) -> None:
        self._path = []
        self._wp_index = 0
        self.arrived = True


# ── Flask API 服务 ────────────────────────────
class NavigationServer:
    """REST API 导航服务 (非 Python 用户通过 HTTP 调用)."""

    def __init__(self, pathfinder: Pathfinder,
                 driver: Optional[AbstractDriver] = None,
                 port: int = 5001,
                 map_image: Optional[str] = None):
        from flask import Flask, request, jsonify, render_template_string
        self._nav = Navigator(pathfinder, driver)
        self._port = port
        self._app = Flask(__name__)
        self._tracker_callback: Optional[Callable] = None
        self._map_image = map_image
        self._pf = pathfinder
        self._reachable_path = None
        self._cap = None  # OBS capture (可选)

        # 前端页面 (支持URL参数调参: ?wp=25&gr=100&la=90&sh=8)
        @self._app.route("/")
        def index():
            import base64
            wp = request.args.get("wp", 25, type=int)
            gr = request.args.get("gr", 100, type=int)
            la = request.args.get("la", 90, type=int)
            sh = request.args.get("sh", 8, type=int)
            # 用新参数重建引擎
            if self._reachable_path:
                self._pf = Pathfinder(self._reachable_path, shrink=sh)
                self._nav = Navigator(self._pf, waypoint_reach=wp, goal_reach=gr, lookahead=la)
            map_b64 = ""
            if self._map_image:
                try:
                    with open(self._map_image, "rb") as f:
                        map_b64 = base64.b64encode(f.read()).decode()
                except: pass
            return render_template_string(_NAV_HTML, map_b64=map_b64,
                gw=self._pf.grid_size[0], gh=self._pf.grid_size[1],
                wp=wp, gr=gr, la=la, sh=sh)

        @self._app.route("/api/plan", methods=["POST"])
        def plan():
            data = request.get_json() or {}
            sx, sy = data.get("start", (0, 0))
            gx, gy = data.get("goal", (0, 0))
            raw = self._nav.set_route((sx, sy), (gx, gy))
            path = [(int(x), int(y)) for x, y in raw]
            return jsonify({"path": path, "length": len(path)})

        @self._app.route("/api/step", methods=["POST"])
        def step():
            data = request.get_json() or {}
            pos = (data.get("x", 0), data.get("y", 0))
            action = self._nav.step(pos)
            wp = self._nav.current_waypoint
            wp_json = (int(wp[0]), int(wp[1])) if wp else None
            return jsonify({
                "action": action.name if action else None,
                "arrived": self._nav.arrived,
                "waypoint": wp_json,
            })

        @self._app.route("/api/position", methods=["POST"])
        def set_pos():
            """外部推送当前位置 (替代 tracker)."""
            data = request.get_json() or {}
            self._tracker_callback = lambda: (data["x"], data["y"])
            return jsonify({"ok": True})

        @self._app.route("/api/cancel", methods=["POST"])
        def cancel():
            self._nav.cancel()
            return jsonify({"ok": True})

        @self._app.route("/api/status")
        def status():
            return jsonify({
                "arrived": self._nav.arrived,
                "waypoint": self._nav.current_waypoint,
                "path_length": len(self._nav.path),
            })

        # OBS 光流追踪
        @self._app.route("/api/track", methods=["POST"])
        def api_track():
            if self._cap is None:
                return jsonify({"error": "no capture"})
            frame = self._cap.read()
            if frame is None:
                return jsonify({"error": "capture failed"})
            if not hasattr(self, '_tracker'):
                from game_automator.mapping import PositionTracker
                self._tracker = PositionTracker.__new__(PositionTracker)
                self._tracker._position = [0, 0]
                self._tracker._crop = None
                self._tracker._prev_gray = None
                self._tracker._prev_pts = None
                self._tracker._last_conf = 0.0
                import cv2
                self._tracker._lk_params = dict(winSize=(21,21), maxLevel=3,
                    criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,30,0.01))
                self._tracker._feature_params = dict(maxCorners=200, qualityLevel=0.3,
                    minDistance=15, blockSize=7)
                self._tracker.init_tracking(frame)
                return jsonify({"pos": [0,0], "conf": 0.0, "msg": "tracker init"})
            pos, conf = self._tracker.update(frame)
            return jsonify({"pos": [int(pos[0]), int(pos[1])], "conf": round(conf, 3)})

        # OBS 实时预览
        @self._app.route("/api/capture")
        def api_capture():
            import base64, cv2 as _cv
            if self._cap is None:
                return jsonify({"error": "no capture source"})
            frame = self._cap.read()
            if frame is None:
                return jsonify({"error": "capture failed"})
            _, buf = _cv.imencode(".jpg", frame, [_cv.IMWRITE_JPEG_QUALITY, 75])
            return jsonify({"ok": True,
                "image": base64.b64encode(buf).decode(),
                "shape": list(frame.shape[:2])})

    def start(self, blocking: bool = True):
        print(f"[NavigationServer] http://127.0.0.1:{self._port}/  (前端)")
        self._app.run(host="127.0.0.1", port=self._port,
                       debug=False, use_reloader=False)

    def start_threaded(self):
        t = Thread(target=self.start, kwargs={"blocking": True}, daemon=True)
        t.start()
        return t

_NAV_HTML = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Navigation Test</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font:14px sans-serif;background:#1a1a2e;color:#eee;display:flex;height:100vh}
#panel{width:280px;background:#1e1e2e;border-right:1px solid#333;padding:14px;display:flex;flex-direction:column;gap:10px}
#panel h2{color:#0ff;font-size:16px}
#panel .info{color:#888;font-size:11px}
#panel input{width:100%;padding:6px;background:#0f0f1a;border:1px solid#444;color:#eee;font-size:12px}
#panel button{width:100%;padding:8px;border:none;border-radius:4px;cursor:pointer;font-size:13px}
.btn-plan{background:#3b82f6;color:#fff}.btn-go{background:#10b981;color:#fff}.btn-stop{background:#ef4444;color:#fff}
#view{flex:1;overflow:auto;background:#0a0a0f;position:relative}
canvas{cursor:crosshair;display:block}
#log{background:#0f0f1a;color:#aaa;font-size:11px;padding:8px;border-radius:4px;max-height:120px;overflow-y:auto;font-family:monospace}
</style></head><body>
<div id="panel">
 <h2>Navigation Test</h2>
 <div class="info">Click on map to set start(click) and goal(shift+click)</div>
 <label>Start <input id="startXY" value="150,150"></label>
 <label>Goal <input id="goalXY" value="750,750"></label>
 <button class="btn-plan" onclick="doPlan()">Plan Path</button>
 <details style="margin:4px 0"><summary style="color:#888;font-size:11px;cursor:pointer">Parameters</summary>
  <div style="font-size:10px;color:#888;margin:2px 0">Waypoint Reach <input id="wpReach" value="{{wp}}" style="width:50px"></div>
  <div style="font-size:10px;color:#888;margin:2px 0">Goal Reach <input id="goalReach" value="{{gr}}" style="width:50px"></div>
  <div style="font-size:10px;color:#888;margin:2px 0">Lookahead <input id="lookahead" value="{{la}}" style="width:50px"></div>
  <div style="font-size:10px;color:#888;margin:2px 0">Shrink <input id="shrink" value="{{sh}}" style="width:50px"></div>
  <div style="font-size:10px;color:#888;margin:2px 0">Step Speed <input id="speed" value="20" style="width:50px"></div>
  <button class="btn-plan" onclick="location.href='/?wp='+document.getElementById('wpReach').value+'&gr='+document.getElementById('goalReach').value+'&la='+document.getElementById('lookahead').value+'&sh='+document.getElementById('shrink').value">Apply Params</button>
 </details>
 <label>Sim Pos <input id="simPos" value="150,150"></label>
 <button class="btn-go" onclick="doStep()">Step &gt;&gt;</button>
 <button class="btn-stop" onclick="location.reload()">Reset</button>
 <button class="btn-go" onclick="testOBS()" style="background:#f59e0b;color:#000">Test OBS</button>
 <button class="btn-go" id="btnSim" onclick="toggleSim()" style="background:#8b5cf6;color:#fff">Auto Sim</button>
 <div id="log"></div>
 <div id="obsPreview" style="margin-top:8px"></div>
</div>
<div id="view"><canvas id="c"></canvas></div>
<script>
let c=document.getElementById('c'),ctx=c.getContext('2d'),img=null;
let start=[150,150],goal=[750,750],path=[],sim=[150,150];
const BASE='http://127.0.0.1:5001';
const gw={{gw}},gh={{gh}};
function log(m){let l=document.getElementById('log');l.innerHTML=m+'<br>'+l.innerHTML;}
async function testOBS(){
 log('Testing OBS...');
 let r=await fetch(BASE+'/api/capture');
 let j=await r.json();
 if(j.error){log('OBS ERROR: '+j.error);return}
 document.getElementById('obsPreview').innerHTML=
  '<img src=\"data:image/jpeg;base64,'+j.image+'\" style=\"width:100%;border:1px solid#555;margin-top:4px\">'+
  '<div style=\"font-size:10px;color:#888\">OBS: '+j.shape[0]+'x'+j.shape[1]+'</div>';
 log('OBS OK: '+j.shape[0]+'x'+j.shape[1]);
}

// Load map or draw blank
let mapB64='{{map_b64}}';
if(mapB64){
 img=new Image();
 img.onload=function(){c.width=img.width;c.height=img.height;ctx.drawImage(img,0,0);drawOverlay()};
 img.src='data:image/png;base64,'+mapB64;
}else{
 c.width=900;c.height=900;ctx.fillStyle='#1a2a1a';ctx.fillRect(0,0,900,900);
 ctx.strokeStyle='#333';ctx.strokeRect(1,1,898,898);
 drawOverlay();
}

function toMap(e){let r=c.getBoundingClientRect();return[Math.round((e.clientX-r.left)*(img.naturalWidth/c.width)),Math.round((e.clientY-r.top)*(img.naturalHeight/c.height))]}
c.onclick=function(e){let p=toMap(e);if(e.shiftKey){goal=p;document.getElementById('goalXY').value=p[0]+','+p[1]}else{start=p;sim=p.slice();document.getElementById('startXY').value=p[0]+','+p[1];document.getElementById('simPos').value=p[0]+','+p[1]} drawOverlay()}

function drawOverlay(){
 ctx.drawImage(img,0,0);
 ctx.fillStyle='#0f0';ctx.beginPath();ctx.arc(start[0],start[1],5,0,Math.PI*2);ctx.fill();
 ctx.fillStyle='#f00';ctx.beginPath();ctx.arc(goal[0],goal[1],5,0,Math.PI*2);ctx.fill();
 for(let i=1;i<path.length;i++){ctx.strokeStyle='#3b82f6';ctx.beginPath();ctx.moveTo(path[i-1][0],path[i-1][1]);ctx.lineTo(path[i][0],path[i][1]);ctx.stroke()}
 ctx.fillStyle='#ff0';ctx.beginPath();ctx.arc(sim[0],sim[1],4,0,Math.PI*2);ctx.fill();
}

async function doPlan(){
 let r=await fetch(BASE+'/api/plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({start:start,goal:goal})});
 let j=await r.json(); path=j.path; log('Path: '+j.length+' points'); drawOverlay();
}

async function doStep(){
 let r=await fetch(BASE+'/api/step',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:sim[0],y:sim[1]})});
 let j=await r.json();
 if(j.arrived||!j.action){log('Arrived!');return}
 if(j.waypoint){let dx=j.waypoint[0]-sim[0],dy=j.waypoint[1]-sim[1];let d=Math.sqrt(dx*dx+dy*dy);let spd=20;if(d>0){sim[0]=Math.round(sim[0]+dx/d*spd);sim[1]=Math.round(sim[1]+dy/d*spd)}}
 document.getElementById('simPos').value=sim[0]+','+sim[1];
 log('Step: '+j.action+' pos=('+sim[0]+','+sim[1]+')');drawOverlay();
}
let simTimer=null;
async function toggleSim(){
 let b=document.getElementById('btnSim');
 if(simTimer){clearInterval(simTimer);simTimer=null;b.textContent='Auto Sim';b.style.background='#8b5cf6';log('Sim stopped');return}
 b.textContent='Running...';b.style.background='#ef4444';
 // 先规划
 if(!path.length) await doPlan();
 if(!path.length){log('No path!');return}
 log('Auto sim started - point OBS at this window');
 simTimer=setInterval(async()=>{
  // 1. OBS capture → 2. step → 3. move dot
  let cr=await fetch(BASE+'/api/capture');let cj=await cr.json();
  if(cj.image){
   document.getElementById('obsPreview').innerHTML=
    '<img src=\"data:image/jpeg;base64,'+cj.image+'\" style=\"width:100%;border:1px solid#555\">';
  }
  let r=await fetch(BASE+'/api/step',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({x:sim[0],y:sim[1]})});
  let j=await r.json();
  if(j.arrived||!j.action){toggleSim();log('Auto arrived!');return}
  if(j.waypoint){
   let dx=j.waypoint[0]-sim[0],dy=j.waypoint[1]-sim[1];
   let d=Math.sqrt(dx*dx+dy*dy),spd=15;
   if(d>0){sim[0]=Math.round(sim[0]+dx/d*spd);sim[1]=Math.round(sim[1]+dy/d*spd)}
  }
  document.getElementById('simPos').value=sim[0]+','+sim[1];
  drawOverlay();
 },800);
}
</script></body></html>"""
