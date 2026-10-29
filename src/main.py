import re
import time
import os
from datetime import UTC, datetime

import cv2
import mss
import numpy as np
import pygetwindow as gw
from rapidfuzz import fuzz, process

import google_loot_sheet as g

GAME_TITLE = "Path of Exile"

CLIENT = (
    "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Path of Exile\\logs\\Client.txt"
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
]

from paddleocr import PaddleOCR


def capture_game():
    windows = gw.getWindowsWithTitle(GAME_TITLE)

    if not windows:
        raise RuntimeError(f'Game window "{GAME_TITLE}" not found')

    window = windows[0]

    region = {
        "left": window.left,
        "top": window.top,
        "width": window.width,
        "height": window.height,
    }

    with mss.MSS() as sct:
        screenshot = np.array(sct.grab(region))
        frame = cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)

    return frame


def run_ocr(image, ocr):
    results = ocr.predict(image)

    return results[0].json["res"]["rec_texts"]


def normalize(text):
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


def find_loot(ocr_text, threshold=80):
    normalized_loot = {normalize(item): item for item in LOOT_TABLE}
    normalized_text = normalize(ocr_text)

    # Split into words
    words = normalized_text.split()

    candidates = []

    # Generate every possible 1-5 word section
    for start in range(len(words)):
        for length in range(1, 6):
            end = start + length

            if end > len(words):
                break

            phrase = " ".join(words[start:end])

            candidates.append(phrase)

    matches = []

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
    found = {}

    for match in matches:
        item = match["item"]

        if item not in found:
            found[item] = match

    return list(found.values())


ocr = PaddleOCR(
    lang="en",
    device="cpu",
    enable_mkldnn=False,
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
)


from pathlib import Path

p = Path(CLIENT)
target = "I felt something"
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
        print(lines)
        if lines and target in lines[-1]:
            image = capture_game()
            results = run_ocr(image, ocr)
            results = find_loot(" ".join(results), threshold=85)

            for result in results:
                print(
                    result["item"],
                    " <- OCR:",
                    repr(result["ocr"]),
                    "score:",
                    round(result["score"], 1),
                )

            g.append_row(
                "Runs",
                [
                    "1",
                    datetime.now(UTC).isoformat(),
                    "Jan-Eike",
                    "Sirus",
                    ", ".join([result["item"] for result in results]),
                ],
            )
    time.sleep(1)
