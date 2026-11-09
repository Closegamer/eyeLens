"""Global hotkeys (work while eyeLens is in the tray)."""

from __future__ import annotations

import contextlib
import threading
from typing import ClassVar

from PySide6.QtCore import QObject, Signal


class HotkeyManager(QObject):
    toggle_lens = Signal()
    toggle_freeze = Signal()
    calibrate = Signal()
    zoom_in = Signal()
    zoom_out = Signal()
    size_up = Signal()
    size_down = Signal()
    error = Signal(str)

    HOTKEYS: ClassVar[dict[str, str]] = {
        "<ctrl>+<alt>+l": "toggle_lens",
        "<ctrl>+<alt>+f": "toggle_freeze",
        "<ctrl>+<alt>+c": "calibrate",
        "<ctrl>+<alt>+=": "zoom_in",
        "<ctrl>+<alt>+-": "zoom_out",
        "<ctrl>+<alt>+]": "size_up",
        "<ctrl>+<alt>+[": "size_down",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._listener = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._listener is not None:
            return
        try:
            from pynput import keyboard

            mapping = {
                combo: (lambda name=name: self._dispatch(name))
                for combo, name in self.HOTKEYS.items()
            }
            listener = keyboard.GlobalHotKeys(mapping)
            listener.daemon = True
            listener.start()
            with self._lock:
                self._listener = listener
        except Exception as exc:  # pragma: no cover - platform dependent
            self.error.emit(f"Global hotkeys are unavailable: {exc}")

    def _dispatch(self, name: str) -> None:
        with contextlib.suppress(Exception):
            getattr(self, name).emit()

    def stop(self) -> None:
        with self._lock:
            listener = self._listener
            self._listener = None
        if listener is not None:
            with contextlib.suppress(Exception):
                listener.stop()
