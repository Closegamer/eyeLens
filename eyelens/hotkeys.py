"""Global hotkeys (work while eyeLens is in the tray)."""

from __future__ import annotations

import contextlib
import ctypes
import platform
import threading
from typing import ClassVar

from PySide6.QtCore import QObject, Signal


class HotkeyManager(QObject):
    toggle_lens = Signal()
    toggle_freeze = Signal()
    calibrate = Signal()
    correct_lens = Signal()
    toggle_big = Signal()
    zoom_in = Signal()
    zoom_out = Signal()
    size_up = Signal()
    size_down = Signal()
    #: Horizontal and vertical wheel deltas for manual lens fine tuning.
    trim_lens = Signal(int, int)
    reset_trim = Signal()
    error = Signal(str)

    HOTKEYS: ClassVar[dict[str, str]] = {
        "<ctrl>+<alt>+l": "toggle_lens",
        "<ctrl>+<alt>+f": "toggle_freeze",
        "<ctrl>+<alt>+c": "calibrate",
        "<ctrl>+<alt>+d": "correct_lens",
        "<ctrl>+<alt>+b": "toggle_big",
        "<ctrl>+<alt>+=": "zoom_in",
        "<ctrl>+<alt>+-": "zoom_out",
        "<ctrl>+<alt>+]": "size_up",
        "<ctrl>+<alt>+[": "size_down",
        "<ctrl>+<alt>+0": "reset_trim",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._listener = None
        self._mouse_listener = None
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

        try:
            from pynput import mouse

            mouse_listener = mouse.Listener(on_scroll=self._on_scroll)
            mouse_listener.daemon = True
            mouse_listener.start()
            with self._lock:
                self._mouse_listener = mouse_listener
        except Exception as exc:  # pragma: no cover - platform dependent
            self.error.emit(f"Global mouse wheel is unavailable: {exc}")

    @staticmethod
    def _ctrl_alt_down() -> bool:
        if platform.system() != "Windows":
            return False
        try:
            user32 = ctypes.windll.user32
            vk_control = 0x11
            vk_menu = 0x12  # Alt
            return bool(user32.GetAsyncKeyState(vk_control) & 0x8000) and bool(
                user32.GetAsyncKeyState(vk_menu) & 0x8000
            )
        except Exception:  # pragma: no cover - Windows API dependent
            return False

    def _on_scroll(self, _x, _y, dx, dy) -> None:
        """Ctrl+Alt+wheel = nudge the lens; plain wheel is left alone."""
        if not self._ctrl_alt_down():
            return
        dx = int(dx)
        dy = int(dy)
        if dx or dy:
            with contextlib.suppress(Exception):
                self.trim_lens.emit(dx, dy)

    def _dispatch(self, name: str) -> None:
        with contextlib.suppress(Exception):
            getattr(self, name).emit()

    def stop(self) -> None:
        with self._lock:
            listener = self._listener
            mouse_listener = self._mouse_listener
            self._listener = None
            self._mouse_listener = None
        for item in (listener, mouse_listener):
            if item is not None:
                with contextlib.suppress(Exception):
                    item.stop()
