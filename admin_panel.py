"""DeadMaze 管理面板 — 浏览器中审核地图提交.

运行: python admin_panel.py → http://127.0.0.1:8888
"""

import json, re, os, imaplib, email, threading, webbrowser, time, zipfile, tempfile
from email.header import decode_header
from http.server import HTTPServer, BaseHTTPRequestHandler

IMAP_SERVER = "imap.qq.com"
EMAIL_ADDR = "2198823120@qq.com"
EMAIL_PWD = "bvbgoplsnkijecfb"
MAP_DIR = os.path.join(os.path.dirname(__file__), "map")
PORT = 8888
SUBJECT_KEY = "[DeadMaze提交]"

_cache = {"subs": [], "time": 0}

def fetch():
    if time.time() - _cache["time"] < 30 and _cache["subs"]:
        return _cache["subs"]
    submissions = []
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_ADDR, EMAIL_PWD)
        for folder in ["INBOX", '"Sent Messages"', '"Sent"']:
            try: mail.select(folder)
            except: continue
            status, msgs = mail.search(None, 'ALL')
            if status != "OK": continue
            for num in msgs[0].split()[-20:]:
                status, data = mail.fetch(num, "(RFC822)")
                if status != "OK": continue
                msg = email.message_from_bytes(data[0][1])
                subject = ""
                for s, cs in decode_header(msg["Subject"]):
                    subject += s.decode(cs or "utf-8", errors="ignore") if isinstance(s, bytes) else s
                if SUBJECT_KEY not in subject: continue
                parts = subject.replace(SUBJECT_KEY, "").strip().split("-")
                map_name = parts[0].strip() if parts else "?"
                author = parts[1].strip() if len(parts) > 1 else "?"
                version = parts[2].strip() if len(parts) > 2 else "v1"

                attachments = []
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_maintype() == 'multipart': continue
                        fn = part.get_filename()
                        if fn:
                            fname = decode_header(fn)[0][0]
                            if isinstance(fname, bytes): fname = fname.decode("utf-8", errors="ignore")
                            payload = part.get_payload(decode=True)
                            if payload:
                                attachments.append((fname, len(payload), payload))

                key = f"{map_name}|{author}|{version}|{len(attachments)}"
                if key in [s.get("_key") for s in submissions]:
                    continue  # 去重: 同邮件跨多个文件夹
                submissions.append({
                    "map": map_name, "author": author, "version": version,
                    "subject": subject, "files": [a[:2] for a in attachments],
                    "_data": attachments, "_key": key
                })
        mail.logout()
    except Exception as e:
        print(f"[邮箱] 错误: {e}")
    _cache["subs"] = submissions
    _cache["time"] = time.time()
    return submissions

def approve(index):
    subs = fetch()
    if index >= len(subs): return False, "越界"
    sub = subs[index]
    dest = os.path.join(MAP_DIR, sub["map"])
    os.makedirs(dest, exist_ok=True)
    for fname, size, data in sub["_data"]:
        if fname.lower().endswith('.zip'):
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
                tmp.write(data); tpath = tmp.name
            with zipfile.ZipFile(tpath) as zf:
                zf.extractall(dest)
            os.unlink(tpath)
        # 非zip的直接写
        elif fname.endswith(('.jpg','.png','.json')):
            with open(os.path.join(dest, fname), 'wb') as f:
                f.write(data)
    return True, f"{dest}"

HTML = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>DeadMaze Admin</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font:14px 'Microsoft YaHei',Arial;background:#1a1a2e;color:#eee;max-width:900px;margin:20px auto;padding:20px}
h1{color:#0ff;margin-bottom:4px}h1 span{color:#3b82f6}
.sub{color:#888;font-size:12px;margin-bottom:20px}
.card{background:#1e1e2e;border:1px solid#333;border-radius:8px;padding:14px;margin:10px 0}
.card .n{font-weight:bold;font-size:16px;color:#ff0}
.card .m{color:#aaa;font-size:12px;margin:4px 0}
.card .f{font-size:11px;color:#666}
.btn{padding:8px 18px;border:none;border-radius:4px;cursor:pointer;font-size:13px;margin-right:8px;font-family:inherit}
.btn-ok{background:#0a0;color:#fff}.btn-no{background:#a30;color:#fff}
.btn-refresh{background:#555;color:#fff;margin-bottom:16px}
.status{margin-top:6px;font-size:12px}
</style></head><body>
<h1><span>DeadMaze</span> 地图审核</h1>
<div class="sub">扫描 QQ 邮箱中标题含 [DeadMaze提交] 的邮件</div>
<button class="btn btn-refresh" onclick="location.reload()">🔄 刷新</button>
<div id="list">加载中...</div>
<script>
async function load(){
 let r=await fetch('/api/list');let j=await r.json();
 if(!j.subs||!j.subs.length){document.getElementById('list').innerHTML='<p style="color:#888">暂无待审核提交</p>';return}
 let h='';
 j.subs.forEach((s,i)=>{
  h+=`<div class="card">
   <div class="n">${s.map}</div>
   <div class="m">作者: ${s.author} | 版本: ${s.version}</div>
   <div class="f">附件: ${s.files.map(f=>f[0]+' ('+(f[1]/1024).toFixed(0)+'KB)').join(', ')}</div>
   <button class="btn btn-ok" onclick="act(${i},'approve')">✅ 批准 (解压到map/)</button>
   <button class="btn btn-no" onclick="act(${i},'reject')">❌ 拒绝</button>
   <div class="status" id="s${i}"></div>
  </div>`;
 });
 document.getElementById('list').innerHTML=h;
}
async function act(i,a){
 document.getElementById('s'+i).textContent='处理中...';
 let r=await fetch('/api/'+a+'?id='+i,{method:'POST'});
 let j=await r.json();
 document.getElementById('s'+i).textContent=j.ok||j.error;
}
load();
</script></body></html>"""

class Handler(BaseHTTPRequestHandler):
    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try: self.wfile.write(body)
        except: pass

    def _html(self, html, code=200):
        self.send_response(code)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def do_GET(self):
        if self.path.startswith("/favicon"):
            self.send_response(204); self.end_headers(); return
        if self.path == "/":
            return self._html(HTML)
        if self.path == "/api/list":
            subs = fetch()
            return self._json({"subs": [{k:v for k,v in s.items() if k!='_data'} for s in subs]})
        self.send_response(404); self.end_headers()

    def do_POST(self):
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        idx = int(q.get("id", [0])[0])
        if self.path.startswith("/api/approve"):
            ok, msg = approve(idx)
            return self._json({"ok": msg} if ok else {"error": msg})
        if self.path.startswith("/api/reject"):
            return self._json({"ok": "已拒绝"})
        self._json({"error":"not found"}, 404)

    def log_message(self, *args): pass

def main():
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"DeadMaze Admin Panel: http://127.0.0.1:{PORT}")
    webbrowser.open(f"http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")

if __name__ == "__main__":
    threading.Thread(target=lambda: time.sleep(0.5) or webbrowser.open(f"http://127.0.0.1:{PORT}"), daemon=True).start()
    main()
