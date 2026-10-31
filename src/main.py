import json
import os
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import mss
import numpy as np
import pygetwindow as gw
from cv2.typing import MatLike
from paddleocr import PaddleOCR
from rapidfuzz import fuzz, process

import google_loot_sheet as g  # ty: ignore[unresolved-import]

GAME_TITLE = "Path of Exile"

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "config.json"
_config = (
    json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
)
CLIENT: str = _config.get(
    "client_path",
    "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Path of Exile\\logs\\Client.txt",
)

LOOT_TABLE = [
    "oubliette reliquary key",
    "goliath greaves",
    "awakener's orb",
    "crimson jewel",
    "orb of dominance",
    "a fate worse than death",
    "bismuth flask",
    "prismatic ring",
    "legion sword",
    "annihilation support",
]

LOOT_MAPPING: dict[str, str] = {
    "oubliette reliquary key": "Oubliette Reliquary Key",
    "goliath greaves": "The Tempest Rising",
    "awakener's orb": "Awakener's Orb",
    "crimson jewel": "Thread of Hope",
    "orb of dominance": "Orb of Dominance",
    "a fate worse than death": "A Fate worse than Death",
    "bismuth flask": "Oriath's End",
    "prismatic ring": "Zana's Ingenuity",
    "legion sword": "The Saviour",
    "annihilation support": "Annihilation Support",
}

LOOT_EXCLUDED: list[str] = [
    "goliath greaves",
    "crimson jewel",
    "bismuth flask",
    "prismatic ring",
    "legion sword",
]


def check_loot_plausibility(loot: list[str]) -> bool:
    return sum(item in LOOT_EXCLUDED for item in loot) >= 2


def capture_game() -> MatLike:
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
    """Runs ocr and returns found text."""
    results = ocr.predict(image)
    return results[0].json["res"]["rec_texts"]


def _normalize(text: str) -> str:
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


def find_loot(ocr_text: str, threshold: int = 80) -> list[dict[str, str | float]]:
    normalized_loot = {_normalize(item): item for item in LOOT_TABLE}
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


def _process_loot(image: MatLike, ocr: PaddleOCR, mm_ss: str) -> None:
    try:
        results = run_ocr(image, ocr)
        results = find_loot(" ".join(results), threshold=85)

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
        g.append_run(
            player="Jan-Eike",
            boss="Sirus",
            loot=", ".join([LOOT_MAPPING[loot_item] for loot_item in loot]),
            time_to_complete=mm_ss,
            error=error,
        )
    except Exception as e:  # noqa: BLE001
        print(f"OCR thread error: {e}")


def main():
    ocr = PaddleOCR(
        lang="en",
        device="cpu",
        enable_mkldnn=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    target = "I felt something"
    target_time = "Did you really think this would work"
    time_start = datetime.now(UTC)
    last_mtime = 0
    while True:
        try:
            mtime = os.path.getmtime(CLIENT)
        except OSError:
            mtime = 0
        if mtime != last_mtime:
            last_mtime = mtime
            with open(CLIENT, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 512))
                tail = f.read().decode(errors="ignore")
            lines = tail.splitlines()
            if lines and target_time in lines[-1]:
                time_start = datetime.now(UTC)
            if lines and target in lines[-1]:
                time_end = datetime.now(UTC)
                time_total = time_end - time_start + timedelta(seconds=10)
                mm_ss = f"{int(time_total.total_seconds() // 60):02d}:{int(time_total.total_seconds() % 60):02d}"
                image = capture_game()
                threading.Thread(
                    target=_process_loot,
                    args=(image, ocr, mm_ss),
                    daemon=True,
                ).start()
        time.sleep(1)


if __name__ == "__main__":
    main()
