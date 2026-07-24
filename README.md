# DeadMaze Game Automation

OBS + YOLO + EasyOCR + A* pathfinding auto patrol/combat/supply system.

## Quick Start

```bash
python navigator.py map_output_reachable.png --map map_output.jpg
```

## Windows

| Window | Content |
|--------|---------|
| **Nav** (1050x720) | Map + path + supply panel |
| **Status** (960x540) | OBS feed(OCR/YOLO boxes) + stats + skills + zombies + config |

## Patrol Setup

| Action | Function |
|--------|----------|
| Left-click #1 | Set start point S |
| Left-click #2+ | Add waypoint |
| Right-click | Set goal G (A* plan) |
| Enter | Start navigation |
| M | Loop patrol (S->WP1->...->S->...) |
| H | Manual return to campfire |
| R | Reset all |

## Skills

| Requirement | Note |
|-------------|------|
| **Skill slot 2** | Must place healing skill in slot 2 (skill_2) |
| **Cooldown** | Set all 4 skill cooldowns at startup; recommend game CD + 2s |

## Supply

| Warning | Note |
|---------|------|
| **Max 8 food items** | More than 8 food items may cause OCR detection failure |

## Hotkeys

| Key | Function |
|-----|----------|
| `-=` | Nav zoom |
| IJKL | Nav pan |
| F | Console config all params |
| O/P | Quick adjust return threshold |
| W | Toggle weapon detect mode |
| 1/2/3/4 | Manual skill release |
| E | Skill toggle |
| Space | Pause/Resume |
| Q | Quit |

## Combat Rules

| Rule | Trigger | Action |
|------|---------|--------|
| Threat | >=2 | Return to campfire + supply |
| Heal | HP < 80% | Use skill_2 when ready |
| Escape | HP < 20% | Space dash -> A* to nearest WP -> skip 5 |
| Low stat | H/T/S < 15 | Auto return + supply |
| Enter combat | HP>=70% + zombies<6 within 600px | Chase nearest -> attack at 130px |
| Weapon empty | Organize bag -> slot color match | Return -> enter campfire -> stop |

## Exit Conditions

1. Weapon empty -> return -> enter campfire -> program stop
2. Supply exhausted (food/water still low after supply) -> program stop
3. Manual Q

## Calibration Tools

```bash
python AImaneuver/ocr_reader.py          # Status OCR ROI
python AImaneuver/hp_detector.py         # HP bar ROI
python AImaneuver/food_ocr_calibrate.py  # Food tooltip ROI
python test_weapon_detect.py             # Weapon slot detection
```

## Config (F key in console)

| Param | Default | Description |
|-------|---------|-------------|
| WP Reach | 25 | Waypoint reach threshold(px) |
| Deviation | 100 | Path deviation replan distance(px) |
| Move Dur | 0.5 | Key press duration(s) |
| Goal Reach | 100 | Goal reach threshold(px) |
| Lookahead | 90 | Lookahead waypoint distance(px) |
| Zombie Rng | 600 | Combat search radius(px) |
| Attack Rng | 130 | Attack range(px) |
| Chase s | 7 | Chase timeout(s) |
| Low Stat | 15 | Low stat return threshold |
