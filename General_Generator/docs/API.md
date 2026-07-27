# Navigation REST API

启动导航服务后，任何语言都能通过 HTTP 调用。

## 启动

```bash
game-automator serve reachable.png
# 服务监听 http://127.0.0.1:5001
```

## 端点

### POST /api/plan

规划从起点到终点的路径。

```json
// Request
{"start": [1000, 500], "goal": [2000, 800]}

// Response
{
  "path": [[1000,500], [1020,520], ..., [2000,800]],
  "length": 45
}
```

### POST /api/step

传入当前位置，返回下一步应执行的动作。

```json
// Request
{"x": 1015, "y": 510}

// Response
{
  "action": "MOVE_SE",        // 动作名, null=已到达
  "arrived": false,           // 是否已到达终点
  "waypoint": [1020, 520]     // 当前目标路标
}
```

### POST /api/cancel

取消当前导航。

```json
// Request: {}  →  Response: {"ok": true}
```

### GET /api/status

查看导航状态。

```json
// Response
{
  "arrived": false,
  "waypoint": [1020, 520],
  "path_length": 45
}
```

---

# Python SDK API

## CaptureSource (抽象基类)

```python
class CaptureSource(ABC):
    def read(self) -> Optional[np.ndarray]: ...
    def resolution(self) -> Tuple[int, int]: ...
    def release(self) -> None: ...
```

实现类：`OBSVideoCapture` / `MSSScreenCapture` / `ADBVideoCapture`

## MapStitcher

```python
stitcher = MapStitcher(min_movement=25, canvas_w=None, canvas_h=None)
canvas, dx, dy, conf = stitcher.add_frame(frame)
stitcher.save("map.jpg")
stitcher.reset()
```

## Pathfinder

```python
pf = Pathfinder("reachable.png", shrink=80)
path = pf.plan(start, goal)          # List[(x,y)] or None
reachable = pf.is_reachable((x, y))  # bool
```

## Navigator

```python
nav = Navigator(pathfinder, driver, waypoint_reach=25, deviation_threshold=100)
path = nav.set_route(start, goal)    # 规划路径
action = nav.step(current_pos)       # 每帧调用
nav.cancel()                         # 取消
```

## AbstractDriver

```python
class AbstractDriver(ABC):
    @abstractmethod
    def execute(self, action: Actions, duration_ms: int = 100) -> None: ...
    @abstractmethod
    def release_all(self) -> None: ...
    @abstractmethod
    def click(self, x: int, y: int) -> None: ...
```

## Actions (8方向 + 战斗 + 交互)

```
MOVE_N  MOVE_S  MOVE_W  MOVE_E
MOVE_NE MOVE_NW MOVE_SE MOVE_SW

ATTACK  DASH
SKILL_1 SKILL_2 SKILL_3 SKILL_4
INTERACT CANCEL
```

## CalibrationServer

```python
calib = CalibrationServer(capture, roi_file="rois.json")
calib.add_roi("exp", 963, 1045, 50, 25, desc="经验值")
calib.load_from_file("existing.json")
calib.start(port=5050)
```

---

# 多语言接入指南

框架启动 REST API 后（`game-automator serve`），任何语言通过 HTTP 调用。

## 按键精灵 (VBScript)

```vb
Set http = CreateObject("MSXML2.XMLHTTP")

' 1. 规划
http.Open "POST", "http://127.0.0.1:5001/api/plan", False
http.SetRequestHeader "Content-Type", "application/json"
http.Send "{""start"":[5000,6000],""goal"":[8000,4000]}"

' 2. 导航
Do
    posX = GetPlayerX() : posY = GetPlayerY()
    http.Open "POST", "http://127.0.0.1:5001/api/step", False
    http.SetRequestHeader "Content-Type", "application/json"
    http.Send "{""x"":" & posX & ",""y"":" & posY & "}"
    action = ParseAction(http.ResponseText)  ' 提取action字段

    Select Case action
        Case "MOVE_N":  KeyPress "W", 1
        Case "MOVE_S":  KeyPress "S", 1
        Case "MOVE_W":  KeyPress "A", 1
        Case "MOVE_E":  KeyPress "D", 1
        Case "MOVE_NE": KeyPress "W", 1 : KeyPress "D", 1
        Case "MOVE_NW": KeyPress "W", 1 : KeyPress "A", 1
        Case "MOVE_SE": KeyPress "S", 1 : KeyPress "D", 1
        Case "MOVE_SW": KeyPress "S", 1 : KeyPress "A", 1
        Case Else: Exit Do
    End Select
    Delay 500
Loop
```

## AutoHotkey

```autohotkey
whr := ComObject("WinHttp.WinHttpRequest.5.1")
whr.Open("POST", "http://127.0.0.1:5001/api/plan", false)
whr.SetRequestHeader("Content-Type", "application/json")
whr.Send("{""start"":[5000,6000],""goal"":[8000,4000]}")

Loop {
    whr.Open("POST", "http://127.0.0.1:5001/api/step", false)
    whr.SetRequestHeader("Content-Type", "application/json")
    whr.Send("{""x"":" GetPlayerX() ",""y"":" GetPlayerY() "}")
    result := whr.ResponseText
    if InStr(result, """MOVE_N""")      Send "w"
    else if InStr(result, """MOVE_S""") Send "s"
    else if InStr(result, """MOVE_W""") Send "a"
    else if InStr(result, """MOVE_E""") Send "d"
    else Break
    Sleep 500
}
```

## JavaScript / Node.js

```js
const BASE = 'http://127.0.0.1:5001';
const res = await fetch(`${BASE}/api/plan`, {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({start:[5000,6000],goal:[8000,4000]})});

const ACT = {MOVE_N:['w'],MOVE_S:['s'],MOVE_W:['a'],MOVE_E:['d'],
    MOVE_NE:['w','d'],MOVE_NW:['w','a'],MOVE_SE:['s','d'],MOVE_SW:['s','a']};

while(true) {
    const pos = getPosition();
    const r = await fetch(`${BASE}/api/step`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({x:pos.x,y:pos.y})});
    const {action,arrived} = await r.json();
    if(arrived||!action) break;
    ACT[action].forEach(k=>pressKey(k));
    await sleep(500);
}
```

## curl

```bash
# 规划
curl -s -X POST http://127.0.0.1:5001/api/plan \
  -H "Content-Type: application/json" \
  -d '{"start":[5000,6000],"goal":[8000,4000]}'

# 步进
curl -s -X POST http://127.0.0.1:5001/api/step \
  -H "Content-Type: application/json" \
  -d '{"x":5010,"y":5990}'
# => {"action":"MOVE_SE","arrived":false,"waypoint":[5020,5980]}

# 状态
curl -s http://127.0.0.1:5001/api/status
```

## 动作名对照表

| 动作名 | 方向 | 地图坐标 |
|--------|------|---------|
| `MOVE_N` | 上 | Y-=1 |
| `MOVE_S` | 下 | Y+=1 |
| `MOVE_W` | 左 | X-=1 |
| `MOVE_E` | 右 | X+=1 |
| `MOVE_NE` | 右上 | X+=1,Y-=1 |
| `MOVE_NW` | 左上 | X-=1,Y-=1 |
| `MOVE_SE` | 右下 | X+=1,Y+=1 |
| `MOVE_SW` | 左下 | X-=1,Y+=1 |
| `null` | 到达 | - |

---

# 用户指南: 对接自定义游戏

三步搞定：

### 1. 实现底層 Driver

```python
from game_automator.driver import AbstractDriver, Actions

class MyGameDriver(AbstractDriver):
    def execute(self, action, duration_ms=100):
        key_map = {
            Actions.MOVE_N: 'w', Actions.MOVE_S: 's',
            Actions.MOVE_W: 'a', Actions.MOVE_E: 'd',
            Actions.ATTACK: 'j', Actions.INTERACT: 'f',
        }
        if action in key_map:
            press_key(key_map[action], duration_ms)

    def release_all(self):
        release_all_keys()

    def click(self, x, y):
        mouse_click(x, y)  # 游戏窗口坐标系
```

### 2. 建图 + 标定

```bash
game-automator stitch -c 1 -o MyGame_map.jpg
# 用 reachability_map 工具标定可达区
game-automator calibrate -c 1 -o MyGame_rois.json
```

### 3. 写导航主循环

```python
cap = OBSVideoCapture()
pf = Pathfinder("MyGame_reachable.png")
driver = MyGameDriver()
nav = Navigator(pf, driver)
nav.set_route(start, goal)

while not nav.arrived:
    frame = cap.read()
    pos = locate_player(frame)      # 你的定位逻辑
    action = nav.step(pos)
    if action:
        driver.execute(action)
```
