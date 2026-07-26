# 🎮 DeadMaze 游戏自动化

为 2.5D 俯视角打僵尸游戏 DeadMaze 构建的全自动 AI 系统 —— 自动寻路、智能战斗、补给返航、后台操控。

**支持地图**: MazonAcademy（已建图+标定） | **分辨率**: 1920×1080

📖 **完整文档**: [blog.219882.xyz/deadmaze](https://blog.219882.xyz/deadmaze/)

---

## 🚀 快速开始

```bash
# 1. 一键安装
setup.bat

# 2. 配置 & 标定 (浏览器操作)
run_config.bat

# 3. 启动导航
run_navigator.bat
```

或手动：

```bash
pip install -r requirements.txt
python config_server.py                    # → http://127.0.0.1:5050
python navigator.py map/MazonAcademy/MazonAcademy_reachable.png --map map/MazonAcademy/MazonAcademy.jpg
```

## 🛠 环境要求

| 组件 | 说明 |
|------|------|
| Python 3.10+ | 安装时勾选 "Add Python to PATH" |
| OBS Studio | 虚拟摄像头插件，输出 1920×1080 |
| Tesseract OCR | 可选，提高中文"开"字识别率 |

## 🗺 导航操作

| 按键 | 功能 |
|------|------|
| `左键` | 设定起点 |
| `右键` | 设定终点 (A* 规划) / 添加途径点 |
| `Enter` | 开始导航 |
| `空格` | 暂停/继续 |
| `Esc` | 停止 |
| `H` | 返航到火堆 |
| `M` | 循环巡逻 |
| `IJKL` | 平移地图 |
| `+/-` | 缩放地图 |
| `1-4` | 手动释放技能 |
| `E` | 技能自动开关 |
| `O/P` | 调节低状态阈值 |
| `Q` | 退出 |

## ⚔ 战斗规则

| 优先级 | 条件 | 动作 |
|--------|------|------|
| 1 | HP < 补血阈值 | 释放技能2 (治疗) |
| 2 | HP < 脱战阈值 | 空格脱战 → 返回途径点 |
| 3 | Threat ≥ 2 | 自动返航补给 |
| 4 | 武器空槽 | 返航火堆 → 停止程序 |
| 5 | 饱食/口渴/耐力 < 阈值 | 返航补给 |
| 6 | 正常 | 战斗/巡逻 |

## 📊 配置参数

通过网页面板 `http://127.0.0.1:5050` 修改：

| 分类 | 参数 | 默认 | 说明 |
|------|------|------|------|
| 导航 | WP Reach | 25px | 到达途径点距离 |
| 导航 | Deviation | 100px | 偏离重规划距离 |
| 导航 | Move Dur | 0.5s | 按键持续时长 |
| 导航 | Goal Reach | 100px | 到达终点距离 |
| 导航 | Lookahead | 90px | 前向路标距离 |
| 战斗 | Zombie Range | 600px | 战斗搜索半径 |
| 战斗 | Attack Range | 130px | 攻击距离 |
| 战斗 | Chase Timeout | 7s | 追击超时 |
| 战斗 | Combat Entry HP | 70% | 最低进战HP |
| 战斗 | Max Zombies | 6 | 最大进战僵尸数 |
| 状态 | Low Stat Thr | 15 | 低状态返航阈值 |
| 状态 | Heal HP | 80% | 补血触发阈值 |
| 状态 | Escape HP | 20% | 脱战触发阈值 |
| 技能 | Skill 1-4 CD | 4/12/22/32s | 技能冷却 |
| 武器 | W Tolerance | 20 | 空槽色差容差 |
| 武器 | W Threshold | 0.3 | 空槽判定阈值 |

## 📦 补给系统

- 饱食/口渴/耐力低于阈值 → 自动返航火堆
- YOLO 识别火堆 → 后台点击 → OCR 确认"开"字
- 扫描背包 8 格 → OCR 识别食物/水 + 数量
- 决策最优组合（饱食>100 且 口渴>100）
- 后台点击消耗 → 循环直到满足或无可吃

⚠ 背包食物不超过 8 个，物品名需包含"食物"或"水"

## 🔬 自定义地图

```bash
# 1. 光流建图 (用你喜欢的名字)
python map_stitcher.py -c 1 -o MyNewMap.jpg

# 2. 可达区标定
python reachability_map.py MyNewMap.jpg -o MyNewMap_reachable.png

# 3. 导航验证 (指定你的地图)
python navigator.py MyNewMap_reachable.png --map MyNewMap.jpg
```

详见 [进阶教程](https://blog.219882.xyz/deadmaze/#advanced)

## 📱 微信通知

配置 PushPlus Token 后，停止/返航/低状态等事件推送到微信。在 [pushplus.plus](https://www.pushplus.plus) 获取 token，填入网页配置面板。

## 🏗 项目结构

```
DeadMaze/
├── navigator.py              # 导航主程序
├── config_server.py          # 网页配置服务 (可独立运行)
├── calibrate.html            # ROI 标定页面
├── map_stitcher.py           # 光流法地图拼接
├── reachability_map.py       # 可达区标定编辑器
├── pathfinder.py             # A* 寻路
├── map_tracker.py            # 实时定位追踪
├── game_controller.py        # 后台键盘操控
├── AImaneuver/
│   ├── combat_dashboard.py   # 战斗总控
│   ├── ocr_reader.py         # OCR 状态读取
│   ├── hp_detector.py        # HP 血量检测
│   ├── inventory_ocr.py      # 背包 OCR
│   └── runs/detect/...       # YOLO 模型
├── setup.bat                 # 一键安装
├── run_config.bat            # 启动配置中心
├── run_navigator.bat         # 启动导航
├── map/                          # 各地图目录
│   ├── MazonAcademy/             # MazonAcademy 完整地图
│   ├── Lakeview18/               # Lakeview18 完整地图
│   ├── BodegaBay/                # BodegaBay (待标定)
│   └── ...                       # 其他地图 (待玩家提交)
├── tools/                        # 工具
│   └── DeadMazeSteam加速版.exe    # 加速版插件 (可选)
```
