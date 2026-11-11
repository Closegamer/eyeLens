"""Application paths, persisted settings and calibration storage."""

from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir, user_data_dir

APP_NAME = "eyeLens"
MODEL_FILE_NAME = "face_landmarker.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
MODEL_SIZE_HINT = 3_758_596


def config_dir() -> Path:
    path = Path(user_config_dir(APP_NAME, appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    path = Path(user_data_dir(APP_NAME, appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return config_dir() / "settings.json"


def calibration_path() -> Path:
    return config_dir() / "calibration.json"


def _repo_root() -> Path | None:
    """Return the checkout root when running from source."""
    candidate = Path(__file__).resolve().parent.parent
    if (candidate / "pyproject.toml").exists():
        return candidate
    return None


def model_search_paths() -> list[Path]:
    paths: list[Path] = []
    env = os.environ.get("EYELENS_MODEL")
    if env:
        paths.append(Path(env).expanduser())
    root = _repo_root()
    if root is not None:
        paths.append(root / "models" / MODEL_FILE_NAME)
    paths.append(data_dir() / "models" / MODEL_FILE_NAME)
    return paths


def find_model_path() -> Path | None:
    for path in model_search_paths():
        if path.is_file() and path.stat().st_size > 1_000_000:
            return path
    return None


def download_model(destination: Path | None = None) -> Path:
    """Download the MediaPipe face landmarker model atomically."""
    target = destination or (data_dir() / "models" / MODEL_FILE_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".face_landmarker_", suffix=".task", dir=target.parent
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response, tmp.open(
            "wb"
        ) as handle:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                handle.write(chunk)
        if tmp.stat().st_size < 1_000_000:
            raise RuntimeError("Downloaded model looks incomplete")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def ensure_model_path() -> Path:
    found = find_model_path()
    if found is not None:
        return found
    return download_model()


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class Settings:
    """User-facing, persisted preferences."""

    schema: int = 2
    diameter: int = 280
    shape: str = "round"
    zoom: float = 2.0
    smoothing: float = 0.72
    opacity: float = 0.98
    show_ring: bool = True
    show_osd: bool = True
    lens_visible: bool = True
    camera_index: int = 0
    control_mode: str = "head"

    DIAMETER_RANGE = (120, 1200)
    SHAPE_OPTIONS = ("round", "square", "wide")
    CONTROL_MODE_OPTIONS = ("head", "eyes")
    WIDE_ASPECT = 1.6
    ZOOM_RANGE = (1.0, 6.0)
    SMOOTHING_RANGE = (0.0, 1.0)
    OPACITY_RANGE = (0.4, 1.0)

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        source = path or settings_path()
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {field.name for field in fields(cls)}
        values = {key: value for key, value in raw.items() if key in known}
        try:
            settings = cls(**values)
        except TypeError:
            return cls()
        # v2 changed the default follow behaviour from "responsive" to
        # "calm".  Migrate old settings once; afterwards the slider value is
        # whatever the user chose.
        if int(raw.get("schema", 1)) < 2:
            settings.smoothing = cls().smoothing
            settings.schema = 2
        return settings.normalized()

    def normalized(self) -> Settings:
        self.schema = 2
        self.diameter = int(
            _clamp(float(self.diameter), *self.DIAMETER_RANGE)
        )
        shape = str(self.shape).strip().lower()
        self.shape = shape if shape in self.SHAPE_OPTIONS else "round"
        control = str(self.control_mode).strip().lower()
        self.control_mode = (
            control if control in self.CONTROL_MODE_OPTIONS else "head"
        )
        self.zoom = round(_clamp(float(self.zoom), *self.ZOOM_RANGE), 2)
        self.smoothing = _clamp(float(self.smoothing), *self.SMOOTHING_RANGE)
        self.opacity = _clamp(float(self.opacity), *self.OPACITY_RANGE)
        self.camera_index = int(_clamp(float(self.camera_index), 0, 9))
        self.show_ring = bool(self.show_ring)
        self.show_osd = bool(self.show_osd)
        self.lens_visible = bool(self.lens_visible)
        return self

    def save(self, path: Path | None = None) -> None:
        _atomic_write_json(path or settings_path(), asdict(self))

    def copy(self) -> Settings:
        return Settings(**asdict(self))


def preferred_big_diameter(screen_height: int) -> int:
    """A large but still on-screen lens size for the Big lens toggle."""
    low, high = Settings.DIAMETER_RANGE
    return int(max(low, min(high, round(max(screen_height, low) * 0.85))))


def lens_dimensions(shape: str, diameter: int) -> tuple[int, int]:
    """Return (width, height) in logical pixels for a lens shape.

    ``diameter`` is the height for every shape.  A wide lens keeps that height
    and is 1.6x wider.
    """
    height = int(max(1, int(diameter)))
    width = (
        int(round(height * Settings.WIDE_ASPECT))
        if str(shape).lower() == "wide"
        else height
    )
    return width, height


@dataclass(frozen=True)
class ScreenInfo:
    """Describes the calibrated screen in Qt logical coordinates."""

    name: str
    left: int
    top: int
    width: int
    height: int
    dpr: float = 1.0

    @classmethod
    def from_values(
        cls, name: str, left: int, top: int, width: int, height: int, dpr: float
    ) -> ScreenInfo:
        return cls(name, int(left), int(top), int(width), int(height), float(dpr))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ScreenInfo:
        return cls(
            name=str(raw.get("name", "")),
            left=int(raw.get("left", 0)),
            top=int(raw.get("top", 0)),
            width=int(raw.get("width", 0)),
            height=int(raw.get("height", 0)),
            dpr=float(raw.get("dpr", 1.0)),
        )

    def matches(self, other: ScreenInfo, tolerance: int = 2) -> bool:
        return (
            self.name == other.name
            and abs(self.left - other.left) <= tolerance
            and abs(self.top - other.top) <= tolerance
            and abs(self.width - other.width) <= tolerance
            and abs(self.height - other.height) <= tolerance
        )


@dataclass
class AppState:
    """Small non-secret runtime marker used for friendly first-run behavior."""

    last_calibrated_at: float = 0.0

    @classmethod
    def load(cls) -> AppState:
        try:
            raw = json.loads((config_dir() / "state.json").read_text("utf-8"))
            return cls(float(raw.get("last_calibrated_at", 0.0)))
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        _atomic_write_json(
            config_dir() / "state.json",
            {"last_calibrated_at": self.last_calibrated_at, "updated_at": time.time()},
        )
