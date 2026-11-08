from dataclasses import dataclass


@dataclass
class Boss:
    name: str
    display_name: str
    location: str
    area_level: int
    kill_lines: list[str]
    time_to_loot: float
    loot_bases: list[str]
    loot_excluded: list[str]
    loot_map: dict[str, str]
    auto_trackable: bool = True
    is_uber: bool = False
