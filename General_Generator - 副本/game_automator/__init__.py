"""game-automator: 通用游戏自动化框架."""

from game_automator.driver import Actions, AbstractDriver
from game_automator.capture import OBSVideoCapture, MSSScreenCapture, ADBVideoCapture
from game_automator.stitching import MapStitcher
from game_automator.mapping import ReachabilityEditor, Pathfinder, PositionTracker
from game_automator.navigation import Navigator, NavigationServer, compute_direction
from game_automator.automator import GameAutomator
