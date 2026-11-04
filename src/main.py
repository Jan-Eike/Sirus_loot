import ctypes
import json
import os
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import cv2
import mss
import numpy as np
import pygame
import pygetwindow as gw
from cv2.typing import MatLike
from paddleocr import PaddleOCR
from rapidfuzz import fuzz, process

from boss_definitions import BOSSES

user32 = ctypes.windll.user32

from boss_data import Boss
from constants import AUTO_TRACK, LOOT_EXCLUDED
from google_sheets_data import append_run

GAME_TITLE = "Path of Exile"

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "config.json"
_config = (
    json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
)
CLIENT: str = _config.get(
    "client_path",
    "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Path of Exile\\logs\\Client.txt",
)


def play_sound(path: str) -> None:
    pygame.mixer.music.load(path)
    pygame.mixer.music.play()


def check_loot_plausibility(loot: list[str]) -> bool:
    """Check if the detected loot is a possible combination.
    This is needed because some non-boss drop items have the same base type as boss drop items.

    Args:
        loot (list[str]): detected list of looted items

    Returns:
        bool: Loot is possible or not
    """
    return sum(item in LOOT_EXCLUDED for item in loot) >= 2


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


def run_ocr(image: MatLike, ocr: PaddleOCR) -> list[str]:
    """Runs the ocr to find the text in the given image.

    Args:
        image (MatLike): The image to do ocr on
        ocr (PaddleOCR): the ocr object to execute the ocr

    Returns:
        list[str]: list of detected strings
    """
    results = ocr.predict(image)
    return results[0].json["res"]["rec_texts"]


def _normalize(text: str) -> str:
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


def find_loot(
    ocr_text: str, boss: Boss, threshold: int = 80
) -> list[dict[str, str | float]]:
    """Find the loot from the extracted ocr text by using fuzzy matching

    Args:
        ocr_text (str): found ocr text from the image
        boss (Boss): boss object containing loot data
        threshold (int, optional): confidence threshold for the fuzzy matching. Defaults to 80.

    Returns:
        list[dict[str, str | float]]: list of dictionaries with information about each item
    """
    normalized_loot = {_normalize(item): item for item in boss.loot_bases}
    normalized_text = _normalize(ocr_text)

    words = normalized_text.split()

    candidates: list[str] = []
    # Generate every possible 1-5 word section
    for start in range(len(words)):
        for length in range(1, 6):
            end = start + length

            if end > len(words):
                break

            phrase = " ".join(words[start:end])
            candidates.append(phrase)

    matches: list[dict[str, str | float]] = []

    for candidate in candidates:
        result = process.extractOne(
            candidate, normalized_loot.keys(), scorer=fuzz.ratio
        )

        if result is None:
            continue

        matched_text, score, _ = result

        if score >= threshold:
            matches.append(
                {
                    "item": normalized_loot[matched_text],
                    "score": score,
                    "ocr": candidate,
                }
            )

    # Sort strongest matches first
    matches.sort(key=lambda x: x["score"], reverse=True)

    # Remove duplicate items
    found: dict[str | float, dict[str, str | float]] = {}

    for match in matches:
        item = match["item"]

        if item not in found:
            found[item] = match

    return list(found.values())


def _process_loot(image: MatLike, ocr: PaddleOCR, mm_ss: str, boss: Boss) -> None:
    """Runs ocr and extracts loot from found strings. Appends it to the google sheets table afterwards.

    Args:
        image (MatLike): the image captured to do ocr on
        ocr (PaddleOCR): the ocr object
        mm_ss (str): time in mm:ss it took to complete one run
        boss (Boss): boss object
    """
    try:
        results = run_ocr(image, ocr)
        results = find_loot(" ".join(results), boss, threshold=85)

        for result in results:
            print(
                result["item"],
                " <- OCR:",
                repr(result["ocr"]),
                "score:",
                round(float(result["score"]), 1),
            )

        loot: list[str] = [str(result["item"]) for result in results]
        error = check_loot_plausibility(loot)
        append_run(
            player="Jan-Eike",
            boss=boss.display_name,
            loot=", ".join([boss.loot_map[loot_item] for loot_item in loot]),
            time_to_complete=mm_ss,
            error=error,
        )
    except Exception as e:  # noqa: BLE001
        print(f"OCR thread error: {e}")
        error = check_loot_plausibility(loot)
        append_run(
            player="Jan-Eike",
            boss=boss.display_name,
            loot=", ".join([boss.loot_map[loot_item] for loot_item in loot]),
            time_to_complete=mm_ss,
            error=error,
        )


def read_client() -> list[str]:
    with open(CLIENT, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 512))
        tail = f.read().decode(errors="ignore")
    return tail.splitlines()


def detect_boss(lines: list[str]) -> Boss | None:
    if not lines:
        return None
    last_line = lines[-1]
    area_level_match = re.findall(r"Generating level (\d*) area", last_line)
    if not area_level_match:
        return None
    area_level = int(area_level_match[0])
    for boss in BOSSES:
        if boss.location in last_line and boss.area_level == area_level:
            return boss
    return None


def detect_boss_kill(lines: list[str], boss: Boss) -> bool:
    return bool(lines and boss.kill_line and boss.kill_line in lines[-1])


def process_boss_kill(time_start, ocr, boss: Boss) -> tuple[None, Literal[False]]:
    time_end = datetime.now(UTC)
    print(time_end)
    detected = False
    # TODO: Change Time calculation
    time_total = time_end - time_start + timedelta(seconds=10)
    mm_ss = f"{int(time_total.total_seconds() // 60):02d}:{int(time_total.total_seconds() % 60):02d}"
    time_to_loot = boss.time_to_loot
    time.sleep(time_to_loot)
    image = capture_game()
    play_sound("assets/beep_on.ogg")
    # Run process_loot in a separate Thread to be able to start recording the time for the next run
    threading.Thread(
        target=_process_loot,
        args=(image, ocr, mm_ss, boss),
        daemon=True,
    ).start()
    return None, detected


def main():
    ocr = PaddleOCR(
        lang="en",
        device="cpu",
        enable_mkldnn=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    pygame.mixer.init()
    detected = False

    _hotkey_event = threading.Event()

    def _poll_hotkey():
        VK_F2 = 0x71
        while True:
            f2_pressed = user32.GetAsyncKeyState(VK_F2) & 0x8000
            if f2_pressed:
                _hotkey_event.set()
                while user32.GetAsyncKeyState(VK_F2) & 0x8000:
                    time.sleep(0.05)
            time.sleep(0.05)

    threading.Thread(target=_poll_hotkey, daemon=True).start()

    # determine standard start time in case the code has to be restarted.
    time_start = datetime.now(UTC)
    boss: None | Boss = None
    last_mtime = 0
    print("Ready.")
    play_sound("assets/beep_on.ogg")
    while True:
        if _hotkey_event.is_set() and boss:
            _hotkey_event.clear()
            boss, detected = process_boss_kill(time_start, ocr, boss)
        try:
            mtime = os.path.getmtime(CLIENT)
        except OSError:
            mtime = 0
        if mtime != last_mtime:
            last_mtime = mtime
            lines = read_client()
            boss = boss or detect_boss(lines)
            if boss and not detected:
                time_start = datetime.now(UTC)
                print(boss.display_name)
                detected = True
            if (
                AUTO_TRACK
                and boss
                and boss.auto_trackable
                and lines
                and detect_boss_kill(lines, boss)
            ):
                boss, detected = process_boss_kill(time_start, ocr, boss)
        time.sleep(0.1)


if __name__ == "__main__":
    main()
