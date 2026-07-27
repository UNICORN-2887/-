"""标准动作定义 + 抽象驱动基类.

用户继承 AbstractDriver 实现底层操控即可接入导航系统.
"""

from enum import IntEnum
from abc import ABC, abstractmethod
from typing import Optional, Tuple


# ── 标准动作枚举 ──────────────────────────────
class Actions(IntEnum):
    # 8 方向移动
    MOVE_N = 0
    MOVE_S = 1
    MOVE_W = 2
    MOVE_E = 3
    MOVE_NE = 4
    MOVE_NW = 5
    MOVE_SE = 6
    MOVE_SW = 7
    # 战斗
    ATTACK = 20
    DASH = 21
    # 技能
    SKILL_1 = 30
    SKILL_2 = 31
    SKILL_3 = 32
    SKILL_4 = 33
    # 交互
    INTERACT = 40
    CANCEL = 41

    @classmethod
    def direction_name(cls, v):
        """从方向向量(ix, iy)推算动作名."""
        names = {
            (0, -1): cls.MOVE_N, (0, 1): cls.MOVE_S,
            (-1, 0): cls.MOVE_W, (1, 0): cls.MOVE_E,
            (1, -1): cls.MOVE_NE, (-1, -1): cls.MOVE_NW,
            (1, 1): cls.MOVE_SE, (-1, 1): cls.MOVE_SW,
        }
        return names.get(v, None)


# ── 抽象驱动 ──────────────────────────────────
class AbstractDriver(ABC):
    """用户在子类中实现具体键鼠/ADB/模拟器操作."""

    @abstractmethod
    def execute(self, action: Actions, duration_ms: int = 100) -> None:
        """执行单个动作, 持续 duration_ms 毫秒."""
        ...

    @abstractmethod
    def release_all(self) -> None:
        """释放所有正在按下的键."""
        ...

    @abstractmethod
    def click(self, x: int, y: int) -> None:
        """在画面坐标(x,y)执行点击."""
        ...
