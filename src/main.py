import ctypes
import threading

import pygame

from client_log_reader import ClientLogReader
from encounter_tracker import EncounterTracker
from loot_detector import LootWorker
from utils import play_sound

user32 = ctypes.windll.user32

from constants import AUTO_TRACK, CLIENT, VK_F2, VK_F3


def main() -> None:
    pygame.mixer.init()

    stop_event = threading.Event()
    finish_event = threading.Event()
    cancel_event = threading.Event()

    def poll_hotkey() -> None:
        previous_f2 = False
        previous_f3 = False

        while not stop_event.is_set():
            f2_pressed = user32.GetAsyncKeyState(VK_F2) & 0x8000
            f3_pressed = user32.GetAsyncKeyState(VK_F3) & 0x8000

            if f2_pressed and not previous_f3:
                finish_event.set()

            if f3_pressed and not previous_f2:
                cancel_event.set()

            previous_f2 = f2_pressed
            previous_f3 = f3_pressed

            stop_event.wait(0.05)

    threading.Thread(
        target=poll_hotkey,
        name="hotkey-poller",
        daemon=True,
    ).start()

    client_log = ClientLogReader(
        CLIENT,
    )

    loot_worker = LootWorker()

    tracker = EncounterTracker(
        auto_track=AUTO_TRACK,
        on_kill=loot_worker.submit,
    )

    print("Ready.")
    play_sound("assets/beep_on.ogg")

    try:
        while not stop_event.is_set():
            if finish_event.is_set():
                finish_event.clear()
                tracker.finish_manually()
            if cancel_event.is_set():
                cancel_event.clear()
                tracker.cancel()
            for line in client_log.read_new_lines():
                tracker.handle_log_line(line)

            stop_event.wait(0.1)

    except KeyboardInterrupt:
        print("Stopping...")
        stop_event.set()


if __name__ == "__main__":
    main()
