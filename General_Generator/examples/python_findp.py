"""Auto-generated Navigator Script (ServerTrack - Phase Correlation)"""
import urllib.request, json, math, time

BASE = "http://127.0.0.1:5001"

def post(path, data=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(f"{BASE}{path}", data=body,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())

# 1. Plan
res = post("/api/plan", {"start": [150, 150], "goal": [741, 813]})
print(f"Plan: {res['length']} pts")

# 2. Navigate with ServerTrack
px, py = 150, 150
for i in range(300):
    # 2a. ServerTrack: phase-correlation position correction
    try:
        tk = post("/api/track_frame", {"x": px, "y": py})
        if tk.get("conf", 0) > 0.5:
            px, py = tk["pos"]
    except Exception:
        pass

    # 2b. Step: get direction from corrected position
    res = post("/api/step", {"x": px, "y": py})
    if res.get("arrived") or not res.get("action"):
        print(f"Arrived! ({px}, {py})")
        break

    # 2c. Move toward waypoint
    wp = res.get("waypoint")
    if wp:
        dx, dy = wp[0] - px, wp[1] - py
        dist = math.hypot(dx, dy)
        if dist > 1:
            px += int(dx / dist * 8)
            py += int(dy / dist * 8)

    # 2d. Report position
    post("/api/report", {"x": px, "y": py})

    if i % 10 == 0:
        print(f"Step {i}: ({px}, {py}) wp={wp} action={res.get('action')}")

    time.sleep(200 / 1000.0)

print("Done!")
