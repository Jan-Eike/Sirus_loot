import re

from data.boss import Boss
from data.boss_definitions import BOSSES

AREA_LEVEL_PATTERN = re.compile(r"Generating level (\d+) area")


def detect_boss(line: str) -> Boss | None:
    match = AREA_LEVEL_PATTERN.search(line)

    if match is None:
        return None

    area_level = int(match.group(1))

    for boss in BOSSES:
        if boss.location in line and boss.area_level == area_level:
            return boss

    return None


def detect_boss_kill(line: str, boss: Boss) -> bool:
    for kill_line in boss.kill_lines:
        if kill_line and kill_line in line:
            return True
    return False
