from __future__ import annotations

from eyelens.config import (
    ScreenInfo,
    Settings,
    lens_dimensions,
    preferred_big_diameter,
)


def test_settings_normalization() -> None:
    settings = Settings(
        diameter=5000,
        zoom=99,
        smoothing=-1,
        opacity=5,
        camera_index=-3,
        control_mode="banana",
        trim_x=9999,
        trim_y=-9999,
    )
    normalized = settings.normalized()
    assert normalized.diameter == Settings.DIAMETER_RANGE[1]
    assert normalized.zoom == Settings.ZOOM_RANGE[1]
    assert normalized.smoothing == 0.0
    assert normalized.opacity == 1.0
    assert normalized.camera_index == 0
    assert normalized.control_mode == "head"
    assert normalized.trim_x == Settings.TRIM_RANGE
    assert normalized.trim_y == -Settings.TRIM_RANGE


def test_settings_control_mode_roundtrip(tmp_path) -> None:
    path = tmp_path / "settings.json"
    original = Settings(control_mode="eyes")
    original.save(path)
    loaded = Settings.load(path)
    assert loaded.control_mode == "eyes"
    assert Settings().control_mode == "head"


def test_settings_roundtrip(tmp_path) -> None:
    path = tmp_path / "settings.json"
    original = Settings(diameter=320, zoom=2.75, smoothing=0.2, opacity=0.8)
    original.save(path)
    loaded = Settings.load(path)
    assert loaded.diameter == 320
    assert loaded.zoom == 2.75
    assert loaded.smoothing == 0.2
    assert loaded.opacity == 0.8


def test_preferred_big_diameter_fits_screen() -> None:
    assert preferred_big_diameter(1200) == 1020
    assert preferred_big_diameter(1080) == 918
    assert preferred_big_diameter(400) == 340
    assert preferred_big_diameter(2000) == Settings.DIAMETER_RANGE[1]


def test_lens_shapes_and_dimensions() -> None:
    assert lens_dimensions("round", 280) == (280, 280)
    assert lens_dimensions("square", 280) == (280, 280)
    assert lens_dimensions("wide", 280) == (448, 280)
    assert lens_dimensions("wide", 1200) == (1920, 1200)
    assert Settings(shape="wide").normalized().shape == "wide"
    assert Settings(shape="banana").normalized().shape == "round"


def test_invalid_settings_file_uses_defaults(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("not json", encoding="utf-8")
    assert Settings.load(path).diameter == Settings().diameter


def test_screen_matching() -> None:
    a = ScreenInfo("DISPLAY1", 0, 0, 1920, 1200, 1.0)
    b = ScreenInfo("DISPLAY1", 0, 0, 1920, 1200, 1.25)
    c = ScreenInfo("DISPLAY1", 1920, 0, 1920, 1200, 1.0)
    assert a.matches(b)
    assert not a.matches(c)


def test_screen_dict_roundtrip() -> None:
    original = ScreenInfo("DISPLAY1", 10, 20, 1280, 720, 1.5)
    assert ScreenInfo.from_dict(original.to_dict()) == original
