# CHANGELOG

## 2026-07-23 — 补给系统集成

### 新增文件
| 文件 | 功能 |
|------|------|
| `AImaneuver/supply_test_panel.py` | 统一测试面板：OBS+YOLO + 状态OCR + 8格补给扫描 + 决策引擎 + 点击/悬停/拖拽测试 |
| `AImaneuver/supply_step_test.py` | 手动逐步调试工具：Enter逐格拖拽+OCR，N/P切换格子 |
| `AImaneuver/supply_check.py` | 火堆补给检测独立脚本（8格拖拽扫描+OCR） |
| `AImaneuver/supply_decision.py` | 补给决策引擎（规则一/二/三） |
| `AImaneuver/food_ocr_calibrate.py` | 食物/水 Tooltip OCR 区域标定工具 |

### 关键修复
- **OBS 帧同步**: `cap.grab() + cv2.waitKey(1)` 持续 drain 缓冲，Windows DShow 必须泵送消息循环才能收到新帧，否则永远读到旧画面
- **OCR 容错**: EasyOCR 常把 "食物" 误读为 "贪物/食钩/饮物"，用 `[食贪饮][物钩饭]` 模糊匹配
- **食物+水同时提取**: 之前 `if/elif` 只取一种，改为分别用正则提取 `食X +N` 和 `水 +N`
- **扫描间清缓冲**: 每格扫描间隙 drain 0.3s + retrieve()，仿 step_test 主循环的 `cap.read()` 效果，防止 tooltip 残留导致串位

### OBS 帧同步原理
```
问题: time.sleep() 等待期间不调 cv2.waitKey()
→ Windows DShow 消息循环阻塞 → OBS 虚拟摄像头不推送新帧
→ grab() 始终拿到同一帧旧画面 → OCR 永远慢一步

解决: 等待期间持续 grab() + waitKey(1)
→ 消息循环正常 → DShow 实时推送 → grab 拿到最新帧
```

### 拖拽方案
- 垂直拖拽替代水平拖拽
- 第一列: 从 `y=340` 往下滑到 `y=383`
- 第二列: 从 `y=460` 往上滑到 `y=423`

### 快捷键 (supply_test_panel)
| 键 | 功能 |
|----|------|
| S | 全自动补给扫描（火堆检测→读状态→扫8格→决策） |
| T | 单次OCR测试 |
| 1/C | 点击模式 |
| 2/H | 悬停模式 |
| 3/D/G | 拖拽模式 |
| Q | 退出 |
