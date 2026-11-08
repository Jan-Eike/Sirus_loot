import re

from data.boss import Boss
from data.boss_definitions import BOSSES

AREA_LEVEL_PATTERN = re.compile(r"Generating level (\d+) area")


def detect_boss(line: str) -> Boss | None:
    """Detect the boss by checking if the given line contains
    the name of the area and the area level.

    Args:
        line (str): line to read

    Returns:
        Boss | None: found boss or None if no Boss was found
    """
    match = AREA_LEVEL_PATTERN.search(line)

    if match is None:
        return None

    area_level = int(match.group(1))

    for boss in BOSSES:
        if boss.location in line and boss.area_level == area_level:
            return boss

    return None


def detect_boss_kill(line: str, boss: Boss) -> bool:
    """Detects if the current boss was killed by inspecting the given line.

    Args:
        line (str): line to read
        boss (Boss): current Boss

    Returns:
        bool: boss was killed or not
    """
    for kill_line in boss.kill_lines:
        if kill_line and kill_line in line:
            return True
    return False
