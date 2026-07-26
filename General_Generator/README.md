# game-automator

通用游戏自动化框架。提供画面采集、光流建图、可达区编辑、A*寻路、导航控制的标准实现。

## 安装

```bash
pip install -e .          # 开发模式 (可编辑)
# 或
pip install game-automator # 正式发布后
```

## 快速开始

```bash
# 光流建图
game-automator stitch -c 1 -o mymap.jpg

# ROI 标定
game-automator calibrate -c 1 -o my_rois.json

# 启动导航 API
game-automator serve mymap_reachable.png -c 1
```

## Python SDK

```python
from game_automator import (
    OBSVideoCapture, MapStitcher, Pathfinder, Navigator, Actions
)
from game_automator.driver import AbstractDriver

# 1. 实现底层驱动
class MyDriver(AbstractDriver):
    def execute(self, action, duration_ms=100):
        # 映射到你的游戏按键
        pass
    def release_all(self): pass
    def click(self, x, y): pass

# 2. 采集 + 建图
cap = OBSVideoCapture()
stitcher = MapStitcher()
frame = cap.read()
stitcher.add_frame(frame)
stitcher.save("map.jpg")

# 3. 寻路
pf = Pathfinder("reachable.png")
path = pf.plan((1000, 500), (2000, 800))

# 4. 导航
driver = MyDriver()
nav = Navigator(pf, driver)
nav.set_route((1000, 500), (2000, 800))
while not nav.arrived:
    pos = get_position()  # 你的定位实现
    action = nav.step(pos)
    if action:
        driver.execute(action)
```

## 目录

```
game_automator/
├── capture/      # 采集 (OBS/MSS/ADB)
├── stitching/    # 光流建图
├── mapping/      # 可达区 + A*
├── navigation/   # 导航控制 + REST API
├── calibration/  # ROI 标定
├── driver/       # 标准动作 + 抽象驱动
└── server.py     # CLI
```
