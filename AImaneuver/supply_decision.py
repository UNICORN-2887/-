"""
火堆补给决策引擎 - 独立测试
规则一: 双不超130 → 直接吃
规则二: 单超130 → 候选, 选总溢出最少的
规则三: 无食物/都>100 → 离开

补充: 双超130也候选 | 溢出相同时选补充量大的
"""

import json, os, time, re

# ========== 加载数据 ==========
BASE = os.path.dirname(__file__)
CLICK_FILE = os.path.join(BASE, "click_points.json")
with open(CLICK_FILE) as f:
    click_pts = json.load(f)

# 食物栏8个格子对应的点击坐标
FOOD_SLOTS = [
    ("food_col1_r1", 885, 383, 1020),
    ("food_col1_r2", 900, 383, 1020),
    ("food_col1_r3", 950, 383, 1020),
    ("food_col1_r4", 970, 383, 1020),
    ("food_col2_r1", 885, 423, 1020),
    ("food_col2_r2", 900, 423, 1020),
    ("food_col2_r3", 950, 423, 1020),
    ("food_col2_r4", 970, 423, 1020),
]

LEAVE_BTN = click_pts.get("leave_campfire", {"x": 920, "y": 313})

# ========== 决策引擎 ==========
def decide_food(status, items):
    """
    status: {'Hunger': int, 'Thirst': int}
    items: [{'name': str, 'food': int|None, 'water': int|None, 'slot': str, 'x': int, 'y': int, 'drag_start': int}]

    返回: ('eat', item) 或 ('leave', None) 或 ('none', None)
    """
    hunger = status.get("Hunger", 0)
    thirst = status.get("Thirst", 0)

    # 终止条件
    if hunger > 100 and thirst > 100:
        return ("leave", None)
    if not items:
        return ("leave", None)

    rule1_candidates = []  # 双不超130
    rule2_candidates = []  # 至少一项超130

    for item in items:
        f = item.get("food") or 0
        w = item.get("water") or 0

        if f == 0 and w == 0:
            continue

        new_h = hunger + f
        new_t = thirst + w

        over_h = max(0, new_h - 130)
        over_t = max(0, new_t - 130)
        total_overflow = over_h + over_t
        total_benefit = f + w

        if total_overflow == 0:
            rule1_candidates.append((total_benefit, item))
        else:
            rule2_candidates.append((total_overflow, -total_benefit, item))
            # 排序: 溢出少优先, 溢出相同时补充量大优先

    # 规则一: 有完美食物直接吃
    if rule1_candidates:
        rule1_candidates.sort(key=lambda x: -x[0])  # 补充量大的优先
        best = rule1_candidates[0][1]
        print(f"  [规则一] {best['name']} food+{best['food']} water+{best['water']} → 不超130, 直接吃")
        return ("eat", best)

    # 规则二: 选溢出最少的
    if rule2_candidates:
        rule2_candidates.sort(key=lambda x: (x[0], x[1]))  # (溢出, -补充量) 小优先
        best = rule2_candidates[0][2]
        overflow = rule2_candidates[0][0]
        print(f"  [规则二] {best['name']} food+{best['food']} water+{best['water']} → 溢出={overflow}, 最少浪费")
        return ("eat", best)

    return ("leave", None)


# ========== 测试 ==========
if __name__ == "__main__":
    print("=" * 50)
    print("补给决策引擎 - 单元测试")
    print("=" * 50)

    # 模拟场景1: 规则一
    s1 = {"Hunger": 80, "Thirst": 60}
    i1 = [
        {"name": "面包", "food": 20, "water": 0, "slot": "1-1", "x": 885, "y": 383, "drag_start": 1020},
        {"name": "能量饮料", "food": 20, "water": 45, "slot": "1-2", "x": 900, "y": 383, "drag_start": 1020},
    ]
    r1 = decide_food(s1, i1)
    print(f"场景1 (hunger=80,thirst=60): {r1[0]}\n")

    # 模拟场景2: 规则二 (你说的例子)
    s2 = {"Hunger": 80, "Thirst": 100}
    i2 = [
        {"name": "一号食物", "food": 30, "water": 60, "slot": "1-1", "x": 885, "y": 383, "drag_start": 1020},
        {"name": "二号食物", "food": 40, "water": 40, "slot": "1-2", "x": 900, "y": 383, "drag_start": 1020},
    ]
    r2 = decide_food(s2, i2)
    print(f"场景2 (hunger=80,thirst=100): {r2[0]}")
    print("  一号: 饱食110, 口渴160 → 水溢出30")
    print("  二号: 饱食120, 口渴140 → 水溢出10 → 应该选二号\n")

    # 模拟场景3: 终止条件
    s3 = {"Hunger": 110, "Thirst": 115}
    i3 = [{"name": "面包", "food": 20, "water": 0, "slot": "1-1", "x": 885, "y": 383, "drag_start": 1020}]
    r3 = decide_food(s3, i3)
    print(f"场景3 (hunger=110,thirst=115 都>100): {r3[0]}\n")

    # 模拟场景4: 双超130 (但未达终止条件)
    s4 = {"Hunger": 105, "Thirst": 100}
    i4 = [
        {"name": "大餐", "food": 40, "water": 30, "slot": "1-1", "x": 885, "y": 383, "drag_start": 1020},
        {"name": "小食", "food": 25, "water": 25, "slot": "1-2", "x": 900, "y": 383, "drag_start": 1020},
    ]
    r4 = decide_food(s4, i4)
    print(f"场景4 (hunger=105,thirst=100 双超130): {r4[0]}")
    print("  大餐: 145/130, 溢出=hunger15+water0=15")
    print("  小食: 130/125, 溢出=0 → 应该选小食\n")

    print("[测试完成] 逻辑符合预期即可集成")
