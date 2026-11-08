import re

import cv2
import mss
import numpy as np
import pygame
import pygetwindow as gw
from cv2.typing import MatLike

from data.boss import Boss

GAME_TITLE = "Path of Exile"


def play_sound(path: str) -> None:
    """Play a sound loacated at the given path.

    Args:
        path (str): path to ogg file
    """
    assert path.split(".")[-1] == "ogg"
    pygame.mixer.music.load(path)
    pygame.mixer.music.play()


def check_loot_plausibility(loot: list[str], boss: Boss) -> bool:
    """Check if the detected loot is a possible combination.
    This is needed because some non-boss drop items have the same base type as boss drop items.

    Args:
        loot (list[str]): detected list of looted items

    Returns:
        bool: Loot is possible or not
    """
    # Always Error for duplicate base types
    if boss.display_name == "Eater" and "crimson jewel" in loot:
        return True
    if boss.display_name == "Exarch" and "cobalt jewel" in loot:
        return True
    return sum(item in boss.loot_excluded for item in loot) >= 2


def capture_game() -> MatLike:
    """Takes a screenshot of the game window.

    Raises:
        RuntimeError: Games was not found

    Returns:
        MatLike: The image
    """
    windows: list[gw.Win32Window] = gw.getWindowsWithTitle(GAME_TITLE)

    if not windows:
        raise RuntimeError(f'Game window "{GAME_TITLE}" not found')

    window = windows[0]

    region: dict[str, float] = {
        "left": window.left,
        "top": window.top,
        "width": window.width,
        "height": window.height,
    }

    with mss.MSS() as sct:
        screenshot = np.array(sct.grab(region))
        image = cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)

    return image


def normalize(text: str) -> str:
    """Some text normalization for better comparison.

    Args:
        text (str): input text

    Returns:
        str: normalized text
    """
    text = text.lower()

    # Apostrophe becomes nothing:
    # "awakener's" -> "awakeners"
    text = text.replace("'", "")
    text = text.replace("’", "")

    # Remove punctuation
    text = re.sub(r"[^a-z0-9\s]", " ", text)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)

    return text.strip()
