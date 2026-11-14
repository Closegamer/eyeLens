"""Global hotkeys (work while eyeLens is in the tray)."""

from __future__ import annotations

import contextlib
import ctypes
import platform
import threading
from typing import ClassVar

from PySide6.QtCore import QObject, Signal

from .i18n import tr


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

    #: Virtual-key codes are layout independent: character matching fails while
    #: Ctrl+Alt are held (the translated character becomes None) and on a
    #: non-Latin layout.
    HOTKEYS: ClassVar[dict[int, str]] = {
        0x4C: "toggle_lens",  # L
        0x46: "toggle_freeze",  # F
        0x43: "calibrate",  # C
        0x44: "correct_lens",  # D
        0x42: "toggle_big",  # B
        0xBB: "zoom_in",  # =
        0xBD: "zoom_out",  # -
        0xDD: "size_up",  # ]
        0xDB: "size_down",  # [
        0x30: "reset_trim",  # 0
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._listener = None
        self._mouse_listener = None
        self._pressed_vks: set[int] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._listener is not None:
            return
        try:
            from pynput import keyboard

            listener = keyboard.Listener(
                on_press=self._on_key_press,
                on_release=self._on_key_release,
            )
            listener.daemon = True
            listener.start()
            with self._lock:
                self._listener = listener
        except Exception as exc:  # pragma: no cover - platform dependent
            self.error.emit(
                tr("Global hotkeys are unavailable: {exc}").format(exc=exc)
            )

        try:
            from pynput import mouse

            mouse_listener = mouse.Listener(on_scroll=self._on_scroll)
            mouse_listener.daemon = True
            mouse_listener.start()
            with self._lock:
                self._mouse_listener = mouse_listener
        except Exception as exc:  # pragma: no cover - platform dependent
            self.error.emit(
                tr("Global mouse wheel is unavailable: {exc}").format(exc=exc)
            )

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

    @staticmethod
    def _vk(key: object) -> int | None:
        vk = getattr(key, "vk", None)
        if vk is None:
            vk = getattr(getattr(key, "value", None), "vk", None)
        return int(vk) if vk is not None else None

    def _on_key_press(self, key: object) -> None:
        vk = self._vk(key)
        if vk is None:
            return
        with self._lock:
            if vk in self._pressed_vks:
                return
            self._pressed_vks.add(vk)
        action = self.HOTKEYS.get(vk)
        if action is not None and self._ctrl_alt_down():
            self._dispatch(action)

    def _on_key_release(self, key: object) -> None:
        vk = self._vk(key)
        if vk is None:
            return
        with self._lock:
            self._pressed_vks.discard(vk)

    def _dispatch(self, name: str) -> None:
        with contextlib.suppress(Exception):
            getattr(self, name).emit()

    def stop(self) -> None:
        with self._lock:
            listener = self._listener
            mouse_listener = self._mouse_listener
            self._listener = None
            self._mouse_listener = None
            self._pressed_vks.clear()
        for item in (listener, mouse_listener):
            if item is not None:
                with contextlib.suppress(Exception):
                    item.stop()
