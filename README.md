# DeadMaze - 光流法建图与定位

基于 ORB 特征匹配的 2.5D 游戏实时地图拼接与定位系统。

## 功能模块

| 模块 | 文件 | 功能 |
|------|------|------|
| 地图拼接 | `map_stitcher.py` | 画面拼接成大地图 |
| 实时追踪 | `map_tracker.py` | ORB 特征匹配实时定位 |
| 截图采集 | `screenshots_capture.py` | OBS 虚拟摄像头截图 |
| 后台操控 | `game_controller.py` | Win32 后台按键/点击 |
| 彩色定位 | `map_localizer_color.py` | 多通道模板匹配定位 |
| 二值定位 | `map_localizer.py` | 二值化模板匹配定位 |
| 物体切割 | `map_cropper.py` | FastSAM 交互式抠图 |
| 阈值查看 | `threshold_viewer.py` | 多种二值化对比 |
| 标注配置 | `label_studio/` | Label Studio YOLO 标注 |

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 需要额外安装:
# 1. OBS Studio + 虚拟摄像头插件
# 2. Tesseract OCR (用于后续 OCR 功能)
#    下载: https://github.com/UB-Mannheim/tesseract/wiki
# 3. Label Studio (用于数据标注)
```

## 使用流程

### 1. 拼接地图
```bash
# 在游戏里走一圈，自动拼接大地图
python map_stitcher.py
# 按 A 开始自动拼接，按 S 保存为 map_output.jpg
```

### 2. 实时定位
```bash
# 加载拼接好的地图，点击设定初始位置，自动追踪
python map_tracker.py map_output.jpg
# 点击地图设定位置 → 按 A 自动追踪 → 轨迹线显示路径
```

### 3. 数据标注
```bash
# 启动 Label Studio
label-studio start
# 导入 label_studio/labeling_config.xml 配置
# 标注标志物后导出 JSON → 用 label_helper.py 转 YOLO 格式
```

## 技术栈

- **特征匹配**: ORB (Oriented FAST + Rotated BRIEF)
- **帧间追踪**: ORB 特征点位移 + 地图 ROI 验证
- **地图拼接**: 帧间 ORB 位移累积 + 画布扩展
- **物体分割**: FastSAM (Segment Anything 轻量版)
- **后台操控**: Win32 PostMessage + AttachThreadInput

## 项目结构

```
DeadMaze/
├── map_stitcher.py          # 地图拼接
├── map_tracker.py           # 实时定位追踪
├── map_cropper.py           # 物体切割
├── map_localizer.py         # 二值化定位
├── map_localizer_color.py   # 彩色定位
├── screenshots_capture.py   # 截图采集
├── game_controller.py       # 后台操控
├── threshold_viewer.py      # 阈值可视化
├── test_background_input.py # 后台操控测试
├── label_studio/            # 标注配置
│   ├── labeling_config.xml
│   └── label_helper.py
├── requirement.txt          # 项目需求文档
├── requirements.txt         # pip 依赖
└── README.md
```
