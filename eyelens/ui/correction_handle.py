"""Small draggable handle used to correct the lens position with the mouse."""

from __future__ import annotations

import contextlib
import ctypes
import os
import platform
import sys
from ctypes import wintypes

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget


class CorrectionHandle(QWidget):
    """A tiny always-on-top handle that can be dragged anywhere on screen.

    It is a separate small window instead of making the full-screen lens
    interactive: clicks outside the handle keep going to the desktop.
    """

    moved = Signal(QPointF)
    released = Signal(QPointF)
    cancelled = Signal()

    SIZE = 48

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("Drag to where you are looking, then release")
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setWindowTitle("eyeLens correction handle")
        self._dragging = False
        self._drag_offset = QPointF()
        self._last_target = QPointF()

    # ------------------------------------------------------------------ public
    def set_center(self, center: QPointF) -> None:
        self.move(
            int(round(center.x() - self.SIZE / 2.0)),
            int(round(center.y() - self.SIZE / 2.0)),
        )

    def center(self) -> QPointF:
        return QPointF(self.geometry().center())

    # --------------------------------------------------------------- lifecycle
    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._configure_native)

    def _configure_native(self) -> None:
        if not self.isVisible():
            return
        if platform.system() != "Windows":
            return
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            gwl_exstyle = -20
            get_window_long = getattr(
                user32, "GetWindowLongPtrW", user32.GetWindowLongW
            )
            set_window_long = getattr(
                user32, "SetWindowLongPtrW", user32.SetWindowLongW
            )
            get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_window_long.restype = ctypes.c_ssize_t
            set_window_long.argtypes = [
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_ssize_t,
            ]
            set_window_long.restype = ctypes.c_ssize_t
            ex_style = get_window_long(hwnd, gwl_exstyle)
            ex_style |= 0x00000080  # WS_EX_TOOLWINDOW
            ex_style |= 0x08000000  # WS_EX_NOACTIVATE
            set_window_long(hwnd, gwl_exstyle, ex_style)

            user32.SetWindowPos.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL
            hwnd_topmost = wintypes.HWND(-1)
            flags = 0x0001 | 0x0002 | 0x0010 | 0x0020
            user32.SetWindowPos(hwnd, hwnd_topmost, 0, 0, 0, 0, flags)

            if (
                hasattr(user32, "SetWindowDisplayAffinity")
                and os.environ.get("EYELENS_NO_CAPTURE_EXCLUDE") != "1"
            ):
                user32.SetWindowDisplayAffinity.argtypes = [
                    wintypes.HWND,
                    wintypes.DWORD,
                ]
                user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
                if not user32.SetWindowDisplayAffinity(hwnd, 0x11):
                    print(
                        "eyeLens: warning: could not exclude the correction "
                        "handle from screen capture.",
                        file=sys.stderr,
                    )
        except Exception as exc:  # pragma: no cover - Windows API dependent
            print(
                f"eyeLens: correction handle styling failed: {exc}",
                file=sys.stderr,
            )

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_target = QPointF(self.geometry().center())
            self._drag_offset = event.globalPosition() - self._last_target
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._last_target = event.globalPosition() - self._drag_offset
            self.moved.emit(self._last_target)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.released.emit(self._last_target)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # -------------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        center = rect.center()
        radius = self.SIZE / 2.0 - 5.0

        shadow = QRadialGradient(center, radius + 5.0)
        shadow.setColorAt(0.0, QColor(0, 0, 0, 0))
        shadow.setColorAt(0.78, QColor(0, 0, 0, 0))
        shadow.setColorAt(0.92, QColor(0, 0, 0, 95))
        shadow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shadow)
        painter.drawEllipse(center, radius + 5.0, radius + 5.0)

        painter.setBrush(QColor(5, 11, 19, 238))
        painter.setPen(QPen(QColor(56, 189, 248, 235), 2.0))
        painter.drawEllipse(center, radius, radius)

        painter.setPen(
            QPen(
                QColor(235, 246, 255, 235),
                2.0,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        reach = 10.5
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            tip = QPointF(center.x() + dx * reach, center.y() + dy * reach)
            painter.drawLine(center, tip)
            if dx:
                painter.drawLine(tip, tip + QPointF(-dx * 4.0, -3.0))
                painter.drawLine(tip, tip + QPointF(-dx * 4.0, 3.0))
            else:
                painter.drawLine(tip, tip + QPointF(-3.0, -dy * 4.0))
                painter.drawLine(tip, tip + QPointF(3.0, -dy * 4.0))

        painter.setBrush(QColor(56, 189, 248, 255))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, 2.6, 2.6)
        painter.end()

    def closeEvent(self, event) -> None:
        with contextlib.suppress(Exception):
            self.releaseMouse()
        super().closeEvent(event)
