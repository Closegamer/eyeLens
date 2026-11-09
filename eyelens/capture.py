"""Low-latency capture of the region under the lens."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from .config import ScreenInfo


@dataclass(frozen=True)
class CaptureFrame:
    image: QImage
    #: Position of the requested lens centre inside ``image`` (image pixels).
    center_x: float
    center_y: float
    #: Physical image pixels per Qt logical pixel.
    scale_x: float
    scale_y: float
    timestamp: float


@dataclass(frozen=True)
class CaptureRequest:
    center_x: float
    center_y: float
    diameter: float
    zoom: float


class ScreenCapture(QThread):
    """Continuously grabs a padded square around the lens centre.

    Capturing only the lens neighbourhood keeps CPU use low even at high zoom.
    The overlay window is excluded from capture via
    ``SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`` so the lens never
    films itself.
    """

    error = Signal(str)

    MARGIN = 1.35
    TARGET_FPS = 30.0

    def __init__(self, screen: ScreenInfo, parent=None) -> None:
        super().__init__(parent)
        self.screen = screen
        self._lock = threading.Lock()
        self._request = CaptureRequest(
            screen.width / 2.0, screen.height / 2.0, 280.0, 2.0
        )
        self._active = True
        self._stop_event = threading.Event()
        self._frame: CaptureFrame | None = None
        self._reported_error = False
        self._monitor: dict | None = None

    # -------------------------------------------------------------- interface
    def set_request(
        self, center_x: float, center_y: float, diameter: float, zoom: float
    ) -> None:
        with self._lock:
            self._request = CaptureRequest(
                float(center_x), float(center_y), float(diameter), float(zoom)
            )

    def set_active(self, active: bool) -> None:
        with self._lock:
            self._active = bool(active)

    def latest(self) -> CaptureFrame | None:
        with self._lock:
            return self._frame

    def monitor(self) -> dict | None:
        with self._lock:
            return dict(self._monitor) if self._monitor else None

    def stop_and_wait(self, timeout_ms: int = 3000) -> None:
        self._stop_event.set()
        if self.isRunning():
            self.wait(timeout_ms)

    # -------------------------------------------------------------------- run
    def run(self) -> None:
        try:
            import mss
        except Exception as exc:  # pragma: no cover - dependency error
            self.error.emit(f"Screen capture is unavailable: {exc}")
            return

        try:
            with mss.MSS() as sct:
                monitors = sct.monitors[1:]
                monitor = next(
                    (m for m in monitors if m.get("is_primary")),
                    monitors[0] if monitors else None,
                )
                if monitor is None:
                    self.error.emit("No screen available for capture.")
                    return
                with self._lock:
                    self._monitor = dict(monitor)

                mon_left, mon_top = int(monitor["left"]), int(monitor["top"])
                mon_w, mon_h = int(monitor["width"]), int(monitor["height"])
                if mon_w <= 0 or mon_h <= 0 or self.screen.width <= 0:
                    self.error.emit("Screen capture has an invalid geometry.")
                    return
                # Derive the true physical/logical scale instead of trusting a
                # rounded QScreen DPI value.
                scale_x = mon_w / float(self.screen.width)
                scale_y = mon_h / float(self.screen.height)

                next_frame = time.perf_counter()
                while not self._stop_event.is_set():
                    with self._lock:
                        active = self._active
                        request = self._request
                    if not active:
                        time.sleep(0.05)
                        next_frame = time.perf_counter()
                        continue

                    try:
                        frame = self._grab(
                            sct,
                            request,
                            (mon_left, mon_top, mon_w, mon_h),
                            scale_x,
                            scale_y,
                        )
                        with self._lock:
                            self._frame = frame
                        self._reported_error = False
                    except Exception as exc:  # pragma: no cover - driver dependent
                        if not self._reported_error:
                            self._reported_error = True
                            self.error.emit(f"Screen capture failed: {exc}")
                        time.sleep(0.25)
                        continue

                    next_frame += 1.0 / self.TARGET_FPS
                    delay = next_frame - time.perf_counter()
                    if delay > 0:
                        time.sleep(min(delay, 0.1))
                    else:
                        next_frame = time.perf_counter()
        except Exception as exc:  # pragma: no cover
            self.error.emit(f"Screen capture stopped: {exc}")

    def _grab(
        self,
        sct,
        request: CaptureRequest,
        monitor: tuple[int, int, int, int],
        scale_x: float,
        scale_y: float,
    ) -> CaptureFrame:
        mon_left, mon_top, mon_w, mon_h = monitor
        center_px = request.center_x * scale_x
        center_py = request.center_y * scale_y
        source_w = max(1.0, request.diameter * request.zoom * scale_x)
        source_h = max(1.0, request.diameter * request.zoom * scale_y)

        capture_w = int(round(min(float(mon_w), max(64.0, source_w * self.MARGIN))))
        capture_h = int(round(min(float(mon_h), max(64.0, source_h * self.MARGIN))))
        capture_w = max(1, min(capture_w, mon_w))
        capture_h = max(1, min(capture_h, mon_h))

        left = int(round(center_px - capture_w / 2.0))
        top = int(round(center_py - capture_h / 2.0))
        left = max(0, min(left, mon_w - capture_w))
        top = max(0, min(top, mon_h - capture_h))

        raw = sct.grab(
            {
                "left": mon_left + left,
                "top": mon_top + top,
                "width": capture_w,
                "height": capture_h,
            }
        )
        image = QImage(
            raw.bgra,
            raw.width,
            raw.height,
            raw.width * 4,
            QImage.Format.Format_ARGB32,
        ).copy()
        return CaptureFrame(
            image=image,
            center_x=center_px - left,
            center_y=center_py - top,
            scale_x=scale_x,
            scale_y=scale_y,
            timestamp=time.monotonic(),
        )
