# CHANGELOG

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
