from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF

from eyelens.ui.overlay import (
    clamp_lens_center,
    lens_source_point,
    point_in_lens,
)


def test_lens_center_can_reach_screen_edges() -> None:
    assert clamp_lens_center(960, 600, 280, 280, 1920, 1200) == (960, 600)
    assert clamp_lens_center(-100, -50, 280, 280, 1920, 1200) == (0, 0)
    assert clamp_lens_center(5000, 5000, 280, 280, 1920, 1200) == (1920, 1200)
    # A lens larger than the screen stays centred.
    assert clamp_lens_center(0, 0, 2400, 1600, 1920, 1200) == (960, 600)


def test_magnified_click_maps_back_to_source() -> None:
    center = QPointF(500, 500)
    # At 2x, a point 200 px right of the lens centre is 100 px on screen.
    source = lens_source_point(center, QPointF(700, 600), 2.0)
    assert source == QPointF(600, 550)
    # The lens centre maps to itself at any zoom.
    assert lens_source_point(center, center, 4.0) == center


def test_lens_hit_area_follows_shape() -> None:
    center = QPointF(200, 200)
    assert point_in_lens(center, QPointF(200, 200), 120, 120, "round")
    assert point_in_lens(center, QPointF(200, 255), 120, 120, "round")
    assert not point_in_lens(center, QPointF(200, 265), 120, 120, "round")
    # Rounded rectangles are wider than tall when requested.
    assert point_in_lens(center, QPointF(270, 200), 160, 100, "wide")
    assert not point_in_lens(center, QPointF(200, 260), 160, 100, "wide")
