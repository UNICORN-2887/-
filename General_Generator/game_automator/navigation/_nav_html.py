"""前端HTML (独立文件, 避免修改主逻辑)"""

_NAV_HTML = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Navigation Test</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font:14px sans-serif;background:#1a1a2e;color:#eee;display:flex;height:100vh}
#panel{width:280px;min-width:200px;max-width:500px;resize:horizontal;overflow:auto;background:#1e1e2e;padding:10px;display:flex;flex-direction:column;gap:6px}
#panel h2{color:#0ff;font-size:15px}
.info{color:#888;font-size:10px}
#panel input{width:100%;padding:4px;background:#0f0f1a;border:1px solid#444;color:#eee;font-size:11px}
#panel button{width:100%;padding:6px;border:none;border-radius:3px;cursor:pointer;font-size:12px}
.btn-plan{background:#3b82f6;color:#fff}.btn-go{background:#10b981;color:#fff}
.btn-stop{background:#ef4444;color:#fff}.btn-obs{background:#f59e0b;color:#000}
#log{background:#0f0f1a;color:#aaa;font-size:10px;padding:6px;border-radius:3px;max-height:100px;overflow-y:auto;font-family:monospace;line-height:1.4}
#steps{display:flex;gap:3px}
#steps div{flex:1;padding:3px;background:#333;border-radius:2px;text-align:center;font-size:8px}
#main{flex:1;overflow:auto;background:#0a0a0f;display:flex;flex-direction:column}
#main canvas{border-bottom:1px solid#333}
.vp-label{position:absolute;top:2px;left:2px;background:rgba(0,0,0,.7);color:#f90;font-size:9px;padding:1px 4px;border-radius:2px}
</style></head><body>
<div id="panel">
 <h2>Navigation Test</h2>
 <div class="info" style="color:#f90">OBS captures this viewport:</div>
 <div style="border:2px solid #f90;border-radius:4px;line-height:0">
  <canvas id="cvp" width="400" height="300"></canvas>
 </div>
 <div class="info">Full map (click: L=start, Shift+L=goal):</div>
 <label>Start <input id="startXY" value="150,150"></label>
 <label>Goal <input id="goalXY" value="750,750"></label>
 <button class="btn-plan" onclick="doPlan()">Plan Path</button>
 <details><summary style="color:#888;font-size:11px;cursor:pointer">Params</summary>
  <div style="font-size:10px;color:#888">WP Reach<input id="wpReach" value="{{wp}}" style="width:50px"></div>
  <div style="font-size:10px;color:#888">Goal Reach<input id="goalReach" value="{{gr}}" style="width:50px"></div>
  <div style="font-size:10px;color:#888">Lookahead<input id="lookahead" value="{{la}}" style="width:50px"></div>
  <div style="font-size:10px;color:#888">Shrink<input id="shrink" value="{{sh}}" style="width:50px"></div>
  <button class="btn-plan" style="margin-top:4px" onclick="location.href='/?wp='+document.getElementById('wpReach').value+'&gr='+document.getElementById('goalReach').value+'&la='+document.getElementById('lookahead').value+'&sh='+document.getElementById('shrink').value">Apply</button>
 </details>
 <label>Sim Pos <input id="simPos" value="150,150"></label>
 <button class="btn-go" onclick="doStep()">Step &gt;&gt;</button>
 <button class="btn-go" id="btnSim" onclick="toggleSim()" style="background:#8b5cf6">Auto Sim</button>
 <button class="btn-obs" onclick="testOBS()">Test OBS</button>
 <button class="btn-stop" onclick="location.reload()">Reset</button>
 <div id="steps">
  <div id="stCap">Capt</div><div id="stTrk">Track</div><div id="stDec">Decide</div><div id="stMov">Move</div>
 </div>
 <div id="log"></div>
 <div id="obsPreview"></div>
</div>
<div id="main">
 <canvas id="c" style="flex:1"></canvas>
</div>

<script>
const VW=400, VH=300, BASE='http://127.0.0.1:5001';
let start=[150,150], goal=[750,750], path=[], sim=[150,150];
let c=document.getElementById('c'), ctx=c.getContext('2d');
let cvp=document.getElementById('cvp'), vctx=cvp.getContext('2d');
let img=null, mapB64='{{map_b64}}', simTimer=null;

function flash(id){let e=document.getElementById(id);e.style.background='#0f0';setTimeout(()=>e.style.background='#333',400)}
function log(m){let l=document.getElementById('log');l.innerHTML=m+'<br>'+l.innerHTML;if(l.children.length>20)l.lastChild.remove()}

// Load map
if(mapB64){img=new Image();img.onload=drawAll;img.src='data:image/png;base64,'+mapB64}

function drawAll(){
 let mw=img?img.width:900, mh=img?img.height:900;
 c.width=mw; c.height=mh;
 // 全览图
 ctx.fillStyle='#0a0a0f';ctx.fillRect(0,0,mw,mh);
 if(img)ctx.drawImage(img,0,0);
 // markers
 if(start){ctx.fillStyle='#0f0';ctx.beginPath();ctx.arc(start[0],start[1],8,0,Math.PI*2);ctx.fill()}
 if(goal){ctx.fillStyle='#00f';ctx.beginPath();ctx.arc(goal[0],goal[1],8,0,Math.PI*2);ctx.fill()}
 for(let i=1;i<path.length;i++){ctx.strokeStyle='#3b82f6';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(path[i-1][0],path[i-1][1]);ctx.lineTo(path[i][0],path[i][1]);ctx.stroke()}
 // current position (yellow)
 ctx.fillStyle='#ff0';ctx.beginPath();ctx.arc(sim[0],sim[1],10,0,Math.PI*2);ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.beginPath();ctx.arc(sim[0],sim[1],12,0,Math.PI*2);ctx.stroke()
 // viewport rect
 ctx.strokeStyle='#f90';ctx.lineWidth=2;ctx.setLineDash([4,2]);ctx.strokeRect(sim[0]-VW/2,sim[1]-VH/2,VW,VH);ctx.setLineDash([])

 // 视口图
 vctx.fillStyle='#0a0a0f';vctx.fillRect(0,0,VW,VH);
 if(img){
  let vx=sim[0]-VW/2, vy=sim[1]-VH/2;
  vctx.drawImage(img, -vx, -vy);
 }
 // crosshair (player at center)
 vctx.strokeStyle='#f00';vctx.lineWidth=2;
 vctx.beginPath();vctx.moveTo(VW/2-15,VH/2);vctx.lineTo(VW/2+15,VH/2);vctx.stroke();
 vctx.beginPath();vctx.moveTo(VW/2,VH/2-15);vctx.lineTo(VW/2,VH/2+15);vctx.stroke();
 vctx.beginPath();vctx.arc(VW/2,VH/2,8,0,Math.PI*2);vctx.stroke();
 if(path.length){
  vctx.strokeStyle='rgba(59,130,246,0.4)';vctx.lineWidth=1;
  for(let i=1;i<path.length;i++){
   let vx=sim[0]-VW/2, vy=sim[1]-VH/2;
   vctx.beginPath();vctx.moveTo(path[i-1][0]-vx,path[i-1][1]-vy);vctx.lineTo(path[i][0]-vx,path[i][1]-vy);vctx.stroke()
  }
 }
}

// Click on full map
c.onclick=function(e){
 let r=c.getBoundingClientRect();
 let mx=Math.round((e.clientX-r.left)*(img?img.width:900)/c.width);
 let my=Math.round((e.clientY-r.top)*(img?img.height:900)/c.height);
 if(e.shiftKey){goal=[mx,my];document.getElementById('goalXY').value=mx+','+my}
 else{start=[mx,my];sim=[mx,my];document.getElementById('startXY').value=mx+','+my;document.getElementById('simPos').value=mx+','+my}
 drawAll()
}

async function doPlan(){
 let r=await fetch(BASE+'/api/plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({start:start,goal:goal})});
 let j=await r.json(); path=j.path; log('Path: '+j.length+' points'); drawAll()
}

async function doStep(){
 let r=await fetch(BASE+'/api/step',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:sim[0],y:sim[1]})});
 let j=await r.json();
 if(j.arrived||!j.action){log('Arrived!');return}
 if(j.waypoint){let dx=j.waypoint[0]-sim[0],dy=j.waypoint[1]-sim[1],d=Math.sqrt(dx*dx+dy*dy),spd=20;if(d>0){sim[0]=Math.round(sim[0]+dx/d*spd);sim[1]=Math.round(sim[1]+dy/d*spd)}}
 document.getElementById('simPos').value=sim[0]+','+sim[1];log('Step: '+j.action);drawAll()
}

async function testOBS(){
 let r=await fetch(BASE+'/api/capture');let j=await r.json();
 if(j.error){log('OBS ERROR: '+j.error);return}
 document.getElementById('obsPreview').innerHTML='<img src="data:image/jpeg;base64,'+j.image+'" style="width:100%;border:1px solid#555;margin-top:4px">';
 log('OBS: '+j.shape[0]+'x'+j.shape[1])
}

async function toggleSim(){
 let b=document.getElementById('btnSim');
 if(simTimer){clearInterval(simTimer);simTimer=null;b.textContent='Auto Sim';b.style.background='#8b5cf6';return}
 b.textContent='Running';b.style.background='#ef4444';
 if(!path.length)await doPlan();if(!path.length)return;
 await fetch(BASE+'/api/track',{method:'POST'}); // init tracker
 simTimer=setInterval(async()=>{
  flash('stCap');
  let cr=await fetch(BASE+'/api/capture');let cj=await cr.json();
  if(cj.image){document.getElementById('obsPreview').innerHTML='<img src="data:image/jpeg;base64,'+cj.image+'" style="width:100%;border:1px solid#555">'}

  flash('stTrk');
  let tr=await fetch(BASE+'/api/track',{method:'POST'});let tj=await tr.json();
  if(tj.dxy && (Math.abs(tj.dxy[0])>0.5||Math.abs(tj.dxy[1])>0.5)){
   sim[0]+=tj.dxy[0];sim[1]+=tj.dxy[1];log('Track: dxy=('+tj.dxy[0]+','+tj.dxy[1]+') conf='+tj.conf+' '+tj.method)
  }else if(tj.dxy){log('Track: still conf='+tj.conf+' '+tj.method)}

  flash('stDec');
  let r=await fetch(BASE+'/api/step',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:sim[0],y:sim[1]})});
  let j=await r.json();
  if(j.arrived||!j.action){toggleSim();log('Arrived!');return}

  flash('stMov');
  if(j.waypoint){let dx=j.waypoint[0]-sim[0],dy=j.waypoint[1]-sim[1],d=Math.sqrt(dx*dx+dy*dy),spd=12;if(d>0){sim[0]=Math.round(sim[0]+dx/d*spd);sim[1]=Math.round(sim[1]+dy/d*spd)}}
  document.getElementById('simPos').value=sim[0]+','+sim[1];drawAll()
 },1000)
}
</script></body></html>"""
