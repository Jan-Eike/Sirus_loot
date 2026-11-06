import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from cv2.typing import MatLike

from boss_detector import detect_boss, detect_boss_kill
from data.boss import Boss
from utils import capture_game, play_sound

RUN_TIMER_OFFSET_SECONDS = 10


@dataclass(frozen=True, slots=True)
class Encounter:
    boss: Boss
    started_at: float


class EncounterTracker:
    def __init__(
        self,
        *,
        auto_track: bool,
        on_kill: Callable[[Boss, float, MatLike], None],
    ) -> None:
        self.auto_track = auto_track
        self.on_kill = on_kill
        self.active: Encounter | None = None

    def handle_log_line(self, line: str) -> None:
        if self.active is None:
            self._try_start_encounter(line)
            return

        boss = self.active.boss

        if self.auto_track and boss.auto_trackable and detect_boss_kill(line, boss):
            self._finish_encounter()

    def finish_manually(self) -> None:
        if self.active is not None:
            self._finish_encounter()

    def _try_start_encounter(self, line: str) -> None:
        boss = detect_boss(line)

        if boss is None:
            return

        self.active = Encounter(
            boss=boss,
            started_at=time.monotonic(),
        )

        print(boss.display_name)

    def _finish_encounter(self) -> None:
        encounter = self.active

        if encounter is None:
            return

        # Clear immediately so the next boss can be detected while we wait.
        self.active = None

        elapsed_seconds = (
            time.monotonic() - encounter.started_at + RUN_TIMER_OFFSET_SECONDS
        )

        if encounter.boss.time_to_loot <= 0:
            self._capture_and_submit(
                encounter.boss,
                elapsed_seconds,
            )
            return

        timer = threading.Timer(
            interval=encounter.boss.time_to_loot,
            function=self._capture_and_submit,
            args=(
                encounter.boss,
                elapsed_seconds,
            ),
        )
        timer.daemon = True
        timer.start()

    def _capture_and_submit(
        self,
        boss: Boss,
        elapsed_seconds: float,
    ) -> None:
        try:
            image = capture_game()
            play_sound("assets/beep_on.ogg")
        except Exception as error:  # noqa: BLE001
            print(f"Screenshot failed for {boss.display_name}: {error}")
            return

        self.on_kill(
            boss,
            elapsed_seconds,
            image,
        )

    def cancel(self) -> None:
        if self.active is None:
            print("No active boss to cancel.")
            return

        self.active = None
        print("Cancelled boss")
