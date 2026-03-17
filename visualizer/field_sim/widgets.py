"""Qt widgets for the reaction-diffusion keyboard view."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QBrush
from PySide6.QtWidgets import QWidget

from .models import KeyCell
from .reaction_diffusion import RDState


def rd_state_to_qcolor(state: RDState) -> QColor:
    """Map (A, B) to a wider, more contrasty color range."""
    a, b = state
    contrast = math.tanh((b - a) * 3.2)
    intensity = max(0.28, min(1.0, (a + b) * 0.7 + abs(contrast) * 0.55))

    red_mix = max(0.0, contrast)
    blue_mix = max(0.0, -contrast)
    mid_mix = max(0.0, 1.0 - abs(contrast))

    red = int(255 * intensity * (0.18 + 0.82 * red_mix))
    green = int(255 * intensity * (0.10 + 0.55 * mid_mix))
    blue = int(255 * intensity * (0.18 + 0.82 * blue_mix))
    return QColor(
        max(0, min(255, red)),
        max(0, min(255, green)),
        max(0, min(255, blue)),
    )


class KeyboardRDWidget(QWidget):
    """Render the keyboard as reaction-diffusion cells."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout_name = ""
        self._cells: list[KeyCell] = []
        self._states: list[RDState] = []
        self.setMinimumSize(QSize(700, 320))

    def set_scene(self, layout_name: str, cells: list[KeyCell], states: list[RDState]) -> None:
        self._layout_name = layout_name
        self._cells = cells
        self._states = states
        self.update()

    def get_cell_colors(self) -> list[tuple[int, int, int]]:
        colors = [rd_state_to_qcolor(state) for state in self._states]
        return [(c.red(), c.green(), c.blue()) for c in colors]

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#101419"))

        if not self._cells:
            painter.setPen(QColor("#cccccc"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Load a layout JSON to begin.")
            return

        min_x = min(cell.x for cell in self._cells)
        min_y = min(cell.y for cell in self._cells)
        max_x = max(cell.x + cell.w for cell in self._cells)
        max_y = max(cell.y + cell.h for cell in self._cells)
        width = max_x - min_x
        height = max_y - min_y
        margin = 24.0
        scale = min(
            (self.width() - margin * 2) / max(width, 0.1),
            (self.height() - margin * 2) / max(height, 0.1),
        )
        offset_x = (self.width() - width * scale) / 2.0
        offset_y = (self.height() - height * scale) / 2.0

        for index, cell in enumerate(self._cells):
            state = self._states[index] if index < len(self._states) else (1.0, 0.0)
            color = rd_state_to_qcolor(state)
            rect = QRectF(
                offset_x + (cell.x - min_x) * scale,
                offset_y + (cell.y - min_y) * scale,
                cell.w * scale,
                cell.h * scale,
            )
            painter.setPen(QPen(QColor("#26303a"), 1.2))
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(rect, 8, 8)

        painter.setPen(QColor("#dbe3eb"))
        painter.drawText(12, 20, f"Layout: {self._layout_name}")
