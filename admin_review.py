"""
DeadMaze 地图审核工具
- 自动扫描 QQ 邮箱中标题为"[DeadMaze地图]"的邮件
- 下载 ZIP 附件，验证文件结构
- 审核通过后解压到 map/ 目录
"""
import imaplib, email, json, re, os, zipfile, tempfile, shutil
from email.header import decode_header

# ========== 配置 ==========
IMAP_SERVER = "imap.qq.com"
IMAP_PORT = 993
EMAIL_ADDR = "2198823120@qq.com"
EMAIL_PWD = "bvbgoplsnkijecfb"
MAP_DIR = os.path.join(os.path.dirname(__file__), "map")
SUBJECT_KEY = "[DeadMaze提交]"

VALID_MAPS = [
    "MazonAcademy","Lakeview18","BodegaBay","BlueMesa","WalkerRiver",
    "SunsetMall","SantaRosaDowntown","Highway99","ArizonaJurassicMuseum",
    "SacramentoSuburbs","SurvivorCamp"
]

def fetch_submissions():
    """获取所有地图提交邮件"""
    if not EMAIL_ADDR or not EMAIL_PWD:
        print("请先填写 EMAIL_ADDR 和 EMAIL_PWD")
        return []
    print(f"连接 {IMAP_SERVER}...")
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    mail.login(EMAIL_ADDR, EMAIL_PWD)

    submissions = []
    for folder in ["INBOX", '"Sent Messages"', '"已发送"']:
        try: mail.select(folder)
        except: continue
        print(f"  检查文件夹: {folder}")
        status, messages = mail.search(None, 'ALL')
        if status != "OK": continue
        msg_nums = messages[0].split()[-50:]
        for num in msg_nums:
            status, data = mail.fetch(num, "(RFC822)")
            if status != "OK": continue
            msg = email.message_from_bytes(data[0][1])
            subject = ""
            for s, charset in decode_header(msg["Subject"]):
                if isinstance(s, bytes):
                    subject += s.decode(charset or "utf-8", errors="ignore")
                else: subject += s
            if SUBJECT_KEY not in subject: continue
            print(f"    ✅ 匹配: {subject[:80]}")
            # 解析主题: [DeadMaze提交] 地图名 - 用户名 - 版本号
            parts = subject.replace(SUBJECT_KEY, "").strip().split("-")
            map_name = parts[0].strip() if parts else "Unknown"
            username = parts[1].strip() if len(parts) > 1 else "Unknown"
            version = parts[2].strip() if len(parts) > 2 else "v1"
            # 下载附件
            attachments = []
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_maintype() == 'multipart': continue
                    filename = part.get_filename()
                    if filename:
                        fname = decode_header(filename)[0][0]
                        if isinstance(fname, bytes): fname = fname.decode("utf-8", errors="ignore")
                        if fname.lower().endswith('.zip'):
                            payload = part.get_payload(decode=True)
                            if payload:
                                attachments.append((fname, payload))
            for fname, data in attachments:
                submissions.append({
                    "map_name": map_name, "username": username,
                    "version": version, "filename": fname,
                    "data": data, "subject": subject
                })
                print(f"      附件: {fname} ({len(data)/1024:.0f}KB)")
    mail.logout()
    return submissions

def validate_zip(zip_data, expected_map):
    """验证ZIP内容是否符合规范"""
    try:
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
            tmp.write(zip_data)
            tmp_path = tmp.name
        with zipfile.ZipFile(tmp_path) as zf:
            files = zf.namelist()
            has_jpg = any(f.endswith('.jpg') for f in files)
            has_reachable = any('reachable' in f.lower() and f.endswith('.png') for f in files)
            print(f"      文件列表: {files}")
            print(f"      JPG={has_jpg} ReachablePNG={has_reachable}")
            return has_jpg and has_reachable
    except Exception as e:
        print(f"      验证失败: {e}")
        return False
    finally:
        os.unlink(tmp_path)

def extract_to_map(zip_data, map_name):
    """解压ZIP到 map/ 目录"""
    dest = os.path.join(MAP_DIR, map_name)
    os.makedirs(dest, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
            tmp.write(zip_data)
            tmp_path = tmp.name
        with zipfile.ZipFile(tmp_path) as zf:
            zf.extractall(dest)
        print(f"      ✅ 已解压到: {dest}")
    finally:
        os.unlink(tmp_path)

def review():
    submissions = fetch_submissions()
    if not submissions:
        print("\n没有待审核的提交")
        return
    print(f"\n{'='*60}")
    print(f"  共 {len(submissions)} 个待审核提交")
    print(f"{'='*60}\n")
    for i, sub in enumerate(submissions):
        print(f"[{i+1}] {sub['map_name']} by {sub['username']} ({sub['version']})")
        print(f"    文件: {sub['filename']} ({len(sub['data'])/1024:.0f}KB)")
        ok = validate_zip(sub['data'], sub['map_name'])
        print(f"    验证: {'✅ 通过' if ok else '❌ 不通过'}")
        if ok:
            choice = input(f"    审核通过? (y/n/s=跳过): ").strip().lower()
            if choice == 'y':
                extract_to_map(sub['data'], sub['map_name'])
                print(f"    ✅ 已发布到地图库!")
            elif choice == 's':
                print(f"    ⏭ 跳过")
            else:
                print(f"    ❌ 已拒绝")
        print()

if __name__ == "__main__":
    if not os.path.exists(MAP_DIR):
        print(f"地图目录不存在: {MAP_DIR}")
        print("请修改 MAP_DIR 指向 DeadMaze/map/")
    else:
        review()
