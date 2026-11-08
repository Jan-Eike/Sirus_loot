import ctypes
import queue
import threading
from enum import Enum, auto

from constants import VK_F2, VK_F3

user32 = ctypes.windll.user32


class HotkeyAction(Enum):
    FINISH_BOSS = auto()
    CANCEL_BOSS = auto()


class HotkeyPoller:
    def __init__(self, poll_interval: float = 0.05) -> None:
        self._poll_interval = poll_interval
        self._actions: queue.SimpleQueue[HotkeyAction] = queue.SimpleQueue()
        self._stop_event = threading.Event()

        self._thread = threading.Thread(
            target=self._run,
            name="hotkey-poller",
            daemon=True,
        )
        self._thread.start()

    def get_actions(self) -> list[HotkeyAction]:
        """Return all queued actions.

        Returns:
            list[HotkeyAction]: list of actions
        """
        actions: list[HotkeyAction] = []

        while True:
            try:
                actions.append(self._actions.get_nowait())
            except queue.Empty:
                return actions

    def close(self) -> None:
        """close the thread."""
        self._stop_event.set()
        self._thread.join(timeout=1)

    def _run(self) -> None:
        previous_f2 = False
        previous_f3 = False

        while not self._stop_event.is_set():
            f2_pressed = self._is_pressed(VK_F2)
            f3_pressed = self._is_pressed(VK_F3)

            if f2_pressed and not previous_f2:
                self._actions.put(HotkeyAction.FINISH_BOSS)

            if f3_pressed and not previous_f3:
                self._actions.put(HotkeyAction.CANCEL_BOSS)

            previous_f2 = f2_pressed
            previous_f3 = f3_pressed

            self._stop_event.wait(self._poll_interval)

    @staticmethod
    def _is_pressed(key: int) -> bool:
        return bool(user32.GetAsyncKeyState(key) & 0x8000)
