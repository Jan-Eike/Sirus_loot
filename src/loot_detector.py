import multiprocessing as mp
from dataclasses import dataclass
from multiprocessing import synchronize
from multiprocessing.queues import Queue

from cv2.typing import MatLike
from paddleocr import PaddleOCR
from rapidfuzz import fuzz, process

from data.boss import Boss
from google_sheets_data import append_run
from utils import check_loot_plausibility, normalize


@dataclass(frozen=True, slots=True)
class LootJob:
    boss: Boss
    elapsed_seconds: float
    image: MatLike


def create_ocr() -> PaddleOCR:
    return PaddleOCR(
        lang="en",
        device="cpu",
        enable_mkldnn=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def run_loot_worker(jobs: Queue, ready: synchronize.Event) -> None:
    ocr = create_ocr()
    ready.set()

    while True:
        job = jobs.get()

        if job is None:
            return

        try:
            process_loot(
                image=job.image,
                ocr=ocr,
                mm_ss=format_duration(job.elapsed_seconds),
                boss=job.boss,
            )
        except Exception as error:  # noqa: BLE001
            print(f"OCR failed for {job.boss.display_name}: {error}")


class LootWorker:
    def __init__(self) -> None:
        context = mp.get_context("spawn")

        self.jobs = context.Queue()
        ready = context.Event()

        self.process = context.Process(
            target=run_loot_worker,
            args=(self.jobs, ready),
            name="loot-worker",
            daemon=True,
        )

        self.process.start()

        if not ready.wait(timeout=120):
            raise RuntimeError("OCR worker failed to start")

    def submit(
        self,
        boss: Boss,
        elapsed_seconds: float,
        image: MatLike,
    ) -> None:
        self.jobs.put(
            LootJob(
                boss=boss,
                elapsed_seconds=elapsed_seconds,
                image=image,
            )
        )


def format_duration(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


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
    normalized_loot = {normalize(item): item for item in boss.loot_bases}
    normalized_text = normalize(ocr_text)

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


def process_loot(image: MatLike, ocr: PaddleOCR, mm_ss: str, boss: Boss) -> None:
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
