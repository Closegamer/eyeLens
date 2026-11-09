"""Turns raw tracker snapshots into a smooth screen-space gaze point."""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QCursor

from ..config import ScreenInfo, Settings
from .filters import PointFilter
from .model import GazeModel
from .tracker import EyeTracker


def smoothing_to_cutoff(smoothing: float) -> tuple[float, float]:
    """Map the UI slider (0 = responsive, 1 = very smooth) to filter params.

    The defaults are deliberately on the calm side: a magnifying lens feels
    wrong when it snaps to every eye-tracker jitter, and gaze estimation is
    noisy by nature.
    """
    s = max(0.0, min(1.0, float(smoothing)))
    min_cutoff = math.exp(math.log(2.4) * (1.0 - s) + math.log(0.22) * s)
    beta = 0.030 * (1.0 - s) + 0.004 * s
    return min_cutoff, beta


class GazeEngine(QObject):
    def __init__(
        self,
        screen: ScreenInfo,
        tracker: EyeTracker | None = None,
        demo: bool = False,
        settings: Settings | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.screen = screen
        self.tracker = tracker
        self.demo = bool(demo)
        self.settings = settings or Settings()
        self.model: GazeModel | None = None
        self._filter = PointFilter()
        cutoff, beta = smoothing_to_cutoff(self.settings.smoothing)
        self._filter.configure(cutoff, beta)
        self._current: tuple[float, float] | None = None
        self._last_good = 0.0
        self._last_seq = -1
        self._face_found = False
        self._openness = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.poll)
        self._timer.start()

    # ----------------------------------------------------------------- config
    def set_model(self, model: GazeModel | None) -> None:
        self.model = model
        self._filter.reset()
        self._current = None
        self._last_good = 0.0
        self._last_seq = -1

    def apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        cutoff, beta = smoothing_to_cutoff(settings.smoothing)
        self._filter.configure(cutoff, beta)

    # ------------------------------------------------------------------- poll
    def poll(self) -> None:
        if self.demo:
            pos = QCursor.pos()
            self._current = (float(pos.x()), float(pos.y()))
            self._last_good = time.monotonic()
            self._face_found = True
            self._openness = 1.0
            return

        if self.tracker is None or self.model is None:
            return
        snap = self.tracker.snapshot()
        self._face_found = snap.face_found
        self._openness = snap.openness
        if snap.seq == self._last_seq:
            return
        self._last_seq = snap.seq

        if not snap.face_found or snap.features is None:
            return
        if not self.model.is_eye_open(snap.openness):
            return

        try:
            prediction = self.model.predict(snap.features)
        except (ValueError, FloatingPointError):
            return

        now = time.monotonic()
        width = self.screen.width
        height = self.screen.height
        margin_x = width * 0.18
        margin_y = height * 0.18
        if not (
            self.screen.left - margin_x
            <= prediction.x
            <= self.screen.left + width + margin_x
            and self.screen.top - margin_y
            <= prediction.y
            <= self.screen.top + height + margin_y
        ):
            return

        x = min(max(prediction.x, self.screen.left), self.screen.left + width)
        y = min(max(prediction.y, self.screen.top), self.screen.top + height)

        if self._current is None or now - self._last_good > 1.0:
            self._filter.reset((x, y))
            self._current = (x, y)
        else:
            self._current = self._filter.filter((x, y), now)
        self._last_good = now

    # ------------------------------------------------------------------ state
    def current_center(self) -> tuple[float, float] | None:
        return self._current

    def age(self) -> float:
        if self._last_good <= 0.0:
            return float("inf")
        return time.monotonic() - self._last_good

    @property
    def face_found(self) -> bool:
        return self._face_found

    @property
    def eyes_open(self) -> bool:
        return self._openness >= (self.model.openness_threshold if self.model else 0.08)

    def state_text(self) -> str:
        if self.demo:
            return "Mouse demo"
        if self.model is None:
            return "Not calibrated"
        if self.screen and self.tracker is None:
            return "Camera off"
        if self.tracker is not None and self.tracker.error_text:
            return "Camera error"
        if not self._face_found:
            return "Face not found"
        if not self.eyes_open:
            return "Eyes closed"
        if self.age() > 0.6:
            return "Reacquiring…"
        return "Tracking"

    def tracking_live(self) -> bool:
        if self.demo:
            return True
        return (
            self.model is not None
            and self._face_found
            and self.age() < 0.55
        )
