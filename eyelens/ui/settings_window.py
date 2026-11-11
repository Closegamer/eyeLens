"""Settings / status window and camera preview."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings, lens_dimensions
from ..gaze.engine import GazeEngine
from ..gaze.tracker import EyeTracker
from .icon import make_pixmap

_LEVEL_COLORS = {
    "ok": "#34d399",
    "warn": "#fbbf24",
    "bad": "#f87171",
    "muted": "#64748b",
    "accent": "#38bdf8",
}


@dataclass
class StatusInfo:
    camera_text: str = "Starting…"
    camera_level: str = "warn"
    gaze_text: str = "—"
    gaze_level: str = "muted"
    calibration_text: str = "Not calibrated"
    calibration_detail: str = "Calibrate once before using the lens."
    calibration_level: str = "bad"
    can_calibrate: bool = False
    can_correct: bool = False
    can_big: bool = False
    lens_visible: bool = True
    locked: bool = False
    demo: bool = False


class PreviewWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self._placeholder = "Camera preview"
        self._live = False
        self.setMinimumSize(280, 158)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(300, 169)

    def set_image(self, image: QImage | None) -> None:
        if image is None and self._image is None:
            return
        self._image = image
        self.update()

    def set_placeholder(self, text: str) -> None:
        if self._placeholder != text:
            self._placeholder = text
            self.update()

    def set_live(self, live: bool) -> None:
        if self._live != live:
            self._live = live
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 13, 13)
        painter.setClipPath(path)
        painter.fillRect(rect, QColor("#060d17"))
        if self._image is not None and not self._image.isNull():
            painter.drawImage(rect, self._image)
        else:
            icon = make_pixmap(72)
            target = QRectF(
                rect.center().x() - 32,
                rect.center().y() - 46,
                64,
                64,
            )
            painter.setOpacity(0.35)
            painter.drawPixmap(target.toRect(), icon)
            painter.setOpacity(1.0)
            painter.setPen(QColor("#7b90a8"))
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(
                rect.adjusted(0, 30, 0, 0),
                Qt.AlignmentFlag.AlignCenter,
                self._placeholder,
            )
        # Bottom shade for the label.
        painter.fillRect(
            QRectF(rect.left(), rect.bottom() - 28, rect.width(), 28),
            QColor(3, 8, 15, 120),
        )
        painter.setPen(QColor(190, 210, 230, 160))
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(
            rect.adjusted(12, 0, -12, -8),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            "CAMERA",
        )
        if self._live:
            painter.setBrush(QColor("#34d399"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(
                QRectF(rect.right() - 22, rect.bottom() - 19, 7, 7)
            )
            painter.setPen(QColor(190, 230, 215, 190))
            painter.drawText(
                rect.adjusted(0, 0, -34, -8),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                "LIVE",
            )
        painter.setClipping(False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 26), 1))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 13, 13)


class StatusRow(QWidget):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)
        self.dot = QLabel()
        self.dot.setFixedSize(8, 8)
        self.dot.setStyleSheet("background:#64748b; border-radius:4px;")
        title_label = QLabel(title)
        title_label.setObjectName("muted")
        title_label.setFixedWidth(78)
        self.value = QLabel("—")
        self.value.setWordWrap(True)
        self.value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.dot)
        layout.addWidget(title_label)
        layout.addWidget(self.value, 1)

    def set_status(self, text: str, level: str = "muted") -> None:
        self.value.setText(text)
        color = _LEVEL_COLORS.get(level, _LEVEL_COLORS["muted"])
        self.dot.setStyleSheet(f"background:{color}; border-radius:4px;")
        self.value.setStyleSheet("" if level != "muted" else "color:#94a3b8;")


class SettingsWindow(QWidget):
    settings_changed = Signal()
    calibrate_requested = Signal()
    freeze_requested = Signal()
    correct_requested = Signal()
    big_lens_requested = Signal()
    camera_restart_requested = Signal(int)
    quit_requested = Signal()
    hidden_to_tray = Signal()

    def __init__(
        self,
        settings: Settings,
        tracker: EyeTracker | None = None,
        engine: GazeEngine | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.tracker: EyeTracker | None = None
        self.engine = engine
        self.status_provider: Callable[[], StatusInfo] | None = None
        self._syncing = False
        self._preview_acquired = False
        self._closing_for_real = False
        self._positioned = False
        self.setWindowTitle("eyeLens")
        self.setMinimumWidth(600)
        self.resize(640, 960)
        self.setObjectName("root")
        self._build_ui()
        self._bind_tracker(tracker)
        self._apply_styles()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(450)
        self._status_timer.timeout.connect(self.refresh_status)
        self.sync_from_settings()

    # -------------------------------------------------------------------- build
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("content")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(26, 22, 26, 24)
        layout.setSpacing(16)

        # Header -------------------------------------------------------------
        header = QHBoxLayout()
        header.setSpacing(14)
        icon = QLabel()
        icon.setPixmap(make_pixmap(72).scaled(54, 54, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
        header.addWidget(icon)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel("eyeLens")
        title.setObjectName("title")
        subtitle = QLabel("A magnifying lens that follows your head")
        subtitle.setObjectName("muted")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        version = QLabel("v0.9.1")
        version.setObjectName("badge")
        header.addWidget(version, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        # Status -------------------------------------------------------------
        status_card = QFrame()
        status_card.setObjectName("card")
        status_layout = QHBoxLayout(status_card)
        status_layout.setContentsMargins(16, 16, 16, 16)
        status_layout.setSpacing(16)
        self.preview = PreviewWidget()
        status_layout.addWidget(self.preview, 3)
        status_col = QVBoxLayout()
        status_col.setSpacing(3)
        self.camera_status = StatusRow("Camera")
        self.gaze_status = StatusRow("Control")
        self.calibration_status = StatusRow("Calibration")
        status_col.addWidget(self.camera_status)
        status_col.addWidget(self.gaze_status)
        status_col.addWidget(self.calibration_status)
        status_col.addStretch(1)
        self.detail_label = QLabel("Calibrate once before using the lens.")
        self.detail_label.setObjectName("muted")
        self.detail_label.setWordWrap(True)
        status_col.addWidget(self.detail_label)
        status_layout.addLayout(status_col, 4)
        layout.addWidget(status_card)

        # Lens ---------------------------------------------------------------
        lens_card = QFrame()
        lens_card.setObjectName("card")
        lens_layout = QVBoxLayout(lens_card)
        lens_layout.setContentsMargins(18, 16, 18, 16)
        lens_layout.setSpacing(10)
        lens_header = QHBoxLayout()
        lens_title = QLabel("Lens")
        lens_title.setObjectName("section")
        lens_header.addWidget(lens_title)
        lens_header.addStretch(1)
        self.freeze_button = QPushButton("Freeze")
        self.freeze_button.setObjectName("ghost")
        self.freeze_button.setCheckable(True)
        self.freeze_button.setToolTip(
            "Freeze the lens in place so you can move your eyes without moving it "
            "(Ctrl+Alt+F)."
        )
        self.freeze_button.toggled.connect(self._toggle_freeze)
        lens_header.addWidget(self.freeze_button)
        self.correct_button = QPushButton("Fix position")
        self.correct_button.setObjectName("ghost")
        self.correct_button.setToolTip(
            "Drag the lens to where you are looking or facing and release; the "
            "model learns that correction (Ctrl+Alt+D)."
        )
        self.correct_button.clicked.connect(self.correct_requested.emit)
        lens_header.addWidget(self.correct_button)
        self.big_button = QPushButton("Big lens")
        self.big_button.setObjectName("ghost")
        self.big_button.setCheckable(True)
        self.big_button.setToolTip(
            "Toggle a large lens sized to the screen (Ctrl+Alt+B)."
        )
        self.big_button.toggled.connect(self._toggle_big_lens)
        lens_header.addWidget(self.big_button)
        self.show_lens = QCheckBox("Show lens")
        self.show_lens.toggled.connect(self._toggle_lens_visible)
        lens_header.addWidget(self.show_lens)
        lens_layout.addLayout(lens_header)

        control_row = QHBoxLayout()
        control_row.setSpacing(12)
        control_label = QLabel("Control")
        control_label.setFixedWidth(84)
        self.control_combo = QComboBox()
        self.control_combo.addItem("Head", "head")
        self.control_combo.addItem("Eyes", "eyes")
        self.control_combo.setToolTip(
            "Head: move or turn your head to move the lens (recommended). "
            "Eyes: follow your gaze. Switching mode requires recalibration. "
            "If no camera is available, the lens automatically follows the "
            "mouse or a finger on the touchscreen."
        )
        self.control_combo.currentIndexChanged.connect(self._on_control_mode)
        control_row.addWidget(control_label)
        control_row.addWidget(self.control_combo, 1)
        lens_layout.addLayout(control_row)

        shape_row = QHBoxLayout()
        shape_row.setSpacing(12)
        shape_label = QLabel("Shape")
        shape_label.setFixedWidth(84)
        self.shape_combo = QComboBox()
        self.shape_combo.addItem("Round", "round")
        self.shape_combo.addItem("Square", "square")
        self.shape_combo.addItem("Wide", "wide")
        self.shape_combo.setToolTip(
            "Lens shape. Wide keeps the chosen height and is 1.6x wider."
        )
        self.shape_combo.currentIndexChanged.connect(self._on_shape)
        shape_row.addWidget(shape_label)
        shape_row.addWidget(self.shape_combo, 1)
        lens_layout.addLayout(shape_row)

        self.size_slider, self.size_value = self._slider_row(
            lens_layout,
            "Size",
            Settings.DIAMETER_RANGE[0],
            Settings.DIAMETER_RANGE[1],
            10,
            "Lens height in pixels; wide lenses are 1.6x wider. "
            "Press Ctrl+Alt+B for a quick big lens.",
        )
        self.zoom_slider, self.zoom_value = self._slider_row(
            lens_layout,
            "Zoom",
            int(Settings.ZOOM_RANGE[0] * 100),
            int(Settings.ZOOM_RANGE[1] * 100),
            5,
            "Magnification of the area under the lens.",
        )
        self.smoothing_slider, self.smoothing_value = self._slider_row(
            lens_layout,
            "Smoothing",
            0,
            100,
            1,
            "Higher = calmer, slower lens movement; lower = faster but more jitter.",
        )
        self.opacity_slider, self.opacity_value = self._slider_row(
            lens_layout,
            "Opacity",
            int(Settings.OPACITY_RANGE[0] * 100),
            int(Settings.OPACITY_RANGE[1] * 100),
            1,
            "Lens opacity.",
        )
        self.size_slider.valueChanged.connect(self._on_size)
        self.zoom_slider.valueChanged.connect(self._on_zoom)
        self.smoothing_slider.valueChanged.connect(self._on_smoothing)
        self.opacity_slider.valueChanged.connect(self._on_opacity)

        options = QHBoxLayout()
        options.setSpacing(18)
        self.ring_checkbox = QCheckBox("Outline")
        self.ring_checkbox.toggled.connect(self._on_ring)
        self.osd_checkbox = QCheckBox("On-screen HUD")
        self.osd_checkbox.toggled.connect(self._on_osd)
        options.addWidget(self.ring_checkbox)
        options.addWidget(self.osd_checkbox)
        options.addStretch(1)
        reset = QPushButton("Reset appearance")
        reset.setObjectName("link")
        reset.clicked.connect(self._reset_appearance)
        options.addWidget(reset)
        lens_layout.addLayout(options)
        layout.addWidget(lens_card)

        # Calibration --------------------------------------------------------
        calibration_card = QFrame()
        calibration_card.setObjectName("card")
        calibration_layout = QVBoxLayout(calibration_card)
        calibration_layout.setContentsMargins(18, 16, 18, 16)
        calibration_layout.setSpacing(9)
        calibration_title = QLabel("Calibration")
        calibration_title.setObjectName("section")
        calibration_layout.addWidget(calibration_title)
        self.calibration_help = QLabel(self._calibration_help_text())
        self.calibration_help.setObjectName("muted")
        self.calibration_help.setWordWrap(True)
        calibration_layout.addWidget(self.calibration_help)
        calibration_actions = QHBoxLayout()
        calibration_actions.setSpacing(10)
        self.calibrate_button = QPushButton("Calibrate now")
        self.calibrate_button.setObjectName("accent")
        self.calibrate_button.clicked.connect(self.calibrate_requested.emit)
        calibration_actions.addWidget(self.calibrate_button)
        calibration_actions.addStretch(1)
        camera_label = QLabel("Camera")
        camera_label.setObjectName("muted")
        calibration_actions.addWidget(camera_label)
        self.camera_spin = QSpinBox()
        self.camera_spin.setRange(0, 9)
        self.camera_spin.setFixedWidth(54)
        self.camera_spin.setToolTip("Webcam index (try 1 if the built-in camera is not 0).")
        calibration_actions.addWidget(self.camera_spin)
        self.restart_camera_button = QPushButton("Apply")
        self.restart_camera_button.setObjectName("ghost")
        self.restart_camera_button.setToolTip("Restart the camera with this index.")
        self.restart_camera_button.clicked.connect(self._restart_camera)
        calibration_actions.addWidget(self.restart_camera_button)
        calibration_layout.addLayout(calibration_actions)
        layout.addWidget(calibration_card)

        # Hotkeys ------------------------------------------------------------
        hotkey_card = QFrame()
        hotkey_card.setObjectName("card")
        hotkey_layout = QVBoxLayout(hotkey_card)
        hotkey_layout.setContentsMargins(18, 14, 18, 16)
        hotkey_layout.setSpacing(8)
        hotkey_title = QLabel("Hotkeys — work anywhere")
        hotkey_title.setObjectName("section")
        hotkey_layout.addWidget(hotkey_title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        rows = [
            ("Ctrl + Alt + L", "Show / hide the lens"),
            ("Ctrl + Alt + F", "Freeze / unfreeze"),
            ("Ctrl + Alt + C", "Calibrate"),
            ("Ctrl + Alt + D", "Correct / drag the lens"),
            ("Ctrl + Alt + B", "Big lens on / off"),
            ("Ctrl + Alt + = / -", "Zoom in / out"),
            ("Ctrl + Alt + ] / [", "Grow / shrink lens"),
        ]
        for index, (keys, description) in enumerate(rows):
            keycap = QLabel(keys)
            keycap.setObjectName("keycap")
            keycap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value = QLabel(description)
            value.setObjectName("muted")
            grid.addWidget(keycap, index, 0)
            grid.addWidget(value, index, 1)
        grid.setColumnStretch(1, 1)
        hotkey_layout.addLayout(grid)
        layout.addWidget(hotkey_card)

        footer = QHBoxLayout()
        privacy = QLabel("Runs fully offline · webcam stays local")
        privacy.setObjectName("muted")
        footer.addWidget(privacy)
        footer.addStretch(1)
        quit_button = QPushButton("Quit eyeLens")
        quit_button.setObjectName("danger")
        quit_button.clicked.connect(self.quit_requested.emit)
        footer.addWidget(quit_button)
        layout.addLayout(footer)
        layout.addStretch(1)

    def _slider_row(
        self,
        layout: QVBoxLayout,
        title: str,
        minimum: int,
        maximum: int,
        step: int,
        tooltip: str,
    ) -> tuple[QSlider, QLabel]:
        row = QHBoxLayout()
        row.setSpacing(12)
        label = QLabel(title)
        label.setFixedWidth(84)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setSingleStep(step)
        slider.setPageStep(step * 5)
        slider.setToolTip(tooltip)
        value = QLabel("—")
        value.setObjectName("value")
        value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        value.setFixedWidth(86)
        row.addWidget(label)
        row.addWidget(slider, 1)
        row.addWidget(value)
        layout.addLayout(row)
        return slider, value

    def _calibration_help_text(self) -> str:
        if self.settings.control_mode == "head":
            return (
                "Aim your head at 25 dots, then 9 accuracy-check dots (about 45 "
                "seconds). Turn or move your head until you are facing each dot, "
                "then hold still. eyeLens learns how your head maps to this "
                "screen and reports the error it measured. Your camera feed "
                "never leaves this computer."
            )
        return (
            "Look at 25 dots, then 9 accuracy-check dots (about 80 seconds). "
            "For each dot, hold still for a moment, then slowly move your head "
            "left and right while keeping your eyes on it. eyeLens learns how "
            "your eyes map to this screen, including head-position changes, and "
            "reports the error it measured. Your camera feed never leaves this "
            "computer."
        )

    def _update_calibration_help(self) -> None:
        if hasattr(self, "calibration_help"):
            self.calibration_help.setText(self._calibration_help_text())

    def _on_control_mode(self, _index: int) -> None:
        if self._syncing:
            return
        mode = str(self.control_combo.currentData() or "head")
        if mode == self.settings.control_mode:
            return
        self.settings.control_mode = mode
        self._update_calibration_help()
        self._commit()

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget#root, QWidget#content {
                background: #070d16;
                color: #dbeafe;
                font-family: "Segoe UI";
                font-size: 10pt;
            }
            QScrollArea { background: transparent; }
            QScrollArea > QWidget > QWidget { background: transparent; }
            QLabel#title {
                font-size: 25px;
                font-weight: 600;
                color: #f0f8ff;
            }
            QLabel#muted { color: #8296ad; font-size: 9pt; }
            QLabel#section {
                font-size: 12pt;
                font-weight: 600;
                color: #e7f2ff;
            }
            QLabel#badge {
                color: #5f7d9c;
                background: #0d1a2a;
                border: 1px solid #1c3149;
                border-radius: 8px;
                padding: 2px 8px;
                font-size: 8pt;
            }
            QLabel#value { color: #b8d4ea; font-size: 9pt; }
            QLabel#keycap {
                background: #0d1928;
                border: 1px solid #21374f;
                border-radius: 6px;
                padding: 3px 8px;
                color: #9fc4e2;
                font-family: "Cascadia Mono", "Consolas";
                font-size: 8pt;
            }
            QFrame#card {
                background: #0b1523;
                border: 1px solid #182a40;
                border-radius: 16px;
            }
            QPushButton {
                background: #112033;
                border: 1px solid #223a55;
                border-radius: 9px;
                padding: 7px 14px;
                color: #d8e8f8;
            }
            QPushButton:hover { background: #172b43; border-color: #2f4d6b; }
            QPushButton:pressed { background: #0d1a2a; }
            QPushButton#accent {
                background: #38bdf8;
                color: #04121f;
                border: 1px solid #38bdf8;
                font-weight: 600;
                padding: 9px 18px;
            }
            QPushButton#accent:hover { background: #7dd3fc; border-color: #7dd3fc; }
            QPushButton#accent:disabled {
                background: #23384b; color: #6c8198; border-color: #23384b;
            }
            QPushButton#ghost { padding: 5px 11px; font-size: 9pt; }
            QPushButton#ghost:checked {
                background: #3a2a0b;
                border-color: #b7791f;
                color: #fbbf24;
            }
            QPushButton#link {
                background: transparent;
                border: none;
                color: #7dd3fc;
                padding: 2px 4px;
                font-size: 9pt;
            }
            QPushButton#link:hover { color: #bae6fd; }
            QPushButton#danger {
                background: transparent;
                border: none;
                color: #fca5a5;
                padding: 6px 4px;
            }
            QPushButton#danger:hover { color: #fecaca; }
            QSlider::groove:horizontal {
                height: 4px;
                background: #17283c;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #0ea5cf;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 15px;
                height: 15px;
                margin: -6px 0;
                border-radius: 7px;
                background: #7dd3fc;
                border: 1px solid #38bdf8;
            }
            QSlider::handle:horizontal:hover { background: #e0f2fe; }
            QCheckBox { color: #a9bed3; spacing: 8px; }
            QCheckBox:hover { color: #dbeafe; }
            QSpinBox {
                background: #0d1928;
                border: 1px solid #223a55;
                border-radius: 7px;
                padding: 3px 6px;
                color: #cfe4f7;
                selection-background-color: #155e75;
            }
            QComboBox {
                background: #0d1928;
                border: 1px solid #223a55;
                border-radius: 7px;
                padding: 3px 6px;
                color: #cfe4f7;
            }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView {
                background: #0b1523;
                color: #dbeafe;
                selection-background-color: #155e75;
            }
            QToolTip {
                background: #0b1523;
                color: #dbeafe;
                border: 1px solid #2b4765;
                padding: 5px;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background: #21374f;
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            """
        )

    # ------------------------------------------------------------------ tracker
    def _bind_tracker(self, tracker: EyeTracker | None) -> None:
        old = self.tracker
        if old is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                old.preview_ready.disconnect(self._on_preview)
        if self._preview_acquired and old is not None:
            old.release_preview()
            self._preview_acquired = False
        self.tracker = tracker
        if tracker is not None:
            tracker.preview_ready.connect(self._on_preview)
            if self.isVisible():
                tracker.acquire_preview()
                self._preview_acquired = True
        else:
            self.preview.set_image(None)

    def set_tracker(self, tracker: EyeTracker | None) -> None:
        self.preview.set_image(None)
        self.preview.set_live(False)
        self._bind_tracker(tracker)
        self.refresh_status()

    def set_engine(self, engine: GazeEngine | None) -> None:
        self.engine = engine

    def _on_preview(self, image: QImage) -> None:
        self.preview.set_image(image)
        self.preview.set_live(True)

    # --------------------------------------------------------------- show/hide
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.tracker is not None and not self._preview_acquired:
            self.tracker.acquire_preview()
            self._preview_acquired = True
        self._status_timer.start()
        self.refresh_status()

    def hideEvent(self, event) -> None:
        self._status_timer.stop()
        if self.tracker is not None and self._preview_acquired:
            self.tracker.release_preview()
            self._preview_acquired = False
        self.preview.set_live(False)
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        if self._closing_for_real:
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()
        self.hidden_to_tray.emit()

    def force_close(self) -> None:
        self._closing_for_real = True
        self.close()

    # ------------------------------------------------------------------ status
    def sync_from_settings(self) -> None:
        self._syncing = True
        try:
            self.size_slider.setValue(self.settings.diameter)
            index = self.shape_combo.findData(self.settings.shape)
            if index >= 0:
                self.shape_combo.setCurrentIndex(index)
            self.zoom_slider.setValue(int(round(self.settings.zoom * 100)))
            self.smoothing_slider.setValue(int(round(self.settings.smoothing * 100)))
            self.opacity_slider.setValue(int(round(self.settings.opacity * 100)))
            self.ring_checkbox.setChecked(self.settings.show_ring)
            self.osd_checkbox.setChecked(self.settings.show_osd)
            self.show_lens.setChecked(self.settings.lens_visible)
            self.camera_spin.setValue(self.settings.camera_index)
            control_index = self.control_combo.findData(self.settings.control_mode)
            if control_index >= 0:
                self.control_combo.setCurrentIndex(control_index)
            self._update_value_labels()
            self._update_calibration_help()
        finally:
            self._syncing = False

    def refresh_status(self) -> None:
        info = self.status_provider() if self.status_provider else StatusInfo()
        self.camera_status.set_status(info.camera_text, info.camera_level)
        self.gaze_status.set_status(info.gaze_text, info.gaze_level)
        self.calibration_status.set_status(
            info.calibration_text, info.calibration_level
        )
        self.detail_label.setText(info.calibration_detail)
        self.calibrate_button.setEnabled(info.can_calibrate)
        self.correct_button.setEnabled(info.can_correct)
        self.big_button.setEnabled(info.can_big)
        self.calibrate_button.setText(
            "Calibrate now"
            if info.calibration_text in ("Not calibrated", "Pointer mode")
            else "Recalibrate"
        )
        self.camera_spin.setEnabled(not info.demo)
        self.restart_camera_button.setEnabled(not info.demo)
        self._syncing = True
        try:
            self.show_lens.setChecked(self.settings.lens_visible)
            self.freeze_button.setChecked(info.locked)
        finally:
            self._syncing = False
        if info.demo:
            self.preview.set_placeholder("Mouse demo — camera off")
            self.preview.set_live(False)
            self.preview.set_image(None)
        elif self.tracker is None:
            self.preview.set_placeholder("Camera off")
            self.preview.set_live(False)
            self.preview.set_image(None)
        elif self.tracker.error_text:
            self.preview.set_placeholder("Camera error")
            self.preview.set_live(False)
            self.preview.set_image(None)
        elif not self.tracker.isRunning():
            self.preview.set_placeholder("Camera stopped")
            self.preview.set_live(False)
            self.preview.set_image(None)
        elif not self.tracker.is_ready:
            self.preview.set_placeholder("Starting camera…")
            self.preview.set_live(False)
            self.preview.set_image(None)
        else:
            self.preview.set_placeholder("Starting camera…")

    def set_locked(self, locked: bool) -> None:
        self._syncing = True
        try:
            self.freeze_button.setChecked(locked)
        finally:
            self._syncing = False

    def set_big_lens(self, active: bool) -> None:
        self._syncing = True
        try:
            self.big_button.setChecked(active)
        finally:
            self._syncing = False

    # ----------------------------------------------------------------- controls
    def _commit(self) -> None:
        self.settings.normalized()
        self._update_value_labels()
        self.settings_changed.emit()

    def _update_value_labels(self) -> None:
        width, height = lens_dimensions(
            self.settings.shape, self.settings.diameter
        )
        self.size_value.setText(
            f"{width}×{height} px"
            if self.settings.shape == "wide"
            else f"{height} px"
        )
        self.zoom_value.setText(f"{self.settings.zoom:.2f}×")
        smoothing = self.settings.smoothing
        if smoothing < 0.25:
            smoothing_text = "Fast"
        elif smoothing < 0.55:
            smoothing_text = "Balanced"
        elif smoothing < 0.80:
            smoothing_text = "Smooth"
        else:
            smoothing_text = "Very smooth"
        self.smoothing_value.setText(smoothing_text)
        self.opacity_value.setText(f"{int(round(self.settings.opacity * 100))}%")
        self.zoom_slider.setToolTip(
            f"Magnification: {self.settings.zoom:.2f}× of the area under the lens."
        )

    def _on_size(self, value: int) -> None:
        if self._syncing:
            return
        self.settings.diameter = int(value)
        self._commit()

    def _on_shape(self, _index: int) -> None:
        if self._syncing:
            return
        shape = self.shape_combo.currentData()
        self.settings.shape = str(shape)
        self._commit()

    def _on_zoom(self, value: int) -> None:
        if self._syncing:
            return
        self.settings.zoom = round(value / 100.0, 2)
        self._commit()

    def _on_smoothing(self, value: int) -> None:
        if self._syncing:
            return
        self.settings.smoothing = value / 100.0
        self._commit()

    def _on_opacity(self, value: int) -> None:
        if self._syncing:
            return
        self.settings.opacity = value / 100.0
        self._commit()

    def _on_ring(self, checked: bool) -> None:
        if self._syncing:
            return
        self.settings.show_ring = bool(checked)
        self._commit()

    def _on_osd(self, checked: bool) -> None:
        if self._syncing:
            return
        self.settings.show_osd = bool(checked)
        self._commit()

    def _toggle_lens_visible(self, checked: bool) -> None:
        if self._syncing:
            return
        self.settings.lens_visible = bool(checked)
        self._commit()

    def _toggle_freeze(self, checked: bool) -> None:
        if self._syncing:
            return
        self.freeze_requested.emit()

    def _toggle_big_lens(self, checked: bool) -> None:
        if self._syncing:
            return
        self.big_lens_requested.emit()

    def _restart_camera(self) -> None:
        self.camera_restart_requested.emit(int(self.camera_spin.value()))

    def _reset_appearance(self) -> None:
        defaults = Settings()
        self._syncing = True
        try:
            self.size_slider.setValue(defaults.diameter)
            index = self.shape_combo.findData(defaults.shape)
            if index >= 0:
                self.shape_combo.setCurrentIndex(index)
            self.zoom_slider.setValue(int(defaults.zoom * 100))
            self.smoothing_slider.setValue(int(defaults.smoothing * 100))
            self.opacity_slider.setValue(int(defaults.opacity * 100))
            self.ring_checkbox.setChecked(defaults.show_ring)
            self.osd_checkbox.setChecked(defaults.show_osd)
        finally:
            self._syncing = False
        self.settings.diameter = defaults.diameter
        self.settings.shape = defaults.shape
        self.settings.zoom = defaults.zoom
        self.settings.smoothing = defaults.smoothing
        self.settings.opacity = defaults.opacity
        self.settings.show_ring = defaults.show_ring
        self.settings.show_osd = defaults.show_osd
        self._commit()

    # ------------------------------------------------------------------- window
    def show_window(self) -> None:
        if not self._positioned:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                available = screen.availableGeometry()
                height = min(960, max(620, available.height() - 40))
                width = min(640, max(600, available.width() - 40))
                self.resize(width, height)
                x = available.center().x() - width // 2
                y = available.center().y() - height // 2
                x = max(available.left(), min(x, available.right() - width))
                y = max(available.top(), min(y, available.bottom() - height))
                self.move(x, y)
            self._positioned = True
        self.show()
        self.setWindowState(
            self.windowState() & ~Qt.WindowState.WindowMinimized
            | Qt.WindowState.WindowActive
        )
        self.raise_()
        self.activateWindow()
