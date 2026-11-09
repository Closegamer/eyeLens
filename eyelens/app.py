"""Application controller: camera, calibration, overlay, tray and hotkeys."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import os
import platform
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QAction, QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from . import __version__
from .capture import ScreenCapture
from .config import (
    ScreenInfo,
    Settings,
    calibration_path,
    ensure_model_path,
    find_model_path,
)
from .gaze.engine import GazeEngine
from .gaze.model import GazeModel
from .gaze.tracker import EyeTracker
from .hotkeys import HotkeyManager
from .ui.calibration_window import CalibrationWindow
from .ui.icon import make_icon
from .ui.overlay import LensOverlay, screen_info
from .ui.settings_window import SettingsWindow, StatusInfo


class EyeLensApp(QObject):
    def __init__(
        self,
        app: QApplication,
        model_path: Path | None,
        demo: bool = False,
        show_settings: bool = False,
        smoke_test: bool = False,
    ) -> None:
        super().__init__()
        self.app = app
        self.demo = bool(demo)
        self.model_path = model_path
        self.smoke_test = smoke_test
        self.force_settings = show_settings
        self._quitting = False
        self._settings_visible_once = False
        self._tray_notice_shown = False
        self._calibration_invalid = False
        self._screen_change_pending = False
        self._correction_target: tuple[float, float] | None = None
        self._correction_release_at = 0.0
        self._correction_pending = False

        self.settings = Settings.load()
        self.screen = QGuiApplication.primaryScreen()
        if self.screen is None:
            raise RuntimeError("No screen available")
        self.screen_data = screen_info(self.screen)
        self.model = self._load_calibration()
        self.calibration_window: CalibrationWindow | None = None

        self.tracker = self._create_tracker() if not self.demo else None
        self.engine = GazeEngine(
            self.screen_data,
            tracker=self.tracker,
            demo=self.demo,
            settings=self.settings,
            parent=self,
        )
        self.engine.set_model(self.model)
        self.capture = ScreenCapture(self.screen_data, parent=self)
        self.capture.error.connect(self._on_capture_error)
        self.capture.start()
        self.overlay = LensOverlay(
            self.screen, self.engine, self.capture, self.settings, parent=None
        )
        self.overlay.screen_changed.connect(self._schedule_screen_change)
        self.overlay.correction_committed.connect(self._on_correction_committed)
        self.overlay.correction_cancelled.connect(self._on_correction_cancelled)
        self.settings_window = SettingsWindow(
            self.settings, tracker=self.tracker, engine=self.engine
        )
        self.settings_window.status_provider = self._status_info
        self.settings_window.settings_changed.connect(self._on_settings_changed)
        self.settings_window.calibrate_requested.connect(self.start_calibration)
        self.settings_window.freeze_requested.connect(self.toggle_freeze)
        self.settings_window.camera_restart_requested.connect(self._restart_camera)
        self.settings_window.correct_requested.connect(self.correct_lens)
        self.settings_window.quit_requested.connect(self.quit)
        self.settings_window.hidden_to_tray.connect(self._on_hidden_to_tray)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(450)
        self._save_timer.timeout.connect(self._save_settings)
        self._screen_timer = QTimer(self)
        self._screen_timer.setSingleShot(True)
        self._screen_timer.setInterval(350)
        self._screen_timer.timeout.connect(self._handle_screen_change)
        self._correction_timer = QTimer(self)
        self._correction_timer.setSingleShot(True)
        self._correction_timer.setInterval(650)
        self._correction_timer.timeout.connect(self._learn_correction)

        self._build_tray()
        self._hotkeys = HotkeyManager(self)
        self._hotkeys.toggle_lens.connect(self.toggle_lens)
        self._hotkeys.toggle_freeze.connect(self.toggle_freeze)
        self._hotkeys.calibrate.connect(self.start_calibration)
        self._hotkeys.correct_lens.connect(self.correct_lens)
        self._hotkeys.zoom_in.connect(lambda: self.adjust_zoom(0.25))
        self._hotkeys.zoom_out.connect(lambda: self.adjust_zoom(-0.25))
        self._hotkeys.size_up.connect(lambda: self.adjust_size(20))
        self._hotkeys.size_down.connect(lambda: self.adjust_size(-20))
        self._hotkeys.error.connect(self._on_hotkey_error)
        self._hotkeys.start()

        if self.tracker is not None:
            self.tracker.start()
        self._sync_tray_menu()

        if self.demo or self.model is not None:
            self.overlay.show()
            self.overlay.raise_()
            if self.tracker is not None:
                QTimer.singleShot(1500, self._maybe_tray_notice)
        if self.model is None or self.force_settings or self.demo or self.smoke_test:
            self._show_settings()
        if self.smoke_test:
            QTimer.singleShot(2600, self.quit)

    # --------------------------------------------------------------- setup
    def _load_calibration(self) -> GazeModel | None:
        path = calibration_path()
        if not path.exists():
            return None
        model = GazeModel.load(path)
        if model is None:
            print(
                "eyeLens: existing calibration is from an older eyeLens version "
                "or is damaged; recalibration required.",
                file=sys.stderr,
            )
            return None
        try:
            calibrated_screen = ScreenInfo.from_dict(model.screen)
        except (TypeError, ValueError):
            self._calibration_invalid = True
            return None
        if not calibrated_screen.matches(self.screen_data):
            self._calibration_invalid = True
            print(
                "eyeLens: existing calibration is for a different screen; "
                "recalibration required.",
                file=sys.stderr,
            )
            return None
        return model

    def _create_tracker(self, camera_index: int | None = None) -> EyeTracker:
        index = self.settings.camera_index if camera_index is None else camera_index
        tracker = EyeTracker(self.model_path, camera_index=index, parent=self)
        tracker.error.connect(self._on_tracker_error)
        return tracker

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.setToolTip("eyeLens")
        menu = QMenu()
        self._tray_status = QAction("Not calibrated", menu)
        self._tray_status.setEnabled(False)
        menu.addAction(self._tray_status)
        menu.addSeparator()

        self._tray_calibrate = QAction("Calibrate…", menu)
        self._tray_calibrate.triggered.connect(self.start_calibration)
        menu.addAction(self._tray_calibrate)

        self._tray_settings = QAction("Open eyeLens", menu)
        self._tray_settings.triggered.connect(self._show_settings)
        menu.addAction(self._tray_settings)
        menu.addSeparator()

        self._tray_show_lens = QAction("Show lens", menu)
        self._tray_show_lens.setCheckable(True)
        self._tray_show_lens.triggered.connect(self.toggle_lens)
        menu.addAction(self._tray_show_lens)

        self._tray_freeze = QAction("Freeze lens", menu)
        self._tray_freeze.setCheckable(True)
        self._tray_freeze.triggered.connect(self.toggle_freeze)
        menu.addAction(self._tray_freeze)

        self._tray_correct = QAction("Correct lens position…", menu)
        self._tray_correct.triggered.connect(self.correct_lens)
        menu.addAction(self._tray_correct)
        menu.addSeparator()

        self._tray_zoom_in = QAction("Zoom in", menu)
        self._tray_zoom_in.triggered.connect(lambda: self.adjust_zoom(0.25))
        menu.addAction(self._tray_zoom_in)
        self._tray_zoom_out = QAction("Zoom out", menu)
        self._tray_zoom_out.triggered.connect(lambda: self.adjust_zoom(-0.25))
        menu.addAction(self._tray_zoom_out)
        self._tray_size_up = QAction("Larger lens", menu)
        self._tray_size_up.triggered.connect(lambda: self.adjust_size(20))
        menu.addAction(self._tray_size_up)
        self._tray_size_down = QAction("Smaller lens", menu)
        self._tray_size_down.triggered.connect(lambda: self.adjust_size(-20))
        menu.addAction(self._tray_size_down)
        menu.addSeparator()

        quit_action = QAction("Quit eyeLens", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        menu.aboutToShow.connect(self._sync_tray_menu)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            print(
                "eyeLens: no system tray available; use the settings window.",
                file=sys.stderr,
            )

    # --------------------------------------------------------------- status
    def _status_info(self) -> StatusInfo:
        info = StatusInfo()
        info.demo = self.demo
        info.lens_visible = self.settings.lens_visible
        info.locked = self.overlay.locked if hasattr(self, "overlay") else False
        if self.demo:
            info.camera_text = "Mouse demo"
            info.camera_level = "accent"
            info.gaze_text = "Mouse pointer"
            info.gaze_level = "accent"
            info.calibration_text = "Demo mode"
            info.calibration_level = "muted"
            info.calibration_detail = (
                "Demo mode: the lens follows the mouse. Start without --demo "
                "to use eye tracking."
            )
            info.can_calibrate = False
            info.can_correct = False
            return info

        tracker = self.tracker
        if tracker is None:
            info.camera_text = "Unavailable"
            info.camera_level = "bad"
        elif tracker.error_text:
            info.camera_text = "Camera error"
            info.camera_level = "bad"
        elif not tracker.isRunning() or not tracker.is_ready:
            info.camera_text = "Starting…"
            info.camera_level = "warn"
        else:
            fps = tracker.snapshot().fps
            info.camera_text = (
                f"Running · {fps:.0f} fps" if fps > 0 else "Running"
            )
            info.camera_level = "ok"

        state = self.engine.state_text()
        info.gaze_text = state
        info.gaze_level = {
            "Tracking": "ok",
            "Mouse demo": "accent",
            "Face not found": "warn",
            "Eyes closed": "warn",
            "Reacquiring…": "warn",
            "Not calibrated": "bad",
            "Camera error": "bad",
            "Camera off": "bad",
        }.get(state, "muted")

        if self.model is not None:
            info.calibration_text = self.model.summary()
            info.calibration_level = (
                "ok" if self.model.quality_ok else "warn"
            )
            label = (
                "Initial accuracy"
                if self.model.metrics.corrections
                else "Accuracy"
            )
            detail = (
                f"{label} ±{self.model.error_rmse:.0f} px · "
                f"{self.model.metrics.n_points} points · "
                f"{self.model.metrics.n_samples} samples."
            )
            camera_used = self.model.screen.get("camera_index")
            if camera_used is not None and int(camera_used) != int(
                self.settings.camera_index
            ):
                detail += (
                    f" Calibrated with camera {camera_used}; recalibrate if "
                    "accuracy drops."
                )
            info.calibration_detail = detail
            info.can_calibrate = (
                tracker is not None
                and tracker.isRunning()
                and tracker.is_ready
                and not tracker.error_text
            )
            info.can_correct = info.can_calibrate
        else:
            info.calibration_text = "Not calibrated"
            info.calibration_level = "bad"
            if self._calibration_invalid:
                info.calibration_detail = (
                    "The display or screen layout changed. Calibrate again for "
                    "this screen."
                )
            elif tracker is not None and tracker.error_text:
                info.calibration_detail = tracker.error_text
            else:
                info.calibration_detail = (
                    "Look at 25 dots plus 9 accuracy-check dots for about 50 "
                    "seconds to teach eyeLens how your eyes map to this screen."
                )
            info.can_calibrate = (
                tracker is not None
                and tracker.isRunning()
                and tracker.is_ready
                and not tracker.error_text
            )
            info.can_correct = False
        return info

    def _sync_tray_menu(self) -> None:
        info = self._status_info()
        self._tray_status.setText(
            f"{info.calibration_text}  ·  {info.gaze_text}"
            if info.calibration_text != "Not calibrated"
            else "Not calibrated"
        )
        self._tray_show_lens.setChecked(self.settings.lens_visible)
        self._tray_freeze.setChecked(self.overlay.locked)
        available = self.demo or self.model is not None
        self._tray_correct.setEnabled(info.can_correct)
        self._tray_zoom_in.setEnabled(available)
        self._tray_zoom_out.setEnabled(available)
        self._tray_size_up.setEnabled(available)
        self._tray_size_down.setEnabled(available)
        self._tray_calibrate.setEnabled(info.can_calibrate)
        self.tray.setToolTip(f"eyeLens — {info.calibration_text}")
        self.settings_window.set_locked(self.overlay.locked)

    # -------------------------------------------------------------- settings
    def _on_settings_changed(self) -> None:
        self.settings.normalized()
        if not self.settings.lens_visible and self.overlay.correction_active:
            self.overlay.cancel_correction()
        self.engine.apply_settings(self.settings)
        self.overlay.apply_settings(self.settings)
        self._save_timer.start()
        self._sync_tray_menu()

    def _save_settings(self) -> None:
        try:
            self.settings.save()
        except OSError as exc:
            print(f"eyeLens: could not save settings: {exc}", file=sys.stderr)

    def _show_settings(self) -> None:
        self._settings_visible_once = True
        self.settings_window.show_window()

    def _on_hidden_to_tray(self) -> None:
        if not self._tray_notice_shown and QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_notice_shown = True
            self.tray.showMessage(
                "eyeLens is still running",
                "Use the tray icon or Ctrl+Alt+L to show the lens.",
                QSystemTrayIcon.MessageIcon.Information,
                3500,
            )

    # -------------------------------------------------------------- controls
    def toggle_lens(self) -> None:
        if not self.demo and self.model is None:
            self._notify("Calibrate first", "Calibrate eyeLens before showing the lens.")
            return
        self.settings.lens_visible = not self.settings.lens_visible
        if not self.settings.lens_visible and self.overlay.correction_active:
            self.overlay.cancel_correction()
        if self.settings.lens_visible:
            if not self.overlay.isVisible():
                self.overlay.show()
            self.overlay.raise_()
        self.engine.apply_settings(self.settings)
        self.overlay.apply_settings(self.settings)
        self.settings_window.sync_from_settings()
        self._save_timer.start()
        self._sync_tray_menu()
        if self.settings.lens_visible:
            self.overlay.flash_osd("Lens on")

    def toggle_freeze(self) -> None:
        if not self.demo and self.model is None:
            self._notify("Calibrate first", "The freeze control needs a calibrated lens.")
            return
        self.overlay.toggle_locked()
        self.settings_window.set_locked(self.overlay.locked)
        self._sync_tray_menu()

    # --------------------------------------------------- mouse correction
    def correct_lens(self) -> None:
        """Let the user drag the lens to the right spot; the model learns it."""
        if self.demo:
            self._notify("Demo mode", "Correction is unavailable in mouse demo mode.")
            return
        if self.model is None:
            self._notify("Calibrate first", "Calibrate eyeLens before correcting it.")
            return
        if self.calibration_window is not None:
            self._notify(
                "Calibration running",
                "Finish the current calibration before correcting the lens.",
            )
            return
        if self.overlay.correction_active:
            self.overlay.cancel_correction()
            return
        if self._correction_pending:
            self._notify(
                "Still learning",
                "Wait a moment for the previous correction to finish.",
            )
            return
        if self.tracker is None or not self.tracker.isRunning():
            self._notify("Camera unavailable", "The camera is not running.")
            return
        if not self.tracker.is_ready:
            self._notify(
                "Camera starting", "Wait a moment for the camera, then try again."
            )
            return
        if self.tracker.error_text:
            self._notify("Camera error", self.tracker.error_text, warning=True)
            return
        if not self.settings.lens_visible:
            self.settings.lens_visible = True
            self.engine.apply_settings(self.settings)
            self.overlay.apply_settings(self.settings)
            self.settings_window.sync_from_settings()
            self._save_timer.start()
            self._sync_tray_menu()
        if not self.overlay.begin_correction():
            self._notify("Correction unavailable", "The lens is busy.")
            return
        self._notify(
            "Correct lens position",
            "Drag the handle to where you are looking, then release. "
            "The lens learns that spot.",
        )

    def _on_correction_committed(self, x: float, y: float) -> None:
        if self._quitting:
            return
        if self.model is None or self.tracker is None:
            self.overlay.finish_correction(False)
            return
        self._correction_target = (float(x), float(y))
        self._correction_release_at = time.monotonic()
        self._correction_pending = True
        self._correction_timer.start()

    def _on_correction_cancelled(self) -> None:
        self._correction_timer.stop()
        self._correction_pending = False
        self._correction_target = None
        self.settings_window.refresh_status()

    def _learn_correction(self) -> None:
        self._correction_timer.stop()
        if self._quitting or not self._correction_pending:
            return
        self._correction_pending = False
        target = self._correction_target
        self._correction_target = None
        if target is None or self.model is None or self.tracker is None:
            self.overlay.finish_correction(False)
            return
        features = self.tracker.recent_features(
            seconds=0.5, since=self._correction_release_at
        )
        if features is None:
            self.overlay.finish_correction(False)
            self._notify(
                "Correction not learned",
                "Keep your face visible and your eyes on the lens, then try again.",
                warning=True,
            )
            return
        try:
            new_model = self.model.with_correction(features, target)
        except (ValueError, FloatingPointError) as exc:
            print(f"eyeLens: correction failed: {exc}", file=sys.stderr)
            self.overlay.finish_correction(False)
            self._notify("Correction failed", str(exc), warning=True)
            return
        self.model = new_model
        self.engine.set_model(new_model, reset=False)
        self.engine.recenter(target[0], target[1])
        try:
            new_model.save(calibration_path())
        except OSError as exc:
            print(f"eyeLens: could not save correction: {exc}", file=sys.stderr)
            self._notify("Could not save correction", str(exc), warning=True)
        self.overlay.finish_correction(True)
        self.settings_window.refresh_status()
        self._sync_tray_menu()
        self._notify(
            "Correction learned",
            "The lens learned this spot. Press Ctrl+Alt+D again for another area.",
        )

    def adjust_zoom(self, delta: float) -> None:
        if not self.demo and self.model is None:
            return
        self.settings.zoom = round(
            max(
                Settings.ZOOM_RANGE[0],
                min(Settings.ZOOM_RANGE[1], self.settings.zoom + delta),
            ),
            2,
        )
        self.engine.apply_settings(self.settings)
        self.overlay.apply_settings(self.settings)
        self.settings_window.sync_from_settings()
        self._save_timer.start()
        self._sync_tray_menu()

    def adjust_size(self, delta: int) -> None:
        if not self.demo and self.model is None:
            return
        low, high = Settings.DIAMETER_RANGE
        self.settings.diameter = int(
            max(low, min(high, self.settings.diameter + delta))
        )
        self.engine.apply_settings(self.settings)
        self.overlay.apply_settings(self.settings)
        self.settings_window.sync_from_settings()
        self._save_timer.start()
        self._sync_tray_menu()

    # ----------------------------------------------------------- calibration
    def start_calibration(self) -> None:
        if self.demo:
            self._notify("Demo mode", "Calibration is unavailable in mouse demo mode.")
            return
        if self.tracker is None:
            self._notify("Camera unavailable", "The camera is not running.")
            return
        if self.model_path is None:
            self._notify(
                "Tracking model missing",
                "Restart eyeLens so it can download the face tracking model.",
            )
            return
        if self.tracker.error_text:
            self._notify("Camera error", self.tracker.error_text)
            return
        if not self.tracker.isRunning():
            self._notify("Camera starting", "Wait a moment for the camera to start.")
            return
        if not self.tracker.is_ready:
            self._notify(
                "Camera starting",
                "The webcam is still starting. Try again in a moment.",
            )
            return
        if self.calibration_window is not None:
            self.calibration_window.raise_()
            self.calibration_window.activateWindow()
            return

        self.overlay.hide()
        try:
            window = CalibrationWindow(self.tracker, self.screen)
        except Exception as exc:  # pragma: no cover
            print(f"eyeLens: could not open calibration: {exc}", file=sys.stderr)
            self._notify("Calibration error", str(exc))
            self._restore_overlay_after_calibration()
            return
        self.calibration_window = window
        self.tracker.preview_ready.connect(window.set_preview)
        window.finished.connect(self._on_calibration_finished)
        window.cancelled.connect(self._on_calibration_cancelled)
        window.setGeometry(self.screen.geometry())
        window.showFullScreen()
        window.raise_()
        window.activateWindow()
        window.setFocus()

    def _detach_calibration(self, window: CalibrationWindow) -> None:
        self.calibration_window = None
        with contextlib.suppress(RuntimeError, TypeError):
            self.tracker.preview_ready.disconnect(window.set_preview)

    def _on_calibration_finished(self, model: GazeModel) -> None:
        window = self.calibration_window
        if window is not None:
            self._detach_calibration(window)
        if self._quitting:
            return
        model.screen["camera_index"] = int(self.settings.camera_index)
        try:
            model.save(calibration_path())
        except OSError as exc:
            print(f"eyeLens: could not save calibration: {exc}", file=sys.stderr)
            self._notify("Could not save calibration", str(exc))
        self.model = model
        self._calibration_invalid = False
        self.engine.screen = self.screen_data
        self.engine.set_model(model)
        self.settings.lens_visible = True
        self.overlay.apply_settings(self.settings)
        if not self.overlay.isVisible():
            self.overlay.show()
        self.overlay.raise_()
        self.overlay.flash_osd(
            f"Calibrated · ±{model.error_rmse:.0f} px", duration=2.0
        )
        self.settings_window.sync_from_settings()
        self.settings_window.refresh_status()
        self._sync_tray_menu()
        self._save_settings()
        self._notify(
            "Calibration complete",
            f"Accuracy: ±{model.error_rmse:.0f} px. The lens now follows your eyes.",
        )
        if self._settings_visible_once:
            self.settings_window.show_window()

    def _on_calibration_cancelled(self) -> None:
        window = self.calibration_window
        if window is not None:
            self._detach_calibration(window)
        if self._quitting:
            return
        self._restore_overlay_after_calibration()
        self.settings_window.refresh_status()

    def _restore_overlay_after_calibration(self) -> None:
        if self.demo or self.model is not None:
            if not self.overlay.isVisible():
                self.overlay.show()
            self.overlay.raise_()
        if self._settings_visible_once:
            self.settings_window.show_window()

    # --------------------------------------------------------------- camera
    def _restart_camera(self, index: int) -> None:
        if self.demo:
            return
        if self.overlay.correction_active:
            self.overlay.cancel_correction()
        index = max(0, min(9, int(index)))
        self.settings.camera_index = index
        self._save_settings()
        if self.calibration_window is not None:
            return
        if self.tracker is not None:
            self.tracker.stop_and_wait()
            self.tracker.deleteLater()
        self.tracker = self._create_tracker(index)
        self.engine.tracker = self.tracker
        self.engine.set_model(self.model)
        self.settings_window.set_tracker(self.tracker)
        self.tracker.start()
        self.settings_window.refresh_status()
        self._sync_tray_menu()
        self._notify("Camera restarted", f"Using camera {index}.")

    def _on_tracker_error(self, message: str) -> None:
        print(f"eyeLens camera: {message}", file=sys.stderr)
        if self._quitting:
            return
        self._notify("Camera error", message, warning=True)
        self.settings_window.refresh_status()

    def _on_capture_error(self, message: str) -> None:
        print(f"eyeLens capture: {message}", file=sys.stderr)

    def _on_hotkey_error(self, message: str) -> None:
        print(f"eyeLens hotkeys: {message}", file=sys.stderr)

    # -------------------------------------------------------------- screens
    def _schedule_screen_change(self) -> None:
        if self._quitting:
            return
        self._screen_timer.start()

    def _handle_screen_change(self) -> None:
        if self._quitting:
            return
        if self._screen_change_pending:
            return
        self._screen_change_pending = True
        try:
            new_info = screen_info(self.screen)
            self.screen_data = new_info
            self.engine.screen = new_info
            old_capture = self.capture
            old_capture.stop_and_wait()
            new_capture = ScreenCapture(new_info, parent=self)
            new_capture.error.connect(self._on_capture_error)
            new_capture.start()
            self.capture = new_capture
            self.overlay.set_capture(new_capture)
            if self.model is not None:
                calibrated = ScreenInfo.from_dict(self.model.screen)
                if not calibrated.matches(new_info):
                    self.model = None
                    self._calibration_invalid = True
                    self.engine.set_model(None)
                    self.overlay.hide()
                    self._notify(
                        "Display changed",
                        "Recalibrate eyeLens for the new display layout.",
                        warning=True,
                    )
                    self._show_settings()
            self.settings_window.refresh_status()
        finally:
            self._screen_change_pending = False

    def _on_primary_screen_changed(self, screen) -> None:
        if screen is not None and screen is not self.screen:
            self._notify(
                "Main display changed",
                "Restart eyeLens to use the new primary display.",
                warning=True,
            )

    # ---------------------------------------------------------------- tray
    def _on_tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_settings()

    def _maybe_tray_notice(self) -> None:
        if self._quitting or self._tray_notice_shown:
            return
        if QSystemTrayIcon.isSystemTrayAvailable() and not self.settings_window.isVisible():
            self._tray_notice_shown = True
            self.tray.showMessage(
                "eyeLens is running",
                "Ctrl+Alt+L shows or hides the lens. Find eyeLens in the tray.",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )

    def _notify(self, title: str, message: str, warning: bool = False) -> None:
        if warning and self.settings_window.isVisible():
            QMessageBox.warning(self.settings_window, title, message)
            return
        if QSystemTrayIcon.isSystemTrayAvailable() and self.tray.isVisible():
            self.tray.showMessage(
                title,
                message,
                QSystemTrayIcon.MessageIcon.Warning
                if warning
                else QSystemTrayIcon.MessageIcon.Information,
                4500,
            )
        else:
            print(f"eyeLens [{title}]: {message}", file=sys.stderr)

    # ----------------------------------------------------------------- quit
    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self._save_timer.stop()
        self._screen_timer.stop()
        self._correction_timer.stop()
        self._correction_pending = False
        self._correction_target = None
        if self.overlay.correction_active:
            self.overlay.cancel_correction()
        self._save_settings()
        with contextlib.suppress(Exception):
            self._hotkeys.stop()
        if self.calibration_window is not None:
            with contextlib.suppress(Exception):
                self.calibration_window.close()
            self.calibration_window = None
        if self.tracker is not None:
            self.tracker.stop_and_wait()
        if self.capture is not None:
            self.capture.stop_and_wait()
        with contextlib.suppress(Exception):
            self.overlay.close()
        self.settings_window.force_close()
        self.tray.hide()
        self.app.quit()


def _apply_palette(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#070d16"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#dbeafe"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#0b1523"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#0d1928"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#0b1523"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#e2e8f0"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#dbeafe"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#112033"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#dbeafe"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#f87171"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#0ea5e9"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#04121f"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#38bdf8"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#5f7d9c"))
    app.setPalette(palette)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="eyeLens",
        description="A webcam-controlled magnifying lens overlay.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Follow the mouse instead of the eyes (no camera required).",
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=None,
        help="Webcam index (default: last saved value).",
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help="Open the settings window even when a calibration exists.",
    )
    parser.add_argument(
        "--reset-calibration",
        action="store_true",
        help="Delete the saved calibration and start fresh.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Path to a MediaPipe face_landmarker.task file.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--version", action="version", version=f"eyeLens {__version__}")
    args = parser.parse_args(argv)

    if args.model:
        os.environ["EYELENS_MODEL"] = str(Path(args.model).expanduser())

    if platform.system() == "Windows":
        with contextlib.suppress(Exception):
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "eyeLens.Desktop.0.1"
            )

    demo = bool(args.demo or args.smoke_test)
    if args.reset_calibration:
        try:
            calibration_path().unlink()
            print("eyeLens: calibration removed.")
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"eyeLens: could not remove calibration: {exc}", file=sys.stderr)

    app = QApplication([sys.argv[0]])
    app.setApplicationName("eyeLens")
    app.setApplicationDisplayName("eyeLens")
    app.setOrganizationName("eyeLens")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(make_icon())
    _apply_palette(app)

    model_path: Path | None = None
    if not demo:
        try:
            model_path = ensure_model_path()
        except Exception as exc:
            print(
                f"eyeLens: could not prepare the face tracking model: {exc}",
                file=sys.stderr,
            )
            model_path = find_model_path()

    try:
        controller = EyeLensApp(
            app,
            model_path=model_path,
            demo=demo,
            show_settings=bool(args.settings),
            smoke_test=bool(args.smoke_test),
        )
    except Exception as exc:
        print(f"eyeLens: failed to start: {exc}", file=sys.stderr)
        QMessageBox.critical(None, "eyeLens", f"eyeLens failed to start:\n\n{exc}")
        return 1

    if model_path is not None:
        controller.model_path = model_path

    if (
        args.camera is not None
        and not demo
        and int(args.camera) != int(controller.settings.camera_index)
    ):
        QTimer.singleShot(0, lambda: controller._restart_camera(int(args.camera)))

    app.primaryScreenChanged.connect(controller._on_primary_screen_changed)
    return int(app.exec())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
