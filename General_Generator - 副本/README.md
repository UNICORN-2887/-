# game-automator

通用游戏自动化框架。提供画面采集、光流建图、可达区编辑、A* 寻路、导航控制。

📖 **完整文档**: [blog.219882.xyz/game-automator](https://blog.219882.xyz/game-automator/)

## 安装

```bash
cd General_Generator
pip install -e .
```

## 3 分钟快速接入

```python
from game_automator import GameAutomator

# 1. 初始化 (指定地图和可达图)
auto = GameAutomator("map.jpg", "reachable.png")

# 2. 规划路径
path = auto.set_route((5000, 6000), (8000, 4000))

# 3. 导航循环
while not auto.arrived:
    pos = get_position()       # 你的定位实现
    action = auto.step(pos)    # 返回 'MOVE_NE' / 'MOVE_S' 等
    if action:
        press_keys(action)     # 你映射到游戏按键
```

## API

```python
auto = GameAutomator(
    "map.jpg", "reachable.png",
    waypoint_reach=25,   # 路标到达判定距离(px)
    goal_reach=100,       # 终点到达判定距离(px)
    lookahead=90,         # 前向路标距离(px)
    shrink=80             # 边缘缩进(px)
)

auto.set_route(start, goal)  # 规划, 返回路径列表
auto.step(current_pos)       # 返回动作名 或 None(到达)
auto.cancel()                # 取消导航
auto.path                    # 完整路径点列表
auto.current_waypoint        # 当前目标路标
auto.arrived                 # 是否已到达
```

## 动作名

| 动作 | 含义 | 按键(DeadMaze) |
|------|------|---------------|
| `MOVE_N` | 北/上 | W |
| `MOVE_S` | 南/下 | S |
| `MOVE_W` | 西/左 | A |
| `MOVE_E` | 东/右 | D |
| `MOVE_NE` | 东北 | W+D |
| `MOVE_NW` | 西北 | W+A |
| `MOVE_SE` | 东南 | S+D |
| `MOVE_SW` | 西南 | S+A |

## 模块

```
game_automator/
├── automator.py    # GameAutomator (一键封装)
├── capture/        # OBSVideoCapture / MSSScreenCapture / ADBVideoCapture
├── stitching/      # MapStitcher (光流建图)
├── mapping/        # Pathfinder (A*) + ReachabilityEditor + PositionTracker (LK光流)
├── navigation/     # Navigator + NavigationServer (REST API)
├── calibration/    # CalibrationServer (ROI 标定网页)
├── driver/         # Actions + AbstractDriver
└── server.py       # CLI: serve / stitch / calibrate
```

## 示例

`examples/deadmaze/` — DeadMaze 游戏完整集成:

```
test_full.py       # 完整导航测试 (Tracker + Pathfinder + Navigator + Controller)
driver.py          # AbstractDriver 实现示例
main.py            # 建图/标定/导航 3 个独立示例
```
