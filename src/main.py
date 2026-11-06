import ctypes
import threading

import pygame
from paddleocr import PaddleOCR

from client_log_reader import ClientLogReader
from encounter_tracker import EncounterTracker
from loot_detector import LootWorker
from utils import play_sound

user32 = ctypes.windll.user32

from constants import AUTO_TRACK, CLIENT, VK_F2


def main() -> None:
    ocr = PaddleOCR(
        lang="en",
        device="cpu",
        enable_mkldnn=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    pygame.mixer.init()

    stop_event = threading.Event()
    hotkey_event = threading.Event()

    def poll_hotkey() -> None:
        while not stop_event.is_set():
            f2_pressed = user32.GetAsyncKeyState(VK_F2) & 0x8000

            if f2_pressed:
                hotkey_event.set()

                while (
                    user32.GetAsyncKeyState(VK_F2) & 0x8000 and not stop_event.is_set()
                ):
                    stop_event.wait(0.05)

            stop_event.wait(0.05)

    threading.Thread(
        target=poll_hotkey,
        name="hotkey-poller",
        daemon=True,
    ).start()

    client_log = ClientLogReader(
        CLIENT,
    )

    loot_worker = LootWorker(ocr)

    tracker = EncounterTracker(
        auto_track=AUTO_TRACK,
        on_kill=loot_worker.submit,
    )

    print("Ready.")
    play_sound("assets/beep_on.ogg")

    try:
        while not stop_event.is_set():
            if hotkey_event.is_set():
                # Always consume F2, even if no boss is active.
                hotkey_event.clear()
                tracker.finish_manually()

            for line in client_log.read_new_lines():
                tracker.handle_log_line(line)

            stop_event.wait(0.1)

    except KeyboardInterrupt:
        print("Stopping...")
        stop_event.set()


if __name__ == "__main__":
    main()
