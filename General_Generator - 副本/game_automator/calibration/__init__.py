"""ROI 标定工具.

CalibrationServer 提供与 DeadMaze 标定中心相同的网页界面,
用户通过浏览器拖拽调整 ROI 位置.
"""

from typing import Dict, List, Optional, Callable
import json
import os
import base64
import time

import cv2
import numpy as np

from game_automator.capture import CaptureSource


class CalibrationServer:
    """Flask 标定网页服务.

    Usage:
        cap = OBSVideoCapture()
        calib = CalibrationServer(cap, roi_file="my_rois.json")
        calib.add_roi("exp", 963, 1045, 50, 25, desc="经验值")
        calib.add_roi("hunger", 1714, 1048, 50, 25, desc="饱食度")
        calib.start()
    """

    def __init__(self, capture: CaptureSource,
                 roi_file: Optional[str] = None):
        from flask import Flask, render_template_string, request, jsonify
        self._cap = capture
        self._roi_file = roi_file
        self._rois: Dict[str, dict] = {}  # name -> {x,y,w,h,desc}
        self._app = Flask(__name__)

        @self._app.route("/api/rois")
        def get_rois():
            return jsonify(self._rois)

        @self._app.route("/api/save", methods=["POST"])
        def save():
            data = request.get_json() or {}
            # data: {"name": [x,y,w,h], ...}
            for name, coords in data.items():
                if name in self._rois and len(coords) >= 4:
                    self._rois[name]["x"] = coords[0]
                    self._rois[name]["y"] = coords[1]
                    self._rois[name]["w"] = coords[2]
                    self._rois[name]["h"] = coords[3]
            if self._roi_file:
                with open(self._roi_file, "w") as f:
                    json.dump(self._export_dict(), f, indent=2)
            return jsonify({"ok": True})

        @self._app.route("/api/capture", methods=["POST"])
        def capture():
            frame = self._cap.read()
            if frame is None:
                return jsonify({"error": "截取失败"})
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            return jsonify({"ok": True,
                            "image": base64.b64encode(buf).decode(),
                            "shape": list(frame.shape[:2])})

    # ── Frontend HTML ───────────────────────────
    _CALIBRATE_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>Game Automator - 标定中心</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font:13px 'Microsoft YaHei',Arial,sans-serif;background:#1a1a2e;color:#eee;display:flex;height:100vh}
#view{flex:1;overflow:auto;background:#0a0a0f} canvas{display:block;cursor:crosshair}
#bar{width:340px;background:#1e1e2e;display:flex;flex-direction:column;border-left:2px solid#333}
#bar-head{padding:14px;border-bottom:1px solid#333}
#bar-head h2{color:#0ff;font-size:17px} .tip{color:#888;font-size:11px;margin:4px 0}
#bar-body{flex:1;overflow-y:auto;padding:8px 14px}
.btn{display:block;width:100%;padding:10px;border:none;border-radius:4px;cursor:pointer;font-size:13px;margin:6px 0;text-align:center}
.btn-cap{background:#09f;color:#fff}.btn-save{background:#0a0;color:#fff;font-size:15px;padding:12px}
.card{padding:8px 10px;margin:3px 0;border-radius:4px;cursor:pointer;border-left:3px solid transparent;background:#252535}
.card:hover{background:#2d2d42}.card.sel{border-left-color:#0f0!important;background:#1a2a1a}
.card .n{font-weight:bold;font-size:12px}.card .d{color:#999;font-size:10px;margin:2px 0}
.card .v{font-family:monospace;font-size:11px;color:#aaa}.card .v b{color:#0f0;font-weight:normal}
.card .edit{margin-top:4px;display:flex;gap:3px}.card .edit input{width:46px;background:#1a1a2a;border:1px solid#444;color:#eee;padding:2px 3px;font-size:10px;font-family:monospace;text-align:center;border-radius:2px}
.card .edit label{font-size:9px;color:#666}
.ball{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:4px}
.toast{position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:99;background:rgba(0,0,0,.9);color:#0f0;padding:7px 22px;border-radius:6px;font-size:13px;display:none}
</style></head><body>
<div id="view"><canvas id="c"></canvas></div>
<div id="bar">
 <div id="bar-head"><h2>标定中心</h2><div class="tip">拖拽=移动 | WASD=微调 | Shift=加速</div></div>
 <button class="btn btn-cap" onclick="doCapture()">📷 截取画面</button>
 <div class="tip" id="info" style="margin:4px 14px"></div>
 <div id="bar-body"></div>
 <button class="btn btn-save" onclick="doSave()">💾 保存</button>
 <div class="tip" style="text-align:center;color:#555;margin:8px 0">拖拽=移动 | WASD=微调 | 点卡片=选中</div>
</div><div id="toast" class="toast"></div>
<script>
let img=null,roi={},active='',c,ctx,drag=false,dox=0,doy=0;
const CLR=['#ff0','#f80','#09f','#0f0','#f0f','#0ff','#f44','#fc0'];
c=document.getElementById('c');ctx=c.getContext('2d');
async function api(url,opt){let r=await fetch(url,opt||{});return r.json()}
async function doCapture(){
 let j=await api('/api/capture',{method:'POST'});if(j.error){toast(j.error,'#f44');return}
 img=new Image();img.onload=()=>{c.width=img.width;c.height=img.height;ctx.drawImage(img,0,0);drawAll()};
 img.src='data:image/jpeg;base64,'+j.image;document.getElementById('info').textContent='分辨率: '+img.width+'x'+img.height;
}
function drawAll(){
 if(!img||!Object.keys(roi).length)return;ctx.drawImage(img,0,0);let ci=0;
 for(let k in roi){let v=roi[k];if(!v||v[2]<2||v[3]<2){ci++;continue}
  let[x,y,w,h]=v,co=CLR[ci%CLR.length],sel=k===active;ci++;
  ctx.strokeStyle=co;ctx.lineWidth=sel?3:1.5;ctx.strokeRect(x,y,w,h);
  ctx.fillStyle=co;ctx.font='bold 10px monospace';let ty=y-4;if(ty<12)ty=y+h+13;ctx.fillText(k,x+2,ty);
  if(sel){ctx.strokeStyle='#fff';ctx.lineWidth=1;ctx.setLineDash([4,2]);ctx.strokeRect(x-1,y-1,w+2,h+2);ctx.setLineDash([])}
}}
function cp(e){let r=c.getBoundingClientRect();return {x:(e.clientX-r.left)*(c.width/r.width),y:(e.clientY-r.top)*(c.height/r.height)}}
c.onmousedown=e=>{if(!img||!active)return;let p=cp(e),v=roi[active];if(!v||v[2]<2)return;let[x,y,w,h]=v;if(p.x>=x&&p.x<=x+w&&p.y>=y&&p.y<=y+h){drag=true;dox=p.x-x;doy=p.y-y;c.style.cursor='grabbing'}}
c.onmousemove=e=>{if(!drag)return;let p=cp(e),v=roi[active];if(!v)return;v[0]=Math.round(p.x-dox);v[1]=Math.round(p.y-doy);drawAll();updateCard(active)}
c.onmouseup=()=>{drag=false;c.style.cursor='crosshair'};c.onmouseleave=()=>{drag=false}
document.addEventListener('keydown',e=>{if(!active||!img)return;if(document.activeElement&&document.activeElement.tagName==='INPUT')return;let v=roi[active];if(!v)return;let s=e.shiftKey?10:1,h=true;switch(e.key){case'w':case'ArrowUp':v[1]-=s;break;case's':case'ArrowDown':v[1]+=s;break;case'a':case'ArrowLeft':v[0]-=s;break;case'd':case'ArrowRight':v[0]+=s;break;default:h=false}if(h){e.preventDefault();drawAll();updateCard(active)}})
function selectROI(k){active=k;renderCards();if(img)drawAll()}
function updateCard(k){let v=roi[k];if(!v)return;let el=document.getElementById('card-'+k);if(!el)return;el.querySelector('.v').innerHTML='[<b>'+v[0]+'</b>, <b>'+v[1]+'</b> <b>'+v[2]+'</b>x<b>'+v[3]+'</b>]';let inps=el.querySelectorAll('input');if(inps.length>=4){inps[0].value=v[0];inps[1].value=v[1];inps[2].value=v[2];inps[3].value=v[3]}}
function updNum(k,i,val){let v=roi[k];if(!v)return;v[i]=parseInt(val)||0;updateCard(k);if(img)drawAll()}
function renderCards(){let h='',ci=0;for(let k in roi){let v=roi[k],co=CLR[ci%CLR.length],sel=k===active;ci++;let vt=v&&v[2]>1?'[<b>'+v[0]+'</b>, <b>'+v[1]+'</b> <b>'+v[2]+'</b>x<b>'+v[3]+'</b>]':'未标定';h+='<div class="card'+(sel?' sel':'')+'" id="card-'+k+'" onclick="selectROI(\''+k+'\')" style="border-left-color:'+co+'"><div class="n"><span class="ball" style="background:'+co+'"></span>'+k.toUpperCase()+'</div><div class="v">'+vt+'</div>';if(v&&v[2]>1){h+='<div class="edit"><label>X</label><input value="'+v[0]+'" onchange="upNum(\''+k+'\',0,this.value)"><label>Y</label><input value="'+v[1]+'" onchange="upNum(\''+k+'\',1,this.value)"><label>W</label><input value="'+v[2]+'" onchange="upNum(\''+k+'\',2,this.value)"><label>H</label><input value="'+v[3]+'" onchange="upNum(\''+k+'\',3,this.value)"></div>'}h+='</div>'}document.getElementById('bar-body').innerHTML=h}
async function doSave(){let d={};for(let k in roi){let v=roi[k];if(v&&v[2]>1)d[k]=v}let j=await api('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});toast(j.ok?'已保存':j.error)}
function toast(m,c){let t=document.getElementById('toast');t.textContent=m;t.style.display='block';t.style.color=c||'#0f0';setTimeout(()=>t.style.display='none',2000)}
(async function(){let j=await api('/api/rois');roi=j;renderCards()})();
</script></body></html>"""

    def add_roi(self, name: str, x: int, y: int,
                w: int, h: int, desc: str = ""):
        self._rois[name] = {"x": x, "y": y, "w": w, "h": h, "desc": desc}

    def _export_dict(self) -> dict:
        out = {}
        for name, r in self._rois.items():
            out[name] = [r["x"], r["y"], r["w"], r["h"], r.get("desc", "")]
        return out

    def load_from_file(self, path: str) -> None:
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            for name, coords in data.items():
                if len(coords) >= 4:
                    self.add_roi(name, *coords[:4],
                                 desc=coords[4] if len(coords) > 4 else "")

    def start(self, port: int = 5050, blocking: bool = True):
        @self._app.route("/calibrate")
        def calibrate_page():
            return render_template_string(_CALIBRATE_HTML)

        print(f"[Calibration] http://127.0.0.1:{port}/calibrate")
        self._app.run(host="127.0.0.1", port=port,
                       debug=False, use_reloader=False)

    def start_threaded(self, port: int = 5050):
        from threading import Thread
        t = Thread(target=self.start, kwargs={"port": port, "blocking": True},
                   daemon=True)
        t.start()
        return t
