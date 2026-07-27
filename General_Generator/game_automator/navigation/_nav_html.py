"""前端HTML"""

_NAV_HTML = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Navigation Test</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font:13px sans-serif;background:#1a1a2e;color:#eee;display:flex;height:100vh;overflow:hidden}
#panel{width:300px;min-width:180px;max-width:600px;resize:horizontal;overflow:auto;background:#1e1e2e;padding:10px;display:flex;flex-direction:column;gap:6px;flex-shrink:0}
#panel h2{color:#0ff;font-size:15px}
#panel input,button{width:100%;padding:5px;background:#0f0f1a;border:1px solid#444;color:#eee;font-size:11px;border-radius:3px}
#panel button{cursor:pointer;margin:2px 0}
.btn-plan{background:#3b82f6}.btn-go{background:#10b981}.btn-stop{background:#ef4444}.btn-vp{background:#f59e0b;color:#000}.btn-ext{background:#6366f1}
#log{background:#0f0f1a;color:#aaa;font-size:10px;padding:6px;border-radius:3px;min-height:50px;max-height:120px;overflow-y:auto;font-family:monospace;line-height:1.4}
#log .dim{color:#666}
#vpWrap{border:2px solid #f90;border-radius:4px;line-height:0;position:relative}
#vpWrap .lbl{position:absolute;top:2px;left:2px;background:rgba(0,0,0,.7);color:#f90;font-size:9px;padding:1px 4px}
canvas#cvp{display:block;width:100%}
#ob{max-height:60px;overflow:hidden}
#ob img{width:100%;object-fit:contain}
#steps{display:flex;gap:3px}#steps div{flex:1;padding:3px;background:#333;text-align:center;font-size:8px}
#main{flex:1;overflow:auto;background:#0a0a0f;display:flex;flex-direction:column;min-width:200px}
.info{color:#888;font-size:10px}
</style></head><body>
<div id="panel">
 <h2>Navigation Test</h2>
 <div class="info" style="color:#f90">OBS viewport (640x360):</div>
 <div id="vpWrap"><div class="lbl">OBS captures this</div><canvas id="cvp" width="640" height="360"></canvas></div>
 <div class="info">Full map (L-click=start, Shift+L-click=goal):</div>
 <label>Start <input id="startXY" value="150,150"></label>
 <label>Goal <input id="goalXY" value="150,750"></label>
 <button class="btn-plan" onclick="doPlan()">Plan Path</button>
 <details open style="margin:2px 0"><summary style="color:#0ff;font-size:12px;cursor:pointer">Navigation Params</summary>
  <div style="font-size:10px;color:#aaa;margin:2px 0">Shrink <input id="shrink" value="{{sh}}" style="width:50px;float:right"></div>
  <div style="font-size:10px;color:#aaa;margin:2px 0">WP Reach <input id="wpReach" value="{{wp}}" style="width:50px;float:right"></div>
  <div style="font-size:10px;color:#aaa;margin:2px 0">Goal Reach <input id="goalReach" value="{{gr}}" style="width:50px;float:right"></div>
  <div style="font-size:10px;color:#aaa;margin:2px 0">Lookahead <input id="lookahead" value="{{la}}" style="width:50px;float:right"></div>
  <button class="btn-plan" style="margin-top:4px" onclick="location.href='/?wp='+document.getElementById('wpReach').value+'&gr='+document.getElementById('goalReach').value+'&la='+document.getElementById('lookahead').value+'&sh='+document.getElementById('shrink').value">Apply Nav Params</button>
 </details>
 <button class="btn-go" onclick="doStep()">Step Forward</button>
 <button class="btn-go" id="btnSim" onclick="toggleSim()" style="background:#8b5cf6">Auto Sim</button>
 <button class="btn-vp" onclick="testOBS()">Test OBS</button>
 <button class="btn-vp" id="btnLive" onclick="toggleLive()" style="background:#e90;color:#000">Live OBS</button>
 <button class="btn-ext" onclick="toggleExt()">Ext Control</button>
 <div class="info" style="margin-top:4px">VBS speed/delay:</div>
 <div style="display:flex;gap:4px">
  <input id="vbsSpd" value="8" style="flex:1" placeholder="speed">
  <input id="vbsDly" value="200" style="flex:1" placeholder="delay ms">
 </div>
 <button class="btn-go" onclick="genVBS()" style="background:#6366f1">Generate VBS</button>
 <button class="btn-stop" onclick="location.reload()">Reset</button>
 <textarea id="vbsOut" style="display:none;width:100%;height:120px;background:#0f0f1a;border:1px solid#444;color:#0f0;font-size:9px;font-family:monospace;margin-top:4px" readonly></textarea>
 <div id="steps"><div id="stCap">Capt</div><div id="stTrk">Track</div><div id="stDec">Decide</div><div id="stMov">Move</div></div>
 <div id="log"></div>
 <div id="ob"></div>
</div>
<div id="main"><canvas id="c"></canvas></div>
<script>
const VW=640,VH=360,BASE='http://127.0.0.1:5001';
let start=[150,150],goal=[150,750],path=[],sim=[150,150];
let img=null,mapB64='{{map_b64}}',simTimer=null,liveTimer=null,extTimer=null;
let c=document.getElementById('c'),ctx=c.getContext('2d');
let cvp=document.getElementById('cvp'),vctx=cvp.getContext('2d');

function log(m,c){let l=document.getElementById('log');l.innerHTML='<span'+(c?' style=color:'+c:'')+'>'+m+'</span><br>'+l.innerHTML;if(l.children.length>30)l.lastChild.remove()}
function flash(id){let e=document.getElementById(id);e.style.background='#0f0';setTimeout(()=>e.style.background='#333',400)}

// Map image
if(mapB64){img=new Image();img.onload=drawAll;img.src='data:image/png;base64,'+mapB64}

function drawAll(){
 let mw=img?img.width:900,mh=img?img.height:900;
 // Full map canvas
 let s=Math.min((window.innerWidth-320)/mw,(window.innerHeight-20)/mh,.8);
 c.width=mw*s;c.height=mh*s;
 ctx.fillStyle='#0a0a0f';ctx.fillRect(0,0,c.width,c.height);
 if(img)ctx.drawImage(img,0,0,c.width,c.height);
 let sc=c.width/mw;
 if(start){ctx.fillStyle='#0f0';ctx.beginPath();ctx.arc(start[0]*sc,start[1]*sc,6,0,Math.PI*2);ctx.fill()}
 if(goal){ctx.fillStyle='#00f';ctx.beginPath();ctx.arc(goal[0]*sc,goal[1]*sc,6,0,Math.PI*2);ctx.fill()}
 for(let i=1;i<path.length;i++){ctx.strokeStyle='#3b82f6';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(path[i-1][0]*sc,path[i-1][1]*sc);ctx.lineTo(path[i][0]*sc,path[i][1]*sc);ctx.stroke()}
 ctx.fillStyle='#ff0';ctx.beginPath();ctx.arc(sim[0]*sc,sim[1]*sc,8,0,Math.PI*2);ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.beginPath();ctx.arc(sim[0]*sc,sim[1]*sc,10,0,Math.PI*2);ctx.stroke()
 ctx.strokeStyle='#f90';ctx.lineWidth=2;ctx.setLineDash([4,4]);ctx.strokeRect((sim[0]-VW/2)*sc,(sim[1]-VH/2)*sc,VW*sc,VH*sc);ctx.setLineDash([])
 // Viewport canvas
 vctx.fillStyle='#0a0a0f';vctx.fillRect(0,0,VW,VH);
 if(img){let vx=sim[0]-VW/2,vy=sim[1]-VH/2;vctx.drawImage(img,-vx,-vy)}
 vctx.strokeStyle='#f00';vctx.lineWidth=2;
 vctx.beginPath();vctx.moveTo(VW/2-15,VH/2);vctx.lineTo(VW/2+15,VH/2);vctx.stroke();
 vctx.beginPath();vctx.moveTo(VW/2,VH/2-15);vctx.lineTo(VW/2,VH/2+15);vctx.stroke();
 vctx.beginPath();vctx.arc(VW/2,VH/2,8,0,Math.PI*2);vctx.stroke()
}

c.onclick=function(e){
 let r=c.getBoundingClientRect();
 let mx=Math.round((e.clientX-r.left)/r.width*(img?img.width:900));
 let my=Math.round((e.clientY-r.top)/r.height*(img?img.height:900));
 if(e.shiftKey){goal=[mx,my];document.getElementById('goalXY').value=mx+','+my}
 else{start=[mx,my];sim=[mx,my];document.getElementById('startXY').value=mx+','+my;document.getElementById('simPos')?document.getElementById('simPos').value=mx+','+my:0}
 drawAll()
}

async function doPlan(){
 let r=await fetch(BASE+'/api/plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({start:start,goal:goal})});
 let j=await r.json();path=j.path||[];log('Plan: '+j.length+' pts','#0f0');drawAll()
}

async function doStep(){
 let r=await fetch(BASE+'/api/step',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:sim[0],y:sim[1]})});
 let j=await r.json();
 if(j.error){log(j.error,'#f44');return}
 if(j.arrived||!j.action){log('Arrived!','#0f0');return}
 if(j.waypoint){let dx=j.waypoint[0]-sim[0],dy=j.waypoint[1]-sim[1],d=Math.sqrt(dx*dx+dy*dy),spd=15;if(d>0){sim[0]=Math.round(sim[0]+dx/d*spd);sim[1]=Math.round(sim[1]+dy/d*spd)}}
 log('Step: '+j.action);drawAll()
}

async function testOBS(){
 let r=await fetch(BASE+'/api/capture');let j=await r.json();
 if(j.error){log(j.error,'#f44');return}
 document.getElementById('ob').innerHTML='<img src="data:image/jpeg;base64,'+j.image+'">';
 log('OBS: '+j.shape[0]+'x'+j.shape[1],'#0f0')
}

function toggleLive(){
 let b=document.getElementById('btnLive');
 if(liveTimer){clearInterval(liveTimer);liveTimer=null;b.textContent='Live OBS';b.style.background='#e90';log('Live stopped','#888');return}
 b.textContent='Live ON';b.style.background='#0f0';log('Live started...','#0f0');
 liveTimer=setInterval(async()=>{
  try{
   let cr=await fetch(BASE+'/api/capture');let cj=await cr.json();
   if(cj.error){document.getElementById('ob').innerHTML='<div style=color:#f44;font-size:10px>'+cj.error+'</div>';return}
   if(!cj.image)return;
   let tr=await fetch(BASE+'/api/track',{method:'POST'});let tj=await tr.json();
   let dxy=tj.dxy?' dxy=('+tj.dxy[0]+','+tj.dxy[1]+')':'';
   document.getElementById('ob').innerHTML='<img src="data:image/jpeg;base64,'+cj.image+'"><div style=font-size:9px;color:#0f0>'+cj.shape[0]+'x'+cj.shape[1]+' | '+tj.method+dxy+'</div>';
  }catch(e){}
 },1500)
}

function toggleSim(){
 let b=document.getElementById('btnSim');
 if(simTimer){clearInterval(simTimer);simTimer=null;b.textContent='Auto Sim';b.style.background='#8b5cf6';return}
 b.textContent='Running';b.style.background='#ef4444';
 if(!path.length){doPlan().then(()=>{if(!path.length)return;_startSim()})}else _startSim()
}
function _startSim(){
 simTimer=setInterval(async()=>{
  // 1. Capture
  flash('stCap');let cr=await fetch(BASE+'/api/capture');let cj=await cr.json();
  if(cj.image)document.getElementById('ob').innerHTML='<img src="data:image/jpeg;base64,'+cj.image+'">';
  // 2. Track: OBS detects displacement → updates position
  flash('stTrk');let tr=await fetch(BASE+'/api/track',{method:'POST'});let tj=await tr.json();
  if(tj.dxy && (Math.abs(tj.dxy[0])>0.3 || Math.abs(tj.dxy[1])>0.3)){
   sim[0] += tj.dxy[0]; sim[1] += tj.dxy[1];
   log('Track: dXY=('+tj.dxy[0].toFixed(1)+','+tj.dxy[1].toFixed(1)+') pos=('+sim[0]+','+sim[1]+')','#0f0');
  }
  // 3. Decide: Navigator uses tracked position
  flash('stDec');let r=await fetch(BASE+'/api/step',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:sim[0],y:sim[1]})});let j=await r.json();
  if(j.arrived||!j.action){toggleSim();log('Arrived!','#0f0');return}
  flash('stMov');drawAll()
 },1000)
}

async function genVBS(){
 let spd=parseInt(document.getElementById('vbsSpd').value)||8;
 let dly=parseInt(document.getElementById('vbsDly').value)||200;
 let sx=start[0],sy=start[1],gx=goal[0],gy=goal[1];
 let r=await fetch(BASE+'/vbs_template'); let tpl=await r.text();
 let vbs=tpl.replace(/{SX}/g,sx).replace(/{SY}/g,sy).replace(/{GX}/g,gx).replace(/{GY}/g,gy).replace(/{SPD}/g,spd).replace(/{DLY}/g,dly);
 let ta=document.getElementById('vbsOut');
 ta.style.display='block';ta.value=vbs;ta.select();
 log('VBS ready','#0f0');
}

function toggleExt(){
 if(extTimer){clearInterval(extTimer);extTimer=null;log('Ext OFF','#888');return}
 log('Ext ON - polling','#0f0');
 fetch(BASE+'/api/report',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:sim[0],y:sim[1]})});
 extTimer=setInterval(async()=>{
  let r=await fetch(BASE+'/api/position');let j=await r.json();
  if(j.pos&&(j.pos[0]!==sim[0]||j.pos[1]!==sim[1])){sim[0]=j.pos[0];sim[1]=j.pos[1];drawAll()}
 },500)
}
</script></body></html>"""
