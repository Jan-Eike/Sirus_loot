import ctypes
import threading

import pygame

import hotkey
from client_log_reader import ClientLogReader
from encounter_tracker import EncounterTracker
from hotkey import HotkeyPoller
from loot_detector import LootWorker
from utils import play_sound

user32 = ctypes.windll.user32

from constants import AUTO_TRACK, CLIENT


def main() -> None:
    pygame.mixer.init()

    stop_event = threading.Event()

    hotkeys = HotkeyPoller()

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
            for action in hotkeys.get_actions():
                match action:
                    case hotkey.HotkeyAction.CANCEL_BOSS:
                        tracker.cancel()
                    case hotkey.HotkeyAction.FINISH_BOSS:
                        tracker.finish_manually()

            for line in client_log.read_new_lines():
                tracker.handle_log_line(line)

            stop_event.wait(0.1)

    except KeyboardInterrupt:
        print("Stopping...")
        stop_event.set()

    finally:
        stop_event.set()
        hotkeys.close()


if __name__ == "__main__":
    main()
