from __future__ import annotations

import pytest

from eyelens.capture import source_extent


def test_zoom_is_magnification_not_minification() -> None:
    # A 2x lens shows half of its own diameter, not twice its diameter.
    assert source_extent(280.0, 2.0) == pytest.approx(140.0)
    assert source_extent(280.0, 1.0) == pytest.approx(280.0)
    assert source_extent(280.0, 6.0) == pytest.approx(280.0 / 6.0)


def test_source_extent_is_never_degenerate() -> None:
    assert source_extent(0.0, 2.0) == pytest.approx(1.0)
    assert source_extent(280.0, 0.0) == pytest.approx(28000.0)
