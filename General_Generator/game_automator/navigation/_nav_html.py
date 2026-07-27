"""前端HTML"""

_NAV_HTML = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Navigation Test</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font:14px sans-serif;background:#1a1a2e;color:#eee;display:flex;height:100vh;overflow:hidden}
#panel{width:300px;min-width:180px;background:#1e1e2e;padding:10px;display:flex;flex-direction:column;gap:6px;overflow-y:auto;flex-shrink:0}
#handle{width:5px;background:#444;cursor:col-resize;flex-shrink:0}
#handle:hover,#handle:active{background:#3b82f6}
#main{flex:1;overflow:auto;background:#0a0a0f;display:flex;flex-direction:column;min-width:200px}
#panel h2{color:#0ff;font-size:15px}
.info{color:#888;font-size:10px}
#panel input{width:100%;padding:4px;background:#0f0f1a;border:1px solid#444;color:#eee;font-size:11px}
#panel button{width:100%;padding:6px;border:none;border-radius:3px;cursor:pointer;font-size:12px;margin:2px 0}
.btn-plan{background:#3b82f6;color:#fff}.btn-go{background:#10b981;color:#fff}
.btn-stop{background:#ef4444;color:#fff}.btn-obs{background:#f59e0b;color:#000}
#log{background:#0f0f1a;color:#aaa;font-size:10px;padding:6px;border-radius:3px;min-height:60px;max-height:150px;overflow-y:auto;font-family:monospace;line-height:1.4;flex-shrink:0}
#obsPreview img{max-height:70px!important;object-fit:contain}
#steps{display:flex;gap:3px}
#steps div{flex:1;padding:3px;background:#333;border-radius:2px;text-align:center;font-size:8px}
</style></head><body>
<div id="panel">
 <h2>Navigation Test</h2>
 <div class="info" style="color:#f90">OBS viewport:</div>
 <div style="border:2px solid #f90;border-radius:4px;line-height:0">
  <canvas id="cvp" width="400" height="300"></canvas>
 </div>
 <div class="info">Full map (click: L=start, Shift+L=goal):</div>
 <label>Start <input id="startXY" value="150,150"></label>
 <label>Goal <input id="goalXY" value="750,750"></label>
 <button class="btn-plan" onclick="doPlan()">Plan Path</button>
 <details style="margin:2px 0"><summary style="color:#888;font-size:11px;cursor:pointer">Params</summary>
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
 <button class="btn-go" id="btnExt" onclick="toggleExt()" style="background:#6366f1">Ext Control</button>
 <button class="btn-stop" onclick="location.reload()">Reset</button>
 <div id="steps">
  <div id="stCap">Capt</div><div id="stTrk">Track</div><div id="stDec">Decide</div><div id="stMov">Move</div>
 </div>
 <div id="log"></div>
 <div id="obsPreview"></div>
</div>
<div id="handle"></div>
<div id="main">
 <canvas id="c" style="flex:1"></canvas>
</div>

<script>
const VW=400, VH=300, BASE='http://127.0.0.1:5001';
let start=[150,150], goal=[750,750], path=[], sim=[150,150];
let c=document.getElementById('c'), ctx=c.getContext('2d');
let cvp=document.getElementById('cvp'), vctx=cvp.getContext('2d');
let img=null, mapB64='{{map_b64}}', simTimer=null;

// Divider drag
let h=document.getElementById('handle'), panel=document.getElementById('panel');
let dragging=false, startX=0, startW=0;
h.onmousedown=function(e){dragging=true;startX=e.clientX;startW=panel.offsetWidth;document.body.style.cursor='col-resize'}
document.onmousemove=function(e){if(!dragging)return;panel.style.width=(startW+e.clientX-startX)+'px'}
document.onmouseup=function(){dragging=false;document.body.style.cursor=''}

function flash(id){let e=document.getElementById(id);e.style.background='#0f0';setTimeout(()=>e.style.background='#333',400)}
function log(m){let l=document.getElementById('log');l.innerHTML=m+'<br>'+l.innerHTML;if(l.children&&l.children.length>30)l.lastChild.remove()}

if(mapB64){img=new Image();img.onload=drawAll;img.src='data:image/png;base64,'+mapB64}

// 轮询外部控制位置 (按键精灵等)
let extMode=false, extPoll=null;
function toggleExt(){
 extMode=!extMode;
 if(extMode){
  // 将当前sim位置设为外部控制的起点
  fetch(BASE+'/api/report',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:sim[0],y:sim[1]})});
  extPoll=setInterval(async()=>{
   let r=await fetch(BASE+'/api/position');let j=await r.json();
   if(j.pos && (j.pos[0]!==sim[0]||j.pos[1]!==sim[1])){
    sim[0]=j.pos[0];sim[1]=j.pos[1];drawAll()
   }
  },500);
  log('Ext mode ON - polling /api/position')
 }else{
  clearInterval(extPoll);extPoll=null;log('Ext mode OFF')
 }
}

function drawAll(){
 let mw=img?img.width:900,mh=img?img.height:900;
 let s=Math.min(window.innerWidth*0.6/mw, (window.innerHeight-20)/mh, 1);
 c.width=mw*s;c.height=mh*s;
 let sc=c.width/mw;
 // 全览图
 ctx.fillStyle='#0a0a0f';ctx.fillRect(0,0,c.width,c.height);
 if(img)ctx.drawImage(img,0,0,c.width,c.height);
 if(start){ctx.fillStyle='#0f0';ctx.beginPath();ctx.arc(start[0]*sc,start[1]*sc,6,0,Math.PI*2);ctx.fill()}
 if(goal){ctx.fillStyle='#00f';ctx.beginPath();ctx.arc(goal[0]*sc,goal[1]*sc,6,0,Math.PI*2);ctx.fill()}
 for(let i=1;i<path.length;i++){ctx.strokeStyle='#3b82f6';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(path[i-1][0]*sc,path[i-1][1]*sc);ctx.lineTo(path[i][0]*sc,path[i][1]*sc);ctx.stroke()}
 ctx.fillStyle='#ff0';ctx.beginPath();ctx.arc(sim[0]*sc,sim[1]*sc,8,0,Math.PI*2);ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.beginPath();ctx.arc(sim[0]*sc,sim[1]*sc,10,0,Math.PI*2);ctx.stroke()
 ctx.strokeStyle='#f90';ctx.lineWidth=2;ctx.setLineDash([4,2]);ctx.strokeRect((sim[0]-VW/2)*sc,(sim[1]-VH/2)*sc,VW*sc,VH*sc);ctx.setLineDash([])

 // 视口
 vctx.fillStyle='#0a0a0f';vctx.fillRect(0,0,VW,VH);
 if(img){
  let vx=sim[0]-VW/2, vy=sim[1]-VH/2;
  vctx.drawImage(img, -vx, -vy);
 }
 vctx.strokeStyle='#f00';vctx.lineWidth=2;
 vctx.beginPath();vctx.moveTo(VW/2-15,VH/2);vctx.lineTo(VW/2+15,VH/2);vctx.stroke();
 vctx.beginPath();vctx.moveTo(VW/2,VH/2-15);vctx.lineTo(VW/2,VH/2+15);vctx.stroke();
 vctx.beginPath();vctx.arc(VW/2,VH/2,8,0,Math.PI*2);vctx.stroke()
}

c.onclick=function(e){
 let r=c.getBoundingClientRect();
 let iw=img?img.width:900, ih=img?img.height:900;
 let mx=Math.round((e.clientX-r.left)/r.width*iw);
 let my=Math.round((e.clientY-r.top)/r.height*ih);
 if(e.shiftKey){goal=[mx,my];document.getElementById('goalXY').value=mx+','+my}
 else{start=[mx,my];sim=[mx,my];document.getElementById('startXY').value=mx+','+my;document.getElementById('simPos').value=mx+','+my}
 drawAll()
}

async function doPlan(){
 let r=await fetch(BASE+'/api/plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({start:start,goal:goal})});
 let j=await r.json();path=j.path;log('Path: '+j.length+' pts');drawAll()
}

async function doStep(){
 let r=await fetch(BASE+'/api/step',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:sim[0],y:sim[1]})});
 let j=await r.json();if(j.arrived||!j.action){log('Arrived!');return}
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
 await fetch(BASE+'/api/track',{method:'POST'});
 simTimer=setInterval(async()=>{
  flash('stCap');let cr=await fetch(BASE+'/api/capture');let cj=await cr.json();
  if(cj.image){document.getElementById('obsPreview').innerHTML='<img src="data:image/jpeg;base64,'+cj.image+'" style="width:100%;border:1px solid#555">'}
  flash('stTrk');let tr=await fetch(BASE+'/api/track',{method:'POST'});let tj=await tr.json();
  if(tj.dxy && (Math.abs(tj.dxy[0])>0.5||Math.abs(tj.dxy[1])>0.5)){sim[0]+=tj.dxy[0];sim[1]+=tj.dxy[1];log('Track: dxy=('+tj.dxy[0]+','+tj.dxy[1]+') '+tj.method)}
  else if(tj.dxy){log('Track: still conf='+tj.conf+' '+tj.method)}
  flash('stDec');let r=await fetch(BASE+'/api/step',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:sim[0],y:sim[1]})});let j=await r.json();
  if(j.arrived||!j.action){toggleSim();log('Arrived!');return}
  flash('stMov');if(j.waypoint){let dx=j.waypoint[0]-sim[0],dy=j.waypoint[1]-sim[1],d=Math.sqrt(dx*dx+dy*dy),spd=12;if(d>0){sim[0]=Math.round(sim[0]+dx/d*spd);sim[1]=Math.round(sim[1]+dy/d*spd)}}
  document.getElementById('simPos').value=sim[0]+','+sim[1];drawAll()
 },1000)
}
</script></body></html>"""
