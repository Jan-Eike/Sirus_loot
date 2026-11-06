import ctypes
import threading
import time
from threading import Event

from constants import VK_F2

user32 = ctypes.windll.user32


def start_hotkey_event() -> Event:
    hotkey_event = threading.Event()
    threading.Thread(target=poll_hotkey, daemon=True).start()
    return hotkey_event


def poll_hotkey(hotkey_event: Event):
    while True:
        f2_pressed = user32.GetAsyncKeyState(VK_F2) & 0x8000
        if f2_pressed:
            hotkey_event.set()
            while user32.GetAsyncKeyState(VK_F2) & 0x8000:
                time.sleep(0.05)
        time.sleep(0.05)
