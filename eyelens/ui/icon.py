"""Programmatically drawn app icon (no binary assets required)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

BRAND = QColor("#38bdf8")
BRAND_SOFT = QColor("#7dd3fc")
INK = QColor("#08111f")


def make_pixmap(size: int = 256) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # Rounded dark tile.
    margin = size * 0.035
    tile = QRectF(margin, margin, size - margin * 2, size - margin * 2)
    gradient = QLinearGradient(tile.topLeft(), tile.bottomRight())
    gradient.setColorAt(0.0, QColor("#101c2e"))
    gradient.setColorAt(1.0, QColor("#070d17"))
    painter.setPen(QPen(QColor(255, 255, 255, 28), max(1.0, size * 0.006)))
    painter.setBrush(gradient)
    painter.drawRoundedRect(tile, size * 0.22, size * 0.22)

    # Magnifier handle.
    center = QPointF(size * 0.46, size * 0.44)
    radius = size * 0.255
    handle_start = QPointF(
        center.x() + radius * 0.72, center.y() + radius * 0.72
    )
    handle_end = QPointF(size * 0.80, size * 0.80)
    painter.setPen(
        QPen(
            BRAND,
            size * 0.075,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
    )
    painter.drawLine(handle_start, handle_end)

    # Lens body.
    painter.setPen(QPen(BRAND, size * 0.032))
    painter.setBrush(QColor(11, 26, 43, 235))
    painter.drawEllipse(center, radius, radius)
    painter.setPen(QPen(QColor(125, 211, 252, 55), max(1.0, size * 0.008)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(center, radius * 0.84, radius * 0.84)

    # Eye inside the lens.
    eye_path = QPainterPath()
    eye_w = radius * 1.18
    eye_h = radius * 0.62
    left = center.x() - eye_w / 2
    right = center.x() + eye_w / 2
    eye_path.moveTo(left, center.y())
    eye_path.cubicTo(
        center.x() - eye_w * 0.28,
        center.y() - eye_h,
        center.x() + eye_w * 0.28,
        center.y() - eye_h,
        right,
        center.y(),
    )
    eye_path.cubicTo(
        center.x() + eye_w * 0.28,
        center.y() + eye_h,
        center.x() - eye_w * 0.28,
        center.y() + eye_h,
        left,
        center.y(),
    )
    painter.setPen(
        QPen(
            QColor("#e0f2fe"),
            size * 0.026,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
    )
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(eye_path)

    iris_r = radius * 0.31
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(BRAND)
    painter.drawEllipse(center, iris_r, iris_r)
    painter.setBrush(INK)
    painter.drawEllipse(center, iris_r * 0.48, iris_r * 0.48)
    painter.setBrush(QColor(255, 255, 255, 220))
    painter.drawEllipse(
        QPointF(center.x() - iris_r * 0.32, center.y() - iris_r * 0.34),
        iris_r * 0.17,
        iris_r * 0.17,
    )

    # Glass highlight.
    painter.setBrush(QColor(255, 255, 255, 20))
    painter.setPen(Qt.PenStyle.NoPen)
    highlight = QRectF(
        center.x() - radius * 0.72,
        center.y() - radius * 0.86,
        radius * 1.1,
        radius * 0.72,
    )
    painter.drawEllipse(highlight)

    painter.end()
    return pixmap


def make_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(make_pixmap(size))
    return icon
