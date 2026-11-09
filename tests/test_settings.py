from __future__ import annotations

from eyelens.config import ScreenInfo, Settings


def test_settings_normalization() -> None:
    settings = Settings(diameter=5000, zoom=99, smoothing=-1, opacity=5, camera_index=-3)
    normalized = settings.normalized()
    assert normalized.diameter == Settings.DIAMETER_RANGE[1]
    assert normalized.zoom == Settings.ZOOM_RANGE[1]
    assert normalized.smoothing == 0.0
    assert normalized.opacity == 1.0
    assert normalized.camera_index == 0


def test_settings_roundtrip(tmp_path) -> None:
    path = tmp_path / "settings.json"
    original = Settings(diameter=320, zoom=2.75, smoothing=0.2, opacity=0.8)
    original.save(path)
    loaded = Settings.load(path)
    assert loaded.diameter == 320
    assert loaded.zoom == 2.75
    assert loaded.smoothing == 0.2
    assert loaded.opacity == 0.8


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
