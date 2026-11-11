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
    QCursor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QScreen,
)
from PySide6.QtWidgets import QWidget

from ..capture import ScreenCapture, source_extent
from ..config import ScreenInfo, Settings, lens_dimensions
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


def clamp_lens_center(
    center_x: float,
    center_y: float,
    lens_width: float,
    lens_height: float,
    screen_width: float,
    screen_height: float,
) -> tuple[float, float]:
    """Keep the lens centre on the screen, even if its edge goes off-screen.

    The old behaviour kept the whole lens on screen, which made the very
    corners and the taskbar unreachable: the lens stopped half a diameter
    before them.  A magnifier needs to cover the border itself, so the visible
    part of the lens is allowed to be clipped there.
    """
    if lens_width >= screen_width:
        x = screen_width / 2.0
    else:
        x = min(max(float(center_x), 0.0), screen_width)
    if lens_height >= screen_height:
        y = screen_height / 2.0
    else:
        y = min(max(float(center_y), 0.0), screen_height)
    return x, y


def lens_path_for_rect(rect: QRectF, shape: str) -> QPainterPath:
    path = QPainterPath()
    if shape == "round":
        path.addEllipse(rect)
    else:
        corner = min(14.0, min(rect.width(), rect.height()) * 0.06)
        path.addRoundedRect(rect, corner, corner)
    return path


def lens_source_point(
    center: QPointF,
    local_point: QPointF,
    zoom: float,
) -> QPointF:
    """Map a point inside the magnified image to its real screen position.

    The lens shows the area around ``center`` scaled by ``zoom``.  A click at
    ``local_point`` in the lens therefore belongs to the source point at
    ``center + (local_point - center) / zoom``.
    """
    zoom = max(0.01, float(zoom))
    return QPointF(
        center.x() + (local_point.x() - center.x()) / zoom,
        center.y() + (local_point.y() - center.y()) / zoom,
    )


def point_in_lens(
    center: QPointF,
    local_point: QPointF,
    width: float,
    height: float,
    shape: str,
) -> bool:
    rect = QRectF(
        center.x() - width / 2.0,
        center.y() - height / 2.0,
        width,
        height,
    )
    return lens_path_for_rect(rect, shape).contains(local_point)


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
        width, height = lens_dimensions(
            self._settings.shape, self._settings.diameter
        )
        self._display_width = float(width)
        self._display_height = float(height)
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
        self._force_click_through = False
        self._pending_click: tuple[QPointF, Qt.MouseButton] | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
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
            or old.shape != self._settings.shape
        ):
            width, height = lens_dimensions(
                self._settings.shape, self._settings.diameter
            )
            size = (
                f"{width}×{height} px"
                if self._settings.shape == "wide"
                else f"{height} px"
            )
            self.flash_osd(f"{self._settings.zoom:.2f}×  ·  {size}")
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
        if self.engine.demo or self.engine.pointer_fallback:
            follows = "the pointer"
        elif (
            self.engine.model is not None
            and self.engine.model.control_mode == "head"
        ):
            follows = "your head"
        else:
            follows = "your gaze"
        self.flash_osd(
            "Lens locked" if self._locked else f"Lens follows {follows}"
        )
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
        self._pending_click = None
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

    def _clamp_center(
        self, center: QPointF, lens_width: float, lens_height: float
    ) -> QPointF:
        x, y = clamp_lens_center(
            center.x(),
            center.y(),
            lens_width,
            lens_height,
            float(self.screen.geometry().width()),
            float(self.screen.geometry().height()),
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
            local, self._display_width, self._display_height
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
        head_control = (
            self.engine.model is not None
            and self.engine.model.control_mode == "head"
        )
        self.flash_osd(
            "Keep facing the lens…" if head_control else "Hold your gaze on the lens…",
            duration=1.2,
        )
        self.correction_committed.emit(target.x(), target.y())

    def _cancel_from_handle(self) -> None:
        self.cancel_correction()

    # --------------------------------------------------------------- Qt events
    def nativeEvent(self, event_type, message):
        """Hit-test only the lens, not the transparent full-screen window.

        Outside the lens the overlay must remain click-through so the user can
        keep working.  Inside the lens the overlay receives the click and
        translates it to the real magnified content.
        """
        if platform.system() == "Windows":
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    if self._force_click_through or self.correction_active:
                        return True, -1  # HTTRANSPARENT
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    origin = self.screen.geometry().topLeft()
                    dpr = max(1.0, float(self.screen.devicePixelRatio()))
                    # WM_NCHITTEST coordinates are physical pixels; the lens
                    # geometry is in Qt logical pixels.
                    local = QPointF(
                        x / dpr - origin.x(), y / dpr - origin.y()
                    )
                    if self._lens_contains(local):
                        return True, 1  # HTCLIENT
                    return True, -1  # HTTRANSPARENT
            except Exception:
                pass
        return super().nativeEvent(event_type, message)

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
        self._pending_click = None
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
            # Interactive lens: the window is hit-testable inside the lens
            # shape only (see nativeEvent/WM_NCHITTEST).  Do not set
            # WS_EX_TRANSPARENT here; clicks outside the lens are passed
            # through by the custom hit test, and clicks inside are translated
            # to the real magnified content.
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

    def _set_click_through(self, enabled: bool) -> None:
        """Temporarily let a synthesized click reach the window below.

        The lens itself sits over the content it magnifies.  When the user
        clicks a magnified control we move the real cursor to the source point
        and inject a click; during that instant the overlay must not intercept
        its own injected click.
        """
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
            style = get_window_long(hwnd, gwl_exstyle)
            if enabled:
                style |= 0x00000020  # WS_EX_TRANSPARENT
            else:
                style &= ~0x00000020
            set_window_long(hwnd, gwl_exstyle, style)
        except Exception:
            pass

    # ----------------------------------------------------------- interactive lens
    def _lens_contains(self, local_point: QPointF) -> bool:
        if self._visibility <= 0.004:
            return False
        return point_in_lens(
            self._display_center,
            local_point,
            max(20.0, self._display_width),
            max(20.0, self._display_height),
            self._settings.shape,
        )

    def _source_point_for(self, local_point: QPointF) -> QPointF:
        geometry = self.screen.geometry()
        origin = geometry.topLeft()
        local = lens_source_point(
            self._display_center,
            local_point,
            self._settings.zoom,
        )
        x = min(max(origin.x() + local.x(), geometry.left()), geometry.right())
        y = min(max(origin.y() + local.y(), geometry.top()), geometry.bottom())
        return QPointF(x, y)

    def _with_source_cursor(self, source: QPointF) -> None:
        """Move the real cursor to the source point for one input event."""
        self._force_click_through = True
        self._set_click_through(True)
        self._saved_cursor = QCursor.pos()
        # The physical click may still have mouse capture on the overlay,
        # which would route the synthetic click back here regardless of
        # position or hit-testing.
        with contextlib.suppress(Exception):
            self.releaseMouse()
        with contextlib.suppress(Exception):
            ctypes.windll.user32.ReleaseCapture()
        QCursor.setPos(int(round(source.x())), int(round(source.y())))

    def _finish_click_through(self) -> None:
        self._set_click_through(False)
        self._force_click_through = False

    def _inject_click(self, source: QPointF, button: Qt.MouseButton) -> None:
        """Click the real screen at ``source`` without moving the lens."""
        if platform.system() != "Windows":
            return
        flags = {
            Qt.MouseButton.LeftButton: (0x0002, 0x0004),
            Qt.MouseButton.RightButton: (0x0008, 0x0010),
            Qt.MouseButton.MiddleButton: (0x0020, 0x0040),
        }.get(button)
        if flags is None:
            return
        self._with_source_cursor(source)
        try:
            user32 = ctypes.windll.user32
            user32.mouse_event(flags[0], 0, 0, 0, 0)
            user32.mouse_event(flags[1], 0, 0, 0, 0)
        finally:
            QCursor.setPos(self._saved_cursor)
            # Keep the window click-through briefly while the input queue
            # delivers the synthetic click; otherwise it can land back on the
            # lens.
            QTimer.singleShot(60, self._finish_click_through)

    def _inject_wheel(
        self, source: QPointF, delta: int, horizontal: bool
    ) -> None:
        if platform.system() != "Windows" or not delta:
            return
        self._with_source_cursor(source)
        try:
            flag = 0x01000 if horizontal else 0x0800  # HWHEEL / WHEEL
            data = ctypes.c_uint(int(delta) & 0xFFFFFFFF).value
            ctypes.windll.user32.mouse_event(flag, 0, 0, data, 0)
        finally:
            QCursor.setPos(self._saved_cursor)
            QTimer.singleShot(60, self._finish_click_through)

    def wheelEvent(self, event) -> None:
        local = self._local_point(event)
        if not self._lens_contains(local):
            event.ignore()
            return
        angle = event.angleDelta()
        if angle.y():
            self._inject_wheel(self._source_point_for(local), angle.y(), False)
        elif angle.x():
            self._inject_wheel(self._source_point_for(local), angle.x(), True)
        event.accept()

    def _local_point(self, event) -> QPointF:
        return event.position()

    def mousePressEvent(self, event) -> None:
        local = self._local_point(event)
        if not self._lens_contains(local):
            self._pending_click = None
            event.ignore()
            return
        # Defer the real click until the mouse is released.  Injecting while
        # the physical button is down means Windows still has mouse capture on
        # the overlay, so the synthetic click would come straight back here.
        self._pending_click = (self._source_point_for(local), event.button())
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        self.mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        pending = self._pending_click
        self._pending_click = None
        if pending is None or not self._lens_contains(
            self._local_point(event)
        ):
            event.ignore()
            return
        source, button = pending
        QTimer.singleShot(10, lambda: self._inject_click(source, button))
        event.accept()

    # -------------------------------------------------------------------- timer
    def _tick(self) -> None:
        now = time.monotonic()
        dt = max(0.001, min(0.1, now - self._last_tick))
        self._last_tick = now

        settings = self._settings
        can_show = settings.lens_visible and (
            self.engine.demo
            or self.engine.pointer_fallback
            or self.engine.model is not None
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

        # Ease the lens size, then keep the lens fully on screen.
        target_w, target_h = lens_dimensions(
            settings.shape, settings.diameter
        )
        self._display_width += (float(target_w) - self._display_width) * (
            1.0 - math.exp(-dt / 0.09)
        )
        self._display_height += (float(target_h) - self._display_height) * (
            1.0 - math.exp(-dt / 0.09)
        )
        width = max(20.0, self._display_width)
        height = max(20.0, self._display_height)
        self._display_center = self._clamp_center(
            self._display_center, width, height
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
                width,
                height,
                settings.zoom,
            )
            self.capture.set_active(True)
        else:
            self.capture.set_active(False)

        self._update_paint()

    def _lens_rect(
        self, center: QPointF, width: float, height: float
    ) -> QRectF:
        return QRectF(
            center.x() - width / 2.0 - self.SHADOW,
            center.y() - height / 2.0 - self.SHADOW,
            width + self.SHADOW * 2,
            height + self.SHADOW * 2,
        )

    def _lens_path(self, rect: QRectF) -> QPainterPath:
        return lens_path_for_rect(rect, self._settings.shape)

    def _update_paint(self) -> None:
        now = time.monotonic()
        osd_visible = now < self._osd_until
        frame = self.capture.latest()
        state = (
            round(self._display_center.x(), 2),
            round(self._display_center.y(), 2),
            round(self._display_width, 2),
            round(self._display_height, 2),
            self._settings.shape,
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
        new_bounds = self._lens_rect(
            self._display_center, self._display_width, self._display_height
        )
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
        width = max(20.0, self._display_width)
        height = max(20.0, self._display_height)
        rect = QRectF(
            center.x() - width / 2.0,
            center.y() - height / 2.0,
            width,
            height,
        )
        settings = self._settings
        alpha = visibility * settings.opacity
        painter.setOpacity(alpha)

        lens_path = self._lens_path(rect)
        self._draw_shadow(painter, lens_path)

        painter.save()
        painter.setClipPath(lens_path)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(5, 11, 19, 245))
        painter.drawPath(lens_path)

        frame = self.capture.latest()
        if frame is not None:
            self._draw_captured(painter, frame, rect, settings.zoom)
        else:
            self._draw_loading(painter, rect)

        # Subtle vignette so the magnified image melts into the rim.
        vignette = QRadialGradient(
            rect.center(), max(width, height) * 0.55
        )
        vignette.setColorAt(0.0, QColor(0, 0, 0, 0))
        vignette.setColorAt(0.78, QColor(0, 0, 0, 0))
        vignette.setColorAt(1.0, QColor(0, 0, 0, 120))
        painter.setBrush(vignette)
        painter.drawPath(lens_path)

        if settings.show_osd:
            self._draw_osd(painter, rect)
        painter.restore()

        if settings.show_ring:
            ring_color = (
                QColor(245, 158, 11, 235)
                if self._locked
                else QColor(235, 246, 255, 220)
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(0, 0, 0, 90), 3.2))
            painter.drawPath(lens_path)
            painter.setPen(QPen(ring_color, 1.7))
            painter.drawPath(lens_path)

        painter.end()

    def _draw_shadow(self, painter: QPainter, path: QPainterPath) -> None:
        """A soft shadow that works for circles and rectangles alike."""
        painter.save()
        painter.translate(0, 3.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for step in range(7, 0, -1):
            spread = self.SHADOW * 1.8 * step / 7.0
            alpha = int(5 + 6 * (7 - step))
            pen = QPen(QColor(0, 0, 0, alpha), spread)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(path)
        painter.restore()

    def _draw_captured(
        self,
        painter: QPainter,
        frame,
        rect: QRectF,
        zoom: float,
    ) -> None:
        image = frame.image
        if image is None or image.isNull():
            return
        source_w = source_extent(rect.width(), zoom) * frame.scale_x
        source_h = source_extent(rect.height(), zoom) * frame.scale_y
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
        # Map the cropped part of the source image exactly onto its place in
        # the lens; areas beyond the edge of the screen stay dark.
        nx = (inter.left() - src.left()) / src.width()
        ny = (inter.top() - src.top()) / src.height()
        nw = inter.width() / src.width()
        nh = inter.height() / src.height()
        dst = QRectF(
            rect.left() + nx * rect.width(),
            rect.top() + ny * rect.height(),
            nw * rect.width(),
            nh * rect.height(),
        )
        painter.drawImage(dst, image, inter)

    def _draw_loading(self, painter: QPainter, rect: QRectF) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        radius = min(rect.width(), rect.height()) * 0.28
        center = rect.center()
        pen = QPen(QColor(56, 189, 248, 120), max(1.5, radius * 0.06))
        painter.setPen(pen)
        arc_rect = QRectF(
            center.x() - radius,
            center.y() - radius,
            radius * 2.0,
            radius * 2.0,
        )
        start = int((time.monotonic() * 220) % 360 * 16)
        painter.drawArc(arc_rect, start, 100 * 16)

    def _draw_osd(self, painter: QPainter, rect: QRectF) -> None:
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
        height = rect.height()
        font_size = int(max(10.0, min(16.0, height * 0.085)))
        font = QFont("Segoe UI", font_size)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text = self._osd_text
        text_width = metrics.horizontalAdvance(text)
        pad_x = max(8.0, height * 0.09)
        pad_y = max(4.0, height * 0.045)
        bottom_margin = max(8.0, height * 0.07)
        box = QRectF(
            rect.center().x() - text_width / 2 - pad_x,
            rect.bottom() - bottom_margin - metrics.height() - pad_y * 2,
            text_width + pad_x * 2,
            metrics.height() + pad_y * 2,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(5, 11, 19, int(175 * fade)))
        painter.drawRoundedRect(box, box.height() / 2, box.height() / 2)
        painter.setPen(QColor(240, 249, 255, int(245 * fade)))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
