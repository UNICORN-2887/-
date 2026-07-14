# DeadMaze 自动化导航系统 - 使用指南

## 环境准备

```bash
pip install -r requirements.txt
```

### 额外安装
- **OBS Studio** + 虚拟摄像头插件（画面采集）
- **Tesseract OCR**（后续 OCR 用，暂不必须）
  - 下载: https://github.com/UB-Mannheim/tesseract/wiki
- **Label Studio**（数据标注用，暂不必须）

---

## 工具总览

| 工具 | 功能 | 对应阶段 |
|------|------|----------|
| `map_stitcher.py` | 拼接大地图 | 阶段1: 建图 |
| `map_tracker.py` | 实时定位追踪 | 阶段2: 定位 |
| `reachability_map.py` | 标注可达/不可达区域 | 阶段3: 可达图 |
| `pathfinder.py` | A* 寻路可视化 | 阶段4: 路径规划 |
| `navigator.py` | 导航闭环（定位+路径+操控） | 阶段5: 自动导航 |
| `screenshots_capture.py` | OBS 截图采集 | 辅助: 截图 |
| `game_controller.py` | 后台 WASD 操控 | 底层: 操控 |
| `threshold_viewer.py` | 二值化阈值调试 | 辅助: 阈值 |
| `map_cropper.py` | FastSAM 物体切割 | 辅助: 抠图 |

---

## 阶段1: 拼接大地图

在游戏里走一圈，自动拼接出完整地图。

```bash
python map_stitcher.py [-c 摄像头索引] [-m 最小位移] [-o 输出文件]
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `-c` / `--camera` | `1` | OBS 虚拟摄像头索引 |
| `-m` / `--min-move` | `25` | 最小位移阈值(px)，低于此不拼接 |
| `-o` / `--output` | `map_output.jpg` | 输出文件名 |
| `--crop` | 自动 | 裁剪区域 `x,y,w,h` |

### 操作

| 按键 | 功能 |
|------|------|
| `A` | 切换自动拼接模式 |
| `C` | 手动拼接当前帧 |
| `T` | 切换裁剪框显示 |
| `IJKL` | 微调裁剪框位置 |
| `+/-` | 缩放裁剪框 |
| `S` | 保存地图（同时保存裁剪配置到 `map_stitcher_crop.json`） |
| `R` | 重置地图 |
| `Q` | 退出 |

### 使用步骤
1. 启动 OBS 虚拟摄像头
2. 启动游戏，走到一个角落
3. 运行 `python map_stitcher.py`
4. 按 `T` 显示裁剪框，用 `IJKL` 调到只覆盖游戏世界（排除 HUD/侧边栏）
5. 按 `A` 开启自动拼接
6. 在游戏里走一圈覆盖所有区域
7. 按 `S` 保存

---

## 阶段2: 实时定位追踪

在地图上定位角色当前位置。

```bash
python map_tracker.py [地图图片] [-c 摄像头索引]
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `map` | `map_output.jpg` | 拼接好的地图 |
| `-c` / `--camera` | `1` | 摄像头索引 |

### 操作

| 操作 | 功能 |
|------|------|
| 鼠标左键点击地图 | 设定初始位置 |
| `A` | 切换自动追踪（每秒5次） |
| 空格 | 手动追踪一次 |
| 滚轮 / `+` `-` | 缩放地图 |
| `R` | 重置 |
| `Q` | 退出 |

### 使用步骤
1. 走到一个特征明显的标志物旁
2. 在下方地图上找到该标志物 → 点击
3. 自动精确匹配 → 按 `A` 自动追踪
4. 绿色框 = 当前画面在地图上的位置，红色箭头指向当前位置

---

## 阶段3: 标注可达/不可达区域

从地图中标记哪些区域可以行走，哪些是障碍。

```bash
python reachability_map.py [地图图片] [-o 输出文件]
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `image` | `map_output.jpg` | 拼接好的地图 |
| `-o` / `--output` | `{name}_reachable.png` | 输出二值图 |

### 初始化
启动时自动检测地图黑色外围 → 标记为不可达。内部全白（可达）。

如果已有标注文件 `{name}_reachable.png`，自动加载继续编辑（**断点续标**）。

### 操作

| 操作 | 功能 |
|------|------|
| 左键拖拽 | 涂白（标记为可行走） |
| 右键拖拽 | 涂黑（标记为障碍） |
| `P` / `M` | 切换描边/涂刷模式 |
| `1` `2` `3` `4` | 画笔大小 (4/12/30/80 px) |
| `IJKL` | 平移 | `+` `-` | 缩放 |
| `T` | 切换视图（叠加/二值/原图） |
| `C` | HSV 颜色分割（自动检测地面） |
| `G` | 形态学闭合（填补小孔） |
| `E` | 形态学腐蚀 |
| `D` | 形态学膨胀 |
| `S` | 手动保存 |
| `R` | 重置 |
| `Q` | 自动保存 + 退出 |

### 描边模式（`P` 切换）

沿物体轮廓描多边形，一键填充大区域：

| 操作 | 功能 |
|------|------|
| 左键点击 | 添加多边形顶点 |
| 右键点击 | 闭合 + 填充黑色（障碍） |
| 中键 / `Enter` | 闭合 + 填充白色（可行走） |
| `Esc` | 取消当前描边 |

### 使用步骤
1. `python reachability_map.py map_output.jpg`
2. 初始化后自动标好外围黑边
3. 大块墙壁/建筑 → 按 `P` 进入描边模式 → 沿轮廓点一圈 → 右键填充
4. 小块/边缘 → 按 `P` 切回涂刷 → 鼠标拖拽修边
5. 按 `Q` 自动保存退出

---

## 阶段4: A* 寻路（可视化）

在可达图上测试路径规划效果。

```bash
python pathfinder.py [可达图] [--map 原图] [-s 缩边像素]
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `reachable` | `map_output_reachable.png` | 二值可达图 |
| `--map` | `map_output.jpg` | 原图（用于背景显示） |
| `-s` / `--shrink` | `8` | 缩边像素（越大路径越靠中间） |

### 缩边原理
腐蚀可达区域 → A* 被迫走中间宽阔区域 → 不贴墙。

| `[` `]` | 调整缩边距离 |
|------|------|
| 青色线 | 缩边后的网格边界 |

### 操作

| 操作 | 功能 |
|------|------|
| 左键 | 设起点（绿色 S） |
| 右键 | 设终点（红色 G） |
| `Enter` | 执行 A* 寻路 |
| `[` `]` | 调整缩边 |
| `R` | 清除 |
| `IJKL` `+` `-` | 平移/缩放 |
| `S` | 保存路径图 |
| `Q` | 退出 |

---

## 阶段4: A* 寻路（可视化）

在可达图上测试路径规划效果。

```bash
python pathfinder.py [可达图] [--map 原图] [-s 缩边像素]
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `reachable` | `map_output_reachable.png` | 二值可达图 |
| `--map` | `map_output.jpg` | 原图（用于背景显示） |
| `-s` / `--shrink` | `8` | 缩边像素（越大路径越靠中间） |

---

## 阶段5: 自动导航闭环

实时定位 + A* 路径 + 8方向操控。

```bash
python navigator.py [可达图] [--map 原图] [-c 摄像头]
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `reachable` | `map_output_reachable.png` | 可达图 |
| `--map` | `map_output.jpg` | 原图 |
| `-c` / `--camera` | `1` | 摄像头索引 |

### 阈值配置（`navigator.py` 头部）

| 参数 | 含义 |
|------|------|
| `WAYPOINT_REACH_THRESHOLD` | 距路标多少像素算到达 |
| `GOAL_REACH_THRESHOLD` | 距终点多少像素算到达（比路标宽松） |
| `PATH_DEVIATION_THRESHOLD` | 偏离路径多少像素触发重规划 |
| `MOVE_DURATION` | 每次按键时长(秒) |
| `TRACK_INTERVAL` | 追踪间隔(秒) |
| `LOOKAHEAD_DIST` | 向前看多少像素选下一个路标 |
| `SHRINK` | 缩边像素（0=贴墙，越大越走中间） |

### 门近距参数（距门 `DOOR_PROXIMITY` px 内自动切换）

| 参数 | 含义 |
|------|------|
| `DOOR_MOVE_DURATION` | 门附近按键时长（更小步防越界） |
| `DOOR_WAYPOINT_REACH` | 门附近路标到达判定 |
| `DOOR_PATH_DEVIATION` | 门附近偏离阈值（更宽松） |
| `DOOR_LOOKAHEAD` | 门附近前视距离 |

### 操作

| 操作 | 功能 |
|------|------|
| 左键点击地图 | 设定起点 = 当前位置 |
| 右键点击地图 | 设定终点 → 自动 A* 规划 |
| `Enter` | 开始导航（先测试控制器 W+D 各 0.2s） |
| 空格 | 暂停/继续 |
| `Esc` | 停止 |
| 滚轮 / `+` `-` | 缩放地图 |
| `IJKL` / 中键拖拽 | 平移 |
| `Q` | 退出 |

### 特性

- **缩边**: A* 网格腐蚀边缘，路径自动走中间
- **回头路切除**: 去掉走进去又走回来的死胡同
- **8方向同时按键**: 斜方向 W+D 等同时按下
- **门近距切换**: 距门 200px 自动缩小步长、放宽偏离
- **断点吸附**: 缩边后起点不可达自动 BFS 找最近可达格

---

## 新地图完整流程

```
1. 建图
   python map_stitcher.py -o map_mazon.jpg
   # 走一圈，按 S 保存

2. 可达图
   python reachability_map.py map_mazon.jpg
   # 描边 + 涂刷标注，按 Q 保存
   # → 生成 map_mazon_reachable.png

3. 路径测试
   python pathfinder.py map_mazon_reachable.png --map map_mazon.jpg
   # 点起点终点，Enter 看路径效果

4. 追踪验证
   python map_tracker.py map_mazon.jpg
   # 点击定位，A 自动追踪，确认定位准确

5. 自动导航
   python navigator.py map_mazon_reachable.png --map map_mazon.jpg
   # 点起点终点，Enter 开始导航
```

---

## 多地图管理

```
DeadMaze/
├── map_mazon.jpg              # Mazon College 地图
├── map_mazon_reachable.png    # Mazon 可达图
├── map_deadmaze.jpg           # DeadMaze 主地图
├── map_deadmaze_reachable.png
└── ...
```

每个地图只需要一张拼接图 + 一张可达图，所有工具通过参数切换。
