"""The always-on-top, click-through magnifying lens."""

from __future__ import annotations

import contextlib
import ctypes
import math
import os
import platform
import sys
import time
from ctypes import wintypes

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QScreen,
)
from PySide6.QtWidgets import QWidget

from ..capture import ScreenCapture, source_extent
from ..config import ScreenInfo, Settings
from ..gaze.engine import GazeEngine
from .correction_handle import CorrectionHandle


def screen_info(screen: QScreen) -> ScreenInfo:
    geometry = screen.geometry()
    return ScreenInfo.from_values(
        name=screen.name(),
        left=geometry.left(),
        top=geometry.top(),
        width=geometry.width(),
        height=geometry.height(),
        dpr=screen.devicePixelRatio(),
    )


class LensOverlay(QWidget):
    screen_changed = Signal()
    correction_started = Signal()
    correction_committed = Signal(float, float)
    correction_cancelled = Signal()

    SHADOW = 26.0

    def __init__(
        self,
        screen,
        engine: GazeEngine,
        capture: ScreenCapture,
        settings: Settings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.screen = screen
        self.engine = engine
        self.capture = capture
        self._settings = settings.copy()
        self._locked = False
        self._visibility = 0.0
        self._display_center = QPointF(
            screen.geometry().width() / 2.0, screen.geometry().height() / 2.0
        )
        self._display_diameter = float(self._settings.diameter)
        self._has_gaze = False
        self._last_bounds = QRectF()
        self._last_paint_state: tuple | None = None
        self._osd_text = ""
        self._osd_until = 0.0
        self._osd_started = 0.0
        self._check_native_on_next_show = True
        self._correcting = False
        self._correction_hold = False
        self._handle: CorrectionHandle | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(screen.geometry())
        self.setWindowTitle("eyeLens overlay")

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._last_tick = time.monotonic()

        screen.geometryChanged.connect(self._on_screen_geometry_changed)

    # ------------------------------------------------------------------ public
    def apply_settings(self, settings: Settings) -> None:
        old = self._settings
        self._settings = settings.copy()
        if (
            abs(old.zoom - self._settings.zoom) > 1e-6
            or old.diameter != self._settings.diameter
        ):
            self.flash_osd(
                f"{self._settings.zoom:.2f}×  ·  {self._settings.diameter} px"
            )
        self._update_paint()

    def set_capture(self, capture: ScreenCapture) -> None:
        with contextlib.suppress(Exception):
            self.capture.set_active(False)
        self.capture = capture
        self._last_paint_state = None
        self._update_paint()

    def flash_osd(self, text: str, duration: float = 1.35) -> None:
        if not self._settings.show_osd:
            return
        now = time.monotonic()
        self._osd_text = text
        self._osd_started = now
        self._osd_until = now + duration
        self._update_paint()

    def toggle_locked(self) -> None:
        self._locked = not self._locked
        self.flash_osd("Lens locked" if self._locked else "Lens follows gaze")
        self._update_paint()

    @property
    def locked(self) -> bool:
        return self._locked

    def current_diameter(self) -> int:
        return self._settings.diameter

    # ------------------------------------------------------- mouse correction
    @property
    def correction_active(self) -> bool:
        return self._correcting or self._correction_hold

    def begin_correction(self) -> bool:
        """Make the lens draggable with a small on-screen handle."""
        if self.correction_active:
            return False
        self._correcting = True
        self._has_gaze = True
        if not self.isVisible():
            self.show()
        self.raise_()
        if self._handle is None:
            self._handle = CorrectionHandle()
            self._handle.moved.connect(self._on_handle_moved)
            self._handle.released.connect(self._on_handle_released)
            self._handle.cancelled.connect(self._cancel_from_handle)
        self._handle.set_center(self._global_center())
        self._handle.show()
        self._handle.raise_()
        self.flash_osd("Drag the handle to where you are looking", duration=4.0)
        self.correction_started.emit()
        return True

    def cancel_correction(self) -> bool:
        if not self.correction_active:
            return False
        self._correcting = False
        self._correction_hold = False
        if self._handle is not None:
            self._handle.hide()
        self.flash_osd("Correction cancelled")
        self.correction_cancelled.emit()
        return True

    def finish_correction(self, success: bool) -> None:
        self._correcting = False
        self._correction_hold = False
        self._has_gaze = True
        if self._handle is not None:
            self._handle.hide()
        self.flash_osd(
            "Correction learned" if success else "Correction not learned",
            duration=1.8 if success else 2.2,
        )

    def _global_center(self) -> QPointF:
        origin = self.screen.geometry().topLeft()
        return QPointF(
            origin.x() + self._display_center.x(),
            origin.y() + self._display_center.y(),
        )

    def _clamp_center(self, center: QPointF, diameter: float) -> QPointF:
        radius = diameter / 2.0
        width = float(self.screen.geometry().width())
        height = float(self.screen.geometry().height())
        x = (
            width / 2.0
            if diameter >= width
            else min(max(center.x(), radius), width - radius)
        )
        y = (
            height / 2.0
            if diameter >= height
            else min(max(center.y(), radius), height - radius)
        )
        return QPointF(x, y)

    def _on_handle_moved(self, global_center: QPointF) -> None:
        if not self._correcting:
            return
        origin = self.screen.geometry().topLeft()
        local = QPointF(
            global_center.x() - origin.x(),
            global_center.y() - origin.y(),
        )
        self._display_center = self._clamp_center(
            local, self._display_diameter
        )
        self._has_gaze = True
        self._last_paint_state = None
        self._update_paint()
        if self._handle is not None:
            self._handle.set_center(self._global_center())

    def _on_handle_released(self, _global_center: QPointF) -> None:
        if not self._correcting:
            return
        self._correcting = False
        self._correction_hold = True
        if self._handle is not None:
            self._handle.hide()
        target = self._global_center()
        self.flash_osd("Hold your gaze on the lens…", duration=1.2)
        self.correction_committed.emit(target.x(), target.y())

    def _cancel_from_handle(self) -> None:
        self.cancel_correction()

    # --------------------------------------------------------------- Qt events
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.setGeometry(self.screen.geometry())
        self._visibility = 0.0
        self._has_gaze = False
        self._last_paint_state = None
        self._last_bounds = QRectF()
        self._last_tick = time.monotonic()
        QTimer.singleShot(0, self._configure_native)
        self._timer.start()

    def hideEvent(self, event) -> None:
        if self.correction_active:
            self.cancel_correction()
        if self._handle is not None:
            self._handle.hide()
        self.capture.set_active(False)
        self._timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        if self.correction_active:
            self.cancel_correction()
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        self._timer.stop()
        self.capture.set_active(False)
        screen = self.screen
        with contextlib.suppress(RuntimeError, TypeError):
            screen.geometryChanged.disconnect(self._on_screen_geometry_changed)
        super().closeEvent(event)

    def _on_screen_geometry_changed(self, _rect) -> None:
        if self.correction_active:
            self.cancel_correction()
        self.setGeometry(self.screen.geometry())
        self._configure_native()
        self._update_paint()
        self.screen_changed.emit()

    # ---------------------------------------------------------------- native win
    def _configure_native(self) -> None:
        if platform.system() != "Windows":
            return
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            gwl_exstyle = -20
            get_window_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_window_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
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
            ex_style |= 0x00080000  # WS_EX_LAYERED
            ex_style |= 0x08000000  # WS_EX_NOACTIVATE
            ex_style |= 0x00000020  # WS_EX_TRANSPARENT
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
            flags = 0x0001 | 0x0002 | 0x0010 | 0x0020  # NOSIZE|NOMOVE|NOACTIVATE|FRAMECHANGED
            user32.SetWindowPos(hwnd, hwnd_topmost, 0, 0, 0, 0, flags)
            # Keep the lens out of its own screen capture. Without this the
            # overlay would show an infinite mirror of itself.
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
                        "eyeLens: warning: could not exclude overlay from screen "
                        "capture; lens may show feedback.",
                        file=sys.stderr,
                    )
        except Exception as exc:  # pragma: no cover - Windows API dependent
            print(f"eyeLens: overlay styling failed: {exc}", file=sys.stderr)

    # -------------------------------------------------------------------- timer
    def _tick(self) -> None:
        now = time.monotonic()
        dt = max(0.001, min(0.1, now - self._last_tick))
        self._last_tick = now

        settings = self._settings
        can_show = settings.lens_visible and (
            self.engine.demo or self.engine.model is not None
        )
        valid = False
        target: QPointF | None = None
        if self.correction_active:
            # The correction handle owns the position; do not let gaze
            # prediction fight the mouse.
            valid = can_show
        elif can_show and self._locked:
            valid = True
        elif can_show:
            center = self.engine.current_center()
            live = self.engine.demo or self.engine.tracking_live()
            if center is not None and live:
                target = QPointF(center[0], center[1]) - self.screen.geometry().topLeft()
                valid = True

        if valid and target is not None:
            if not self._has_gaze:
                self._display_center = target
                self._has_gaze = True
            else:
                # Deliberately relaxed follow time constant: the lens should
                # glide after the eyes instead of chasing every tracker jitter.
                factor = 1.0 - math.exp(-dt / 0.085)
                self._display_center += (target - self._display_center) * factor
        if valid:
            self._has_gaze = True

        # Ease the diameter, then keep the lens fully on screen.
        d_target = float(settings.diameter)
        self._display_diameter += (d_target - self._display_diameter) * (
            1.0 - math.exp(-dt / 0.09)
        )
        diameter = max(20.0, self._display_diameter)
        self._display_center = self._clamp_center(
            self._display_center, diameter
        )
        if self._correcting and self._handle is not None:
            self._handle.set_center(self._global_center())

        vis_target = 1.0 if valid else 0.0
        tau = 0.10 if vis_target > self._visibility else 0.14
        self._visibility += (vis_target - self._visibility) * (
            1.0 - math.exp(-dt / tau)
        )
        if self._visibility < 0.004:
            self._visibility = 0.0
        elif self._visibility > 0.996:
            self._visibility = 1.0

        if self._visibility > 0.004:
            self.capture.set_request(
                self._display_center.x(),
                self._display_center.y(),
                diameter,
                settings.zoom,
            )
            self.capture.set_active(True)
        else:
            self.capture.set_active(False)

        self._update_paint()

    def _lens_rect(self, center: QPointF, diameter: float) -> QRectF:
        radius = diameter / 2.0
        return QRectF(
            center.x() - radius - self.SHADOW,
            center.y() - radius - self.SHADOW,
            diameter + self.SHADOW * 2,
            diameter + self.SHADOW * 2,
        )

    def _update_paint(self) -> None:
        now = time.monotonic()
        osd_visible = now < self._osd_until
        frame = self.capture.latest()
        state = (
            round(self._display_center.x(), 2),
            round(self._display_center.y(), 2),
            round(self._display_diameter, 2),
            round(self._visibility, 3),
            self._locked,
            round(self._osd_until - now, 2) if osd_visible else 0.0,
            self._settings.show_ring,
            self._settings.zoom,
            self._settings.opacity,
            round(frame.timestamp, 2) if frame is not None else 0.0,
        )
        if state == self._last_paint_state:
            return
        self._last_paint_state = state
        new_bounds = self._lens_rect(self._display_center, self._display_diameter)
        dirty = new_bounds.united(self._last_bounds).toAlignedRect()
        self._last_bounds = new_bounds
        if dirty.isValid():
            self.update(dirty)

    # -------------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(event.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceOver
        )

        visibility = self._visibility
        if visibility <= 0.004:
            painter.end()
            return

        center = self._display_center
        diameter = max(20.0, self._display_diameter)
        radius = diameter / 2.0
        settings = self._settings
        alpha = visibility * settings.opacity
        painter.setOpacity(alpha)

        # Soft drop shadow.
        shadow = QRadialGradient(
            center, radius + self.SHADOW, QPointF(center.x(), center.y() - radius * 0.2)
        )
        shadow.setColorAt(0.0, QColor(0, 0, 0, 0))
        shadow.setColorAt(0.83, QColor(0, 0, 0, 0))
        shadow.setColorAt(0.93, QColor(0, 0, 0, 70))
        shadow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shadow)
        painter.drawEllipse(center, radius + self.SHADOW, radius + self.SHADOW)

        lens_path = QPainterPath()
        lens_path.addEllipse(center, radius, radius)
        painter.save()
        painter.setClipPath(lens_path)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(5, 11, 19, 245))
        painter.drawEllipse(center, radius, radius)

        frame = self.capture.latest()
        if frame is not None:
            self._draw_captured(painter, frame, center, diameter, settings.zoom)
        else:
            self._draw_loading(painter, center, radius)

        # Subtle vignette so the magnified image melts into the rim.
        vignette = QRadialGradient(center, radius)
        vignette.setColorAt(0.0, QColor(0, 0, 0, 0))
        vignette.setColorAt(0.78, QColor(0, 0, 0, 0))
        vignette.setColorAt(1.0, QColor(0, 0, 0, 120))
        painter.setBrush(vignette)
        painter.drawEllipse(center, radius, radius)

        if settings.show_osd:
            self._draw_osd(painter, center, radius)
        painter.restore()

        if settings.show_ring:
            ring_color = (
                QColor(245, 158, 11, 235)
                if self._locked
                else QColor(235, 246, 255, 220)
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(0, 0, 0, 90), 3.2))
            painter.drawEllipse(center, radius + 0.6, radius + 0.6)
            painter.setPen(QPen(ring_color, 1.7))
            painter.drawEllipse(center, radius + 0.2, radius + 0.2)

        painter.end()

    def _draw_captured(
        self,
        painter: QPainter,
        frame,
        center: QPointF,
        diameter: float,
        zoom: float,
    ) -> None:
        image = frame.image
        if image is None or image.isNull():
            return
        source_w = source_extent(diameter, zoom) * frame.scale_x
        source_h = source_extent(diameter, zoom) * frame.scale_y
        src = QRectF(
            frame.center_x - source_w / 2.0,
            frame.center_y - source_h / 2.0,
            source_w,
            source_h,
        )
        image_rect = QRectF(0, 0, image.width(), image.height())
        inter = src.intersected(image_rect)
        if inter.width() <= 0 or inter.height() <= 0:
            return
        radius = diameter / 2.0
        target = QRectF(
            center.x() - radius, center.y() - radius, diameter, diameter
        )
        # Map the cropped part of the source image exactly onto its place in
        # the lens; areas beyond the edge of the screen stay dark.
        nx = (inter.left() - src.left()) / src.width()
        ny = (inter.top() - src.top()) / src.height()
        nw = inter.width() / src.width()
        nh = inter.height() / src.height()
        dst = QRectF(
            target.left() + nx * target.width(),
            target.top() + ny * target.height(),
            nw * target.width(),
            nh * target.height(),
        )
        painter.drawImage(dst, image, inter)

    def _draw_loading(self, painter: QPainter, center: QPointF, radius: float) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(56, 189, 248, 120), max(1.5, radius * 0.018))
        painter.setPen(pen)
        rect = QRectF(
            center.x() - radius * 0.55,
            center.y() - radius * 0.55,
            radius * 1.1,
            radius * 1.1,
        )
        start = int((time.monotonic() * 220) % 360 * 16)
        painter.drawArc(rect, start, 100 * 16)

    def _draw_osd(self, painter: QPainter, center: QPointF, radius: float) -> None:
        now = time.monotonic()
        if now >= self._osd_until or not self._osd_text:
            return
        remaining = self._osd_until - now
        fade = 1.0
        if remaining < 0.35:
            fade = max(0.0, remaining / 0.35)
        if self._osd_started > 0:
            fade = min(fade, max(0.0, (now - self._osd_started) / 0.10))
        if fade <= 0.0:
            return
        font_size = int(max(10.0, min(16.0, radius * 0.085)))
        font = QFont("Segoe UI", font_size)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text = self._osd_text
        text_width = metrics.horizontalAdvance(text)
        pad_x = max(8.0, radius * 0.09)
        pad_y = max(4.0, radius * 0.045)
        box = QRectF(
            center.x() - text_width / 2 - pad_x,
            center.y() + radius * 0.48 - metrics.height() / 2 - pad_y,
            text_width + pad_x * 2,
            metrics.height() + pad_y * 2,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(5, 11, 19, int(175 * fade)))
        painter.drawRoundedRect(box, box.height() / 2, box.height() / 2)
        painter.setPen(QColor(240, 249, 255, int(245 * fade)))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
