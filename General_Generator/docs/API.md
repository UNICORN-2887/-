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
