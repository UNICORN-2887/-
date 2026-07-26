# CHANGELOG

## 2026-07-27 — 框架封装 + 地图审核 + 网站整合 + 问题修复

### game-automator 框架
- 新增 `GameAutomator` 封装类 — 三行代码完成寻路导航
- `Navigator` 加 lookahead(90px) + goal_reach(100px) + 卡住检测
- `PositionTracker` 改为 LK 光流追踪 (goodFeaturesToTrack + calcOpticalFlowPyrLK)
- CLI 新增 `game-automator reachable` 命令 (可达区标定)
- `Navigator.step()` 完全对齐 DeadMaze `navigate_step()` 时序

### 地图审核系统
- 新增 `admin_panel.py` — 网页审核面板 (http://127.0.0.1:8888)
- 自动扫描 QQ 邮箱 [DeadMaze提交] 标题邮件
- Message-ID 去重 + 批准即解压到 map/ 目录
- 新增 `admin_review.py` — 终端审核工具

### 项目整理
- 地图文件重命名为 MazonAcademy/Lakeview18 系列
- 创建 map/ 目录，11 个地图子文件夹
- 文件归类: OBS_profiles/ / tools/ / test/
- 删除旧备份和临时文件
- 软著申请文件加入 .gitignore (含个人信息)

### 网站 (blog.219882.xyz)
- 新增 "纯光流建图寻路框架" 页面 (game-automator)
- Mermaid 架构图 + 模块职责表 + CLI 命令表
- DeadMaze 网站加 OBS 场景配置说明 + 地图下载页 + 提交页
- 导航栏 "链接" 菜单整合三个项目
- 标定网页说明加摄像头选择

### Bug 修复
- OpenCV GUI 冲突: easyocr 等包强制依赖 headless → setup.bat 后装 opencv-python 覆盖
- 批处理中文乱码 → 全部改为 ASCII
- run_*.bat 加 conda activate brain (PowerShell 用错 Python)
- 删除死滑块 return_thr (实际用 low_stat_thr)
- compute_direction 改回 DeadMaze best_direction 内积法
- _resample 重采样修复 4px 细网格全跳过
- cv2.destroyAllWindows() 加 try/except 保护

---

## 2026-07-26 — 标定中心 + PushPlus + 一键部署 + 官网文档

### 标定中心 `/calibrate`
- 新增 `calibrate.html` — 独立 HTML 前端 (脱离内联模板避免缓存问题)
- 1920 原生分辨率截图 + 鼠标拖拽移动 ROI + WASD/方向键微调
- 实时预览: 每 2s 自动刷新画面 + OCR + HP + 武器检测结果
- `/api/preview` 端点: 返回截图 + OCR(6状态) + HP(绿色占比) + 武器(颜色匹配)
- `/api/reset` 端点: 重置为本地 JSON 文件值
- OCR 与导航器 `_read_status_values` 完全一致 (en模型 + 放大6x + allowlist数字)
- HP 检测: HSV 绿色掩码 → 绿像素占比
- 武器检测: 颜色匹配参考色 RGB(80,39,19) → match_ratio > thr → 空
- 所有区域拆分为独立卡片: ocr_exp/hunger/thirst/stamina/threat/open + hp + weapon + inventory + food

### PushPlus 微信推送
- 网页配置面板新增 "NOTIFY 通知" 区块 (pushplus_token)
- `_push_notify(title, content, cooldown=60)` — 同 title 60s 内不重复发送
- 触发场景: 武器耗尽停止、HP过低脱战、Threat≥2返航、低状态返航
- 每条推送含完整状态摘要 (HP/H/T/S/Thr)

### 一键部署
- `setup.bat` — 检测 Python → pip install 依赖 → 检测 Tesseract → 提示 OBS
- `run_config.bat` — 启动配置中心 + 自动打开浏览器
- `run_navigator.bat` — 启动导航 + 操作提示
- Python 脚本自动安装缺失依赖 (importlib 检测 → subprocess pip install)
- config_server.py 可独立运行，不依赖 navigator
- 端口冲突检测: navigator 启动时若 config_server 已在运行则跳过

### 配置面板升级
- 新增 "GAME 游戏设置" 区块: 游戏路径配置
- 启动器保留 (加速器路径)
- `requirements.txt` 更新为完整依赖列表
- `.gitignore` 加例外规则: YOLO best.pt + FastSAM-s.pt 纳入仓库

### 官网文档 (blog.219882.xyz/deadmaze/)
- 单页 HTML 深色主题，左侧导航 + 右侧内容
- 章节: 概述/快速开始/环境安装/配置标定/导航使用/战斗系统/补给系统/参数说明/FAQ/进阶/截图
- 进阶教程三步: 光流建图 → 可达区标定 → 导航验证 (完整键位表+参数+技巧)
- README.md 重写: 快速开始+键位表+参数表+项目结构
- 截图占位 (onerror 自动隐藏) → 待用户放入图片

### 待续工作
- ⏳ 网站截图: 5 张图放入 public/deadmaze/ → push 即上线
- ⏳ 补给点击坐标标定工具 (click_points.json 各按钮点位因分辨率不同需标定)
- ⏳ YOLO 自定义模型再训练教程
- ⏳ 多地图支持与建图模板

---

## 2026-07-25 — 武器检测 + Threat规则 + 双窗口 + 重进火堆

### 武器检测
- 每15s点organize_bag整理背包 → 颜色匹配第一格(RGB 80,39,19)
- 空槽判定: Tol=20 Thr=0.3, 匹配率>30%=无武器
- W键切换手动/自动模式
- 武器耗尽 → 返航 → 进火堆 → 停止程序(不补给)
- 独立标定工具: test_weapon_detect.py (S保存weapon_roi.json)

### Threat规则
- Threat≥2 → 立刻返航补给 (与低状态同样流程)

### 双窗口
- Nav窗: 纯地图导航
- Status窗(960x540): 左=大YOLO画面+OCR框, 右=状态+技能+僵尸+配置

### 重进火堆
- 完全复制首次进火堆逻辑: YOLO 5帧 + 8次点击等1.5s OCR
- 3次食用后自动离开→重进火堆, 重置计数器

### 退出条件
1. 武器耗尽 → 返航 → 进火堆 → 停止
2. 补给后H/T仍<15 → 停止

## 2026-07-24 — 收尾修复

- OCR: 灰度6x放大直读, 拼接所有数字, >200约束
- 补给后drain OBS 3秒再读状态 (防火堆UI旧帧)
- 食物OCR: 扫描间清缓冲1s, 拖拽后drain 3s
- 火堆交互: 仅returning_home时触发
- Deviation: 60→100
- 移除Enter测试按键(W/D)
- 斜向移动: key_down同时按 → sleep → key_up同时放
- 补给系统OCR: 拼接数字+>200约束 (两处统一)
- 途径点3次检测(0/0.5/1.0s) + 强制YOLO刷新
- 攻击范围: 70→130px, 搜索半径: 300→600px
- 墙检测: 可达图锥形射线±15°
- 追击超时7s + 途径点总战斗超时60s
- is_simulate守卫修复

## 2026-07-23 — 战斗系统 + 自动返航 + 收尾

### 战斗规则
- 规则1: HP<80%自动补血(skill_2)
- 规则2: HP<20%空格脱战→A*回最近途径点→跳过5点
- 规则3: Hunger/Thirst/Stamina任一<15 → 自动H返航补给
- 进入战斗: HP≥70% + 600px内僵尸<6 → 追最近→攻击(130px内)
- 墙检测: 可达图锥形射线±15°, >50%阻塞=墙后剔除
- 防呆: 追击超时7s切换目标, 途径点战斗总超时60s强制脱战
- 攻击→追击: 僵尸跑出130px切回chasing
- 途径点检测: 0s/0.5s/1.0s三次YOLO检测
- 补给后检查: 仍低→终止程序; H≥100,T≥100,S≥50→返回巡逻

### 右侧状态栏
- HP血条 + Hunger + Thirst + Stamina
- 技能冷却进度条
- 战斗模式+目标+方向
- YOLO画面(黄色TARGET框标注当前追击僵尸)
- 僵尸列表(标注墙后)
- 玩家坐标

### 快捷键
M=循环 R=重置 1-4=技能 E=技能开关

## 2026-07-23 — 巡逻系统重写 + 战斗技能 + 补给集成

### navigator.py 巡逻系统
- **多途径点巡逻**: 左键第1次=起点, 后续左键=添加途径点, 右键=终点
- **逐段导航**: `self.goal` 动态变化, 到达当前目标后自动切下一段
- **M键循环巡逻**: S → WP1 → WP2 → ... → WPn → S(等3s) → WP1 → ...
- **途径点等待**: 到达途径点停止移动, 原地等待3秒后自动前往下一个
- **R键重置**: 清除起点/途径点/终点/路径
- **8方向移动**: `key_down` 同时按下多键 → `sleep` → `key_up` 同时释放, 真正斜向
- **偏离重规划修复**: `plan_path(to_goal_only=True)` 保持当前goal, 不会回到WP1

### navigator.py 技能系统
- **SkillCooldown**: 4技能(1/2/3/4键)独立冷却管理
- **自动释放**: 导航中冷却完毕自动释放, 每步最多一个
- **渲染面板**: 右上角冷却进度条 + 剩余秒数
- **启动配置**: 启动时可输入冷却时间, 保存到 `skill_cooldowns.json`
- **快捷键**: 1/2/3/4手动释放, E开关

### navigator.py 补给系统
- **虚拟饱食度**: 进入火堆OCR读初始值, 后续用基准+已吃累加, 不再依赖OCR实时读取
- **补给面板**: 窗口左上角显示虚拟值/已吃总量/推荐/物品列表
- **用户确认**: 决策后暂停等输入 y=吃 / n=跳过 / q=离开
- **火堆交互**: 仅按H返航时触发

### navigator.py YOLO寻怪
- 导航中每步YOLO检测僵尸种类和数量
- 窗口右侧显示YOLO实时画面 + 僵尸统计

### 新增文件
| 文件 | 功能 |
|------|------|
| `AImaneuver/supply_test_panel.py` | 统一测试面板 |
| `AImaneuver/supply_step_test.py` | 手动逐步调试工具 |
| `AImaneuver/supply_check.py` | 火堆补给检测 |
| `AImaneuver/supply_decision.py` | 补给决策引擎 |
| `AImaneuver/food_ocr_calibrate.py` | 食物/水 OCR标定 |
| `test_skills.py` | 技能自动释放测试 |

### 快捷键总览 (navigator)
| 键 | 功能 |
|----|------|
| 左键 | 起点 / 添加途径点 |
| 右键 | 终点 |
| Enter | 开始导航 |
| H | 返航 |
| M | 循环巡逻 |
| R | 全部重置 |
| 1/2/3/4 | 手动释放技能 |
| E | 技能开关 |
| 空格 | 暂停/继续 |
| IJKL | 平移地图 |
| +/- | 缩放 |
| Q | 退出 |

### OBS 帧同步原理
```
问题: time.sleep() 期间不调 cv2.waitKey()
→ Windows DShow 消息循环阻塞 → OBS 虚拟摄像头不推送新帧

解决: 等待期间持续 grab() + waitKey(1)
→ 消息循环正常 → DShow 实时推送 → 拿到最新帧
```
