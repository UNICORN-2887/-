"""GameAutomator — 一键启动导航."""
from typing import Optional, Tuple, List, Callable
import time
from game_automator.mapping import Pathfinder
from game_automator.navigation import Navigator


class GameAutomator:
    """游戏自动化引擎.

    封装 Pathfinder + Navigator, 用户只需提供:
    - 地图路径和可达图
    - 位置获取回调
    - 按键执行回调

    Usage:
        auto = GameAutomator("map.jpg", "reachable.png")
        auto.set_route(start, goal)
        while not auto.finished:
            pos = get_position()  # 你的定位
            keys = auto.step(pos)  # 返回按键名列表
            if keys: send_keys(keys)
    """

    def __init__(self,
                 map_path: str,
                 reachable_path: str,
                 waypoint_reach: int = 25,
                 goal_reach: int = 100,
                 lookahead: int = 90,
                 shrink: int = 80):
        self._pf = Pathfinder(reachable_path, shrink=shrink)
        self._nav = Navigator(self._pf,
                              waypoint_reach=waypoint_reach,
                              goal_reach=goal_reach,
                              lookahead=lookahead)

    # ── API ──────────────────────────────────
    def set_route(self, start: Tuple[int, int],
                  goal: Tuple[int, int]) -> List[Tuple[int, int]]:
        """规划路径, 返回路径点列表."""
        return self._nav.set_route(start, goal)

    def step(self, current_pos: Tuple[int, int]
             ) -> Optional[str]:
        """传入当前位置, 返回动作名 (如 'MOVE_NE').

        返回 None 表示已到达终点.
        """
        action = self._nav.step(current_pos)
        return action.name if action else None

    def cancel(self) -> None:
        """取消导航."""
        self._nav.cancel()

    # ── 属性 ────────────────────────────────
    @property
    def path(self) -> List[Tuple[int, int]]:
        return self._nav.path

    @property
    def current_waypoint(self) -> Optional[Tuple[int, int]]:
        return self._nav.current_waypoint

    @property
    def arrived(self) -> bool:
        return self._nav.arrived

    @property
    def grid_size(self):
        return self._pf.grid_size
