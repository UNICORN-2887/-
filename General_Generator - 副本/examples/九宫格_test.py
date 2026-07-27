"""Python 九宫格测试 - 用框架 REST API 测试导航

运行:
  1. game-automator serve grid_reachable.png   (另一个终端)
  2. python 九宫格_test.py
"""

import urllib.request, json, time
import cv2, numpy as np
import os

BASE = "http://127.0.0.1:5001"
HERE = os.path.dirname(__file__)
GRID = os.path.join(HERE, "grid_reachable.png")

# 1. 生成最小测试可达图 (300x300, 全白=全部可达)
if not os.path.exists(GRID):
    os.makedirs(HERE, exist_ok=True)
    img = np.full((300, 300), 255, dtype=np.uint8)
    cv2.imwrite(GRID, img)
    print(f"已生成测试可达图: {GRID}")
else:
    print(f"使用已有可达图: {GRID}")

def api(method, path, data=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type":"application/json"} if data else {},
        method=method)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())

# 2. 规划路径 (九宫格: 中心→右下角)
start = (150, 150)  # 中心
goal  = (280, 280)  # 右下角
print(f"\n规划: {start} → {goal}")
result = api("POST", "/api/plan", {"start": start, "goal": goal})
path = result.get("path", [])
print(f"路径: {len(path)} 个点")
print(f"前3点: {path[:3]}...")
print(f"最后点: {path[-1]}")

# 3. 模拟导航 (从起点沿路径走)
print(f"\n模拟导航:")
pos = list(start)
for step_i in range(min(20, len(path) * 2)):
    result = api("POST", "/api/step", {"x": pos[0], "y": pos[1]})
    action = result.get("action")
    arrived = result.get("arrived", False)
    wp = result.get("waypoint")

    if arrived or action is None:
        print(f"  ✅ 到达! ({pos[0]},{pos[1]})")
        break

    # 模拟移动: 向路标方向移动
    if wp:
        dx = wp[0] - pos[0]
        dy = wp[1] - pos[1]
        dist = (dx*dx + dy*dy) ** 0.5
        speed = min(30, dist)
        if dist > 0:
            pos[0] += int(dx / dist * speed)
            pos[1] += int(dy / dist * speed)

    if step_i % 3 == 0:
        print(f"  步{step_i}: pos=({pos[0]},{pos[1]}) action={action} wp={wp}")

print(f"\n测试完成!")
