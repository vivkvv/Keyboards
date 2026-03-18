"""Individual key graphics item."""

from typing import Callable, Optional

from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsItem, QStyleOptionGraphicsItem, QWidget
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QFont, QFontMetrics, QTransform
from PySide6.QtCore import Qt, QRectF
import math

from ..models import KeyGeometry
from ..parsers import KeyLabels


class KeyItem(QGraphicsRectItem):
    """
    Individual key graphics item.

    Handles:
    - Rotated key rendering using QGraphicsItem transforms
    - Press/release color changes
    - Single-line label display: "tap hold" with different colors
    - Multi-layer grid display (N×N grid for N layers)
    - Hover state for debugging
    """

    # Colors (defaults, can be overridden)
    COLOR_DEFAULT = QColor("#3c3c3c")
    COLOR_PRESSED = QColor("#4fc3f7")  # Light blue for tap
    COLOR_PRESSED_HOLD = QColor("#ffb74d")  # Orange for hold
    COLOR_BORDER = QColor("#5c5c5c")
    COLOR_BORDER_PRESSED = QColor("#81d4fa")
    COLOR_BORDER_PRESSED_HOLD = QColor("#ffd180")  # Lighter orange for hold border
    COLOR_BORDER_HID = QColor("#ffffff")
    COLOR_TUTOR_FEEDBACK_CORRECT = QColor("#43a047")
    COLOR_TUTOR_FEEDBACK_ERROR = QColor("#e53935")
    COLOR_TEXT_TAP = QColor("#ffffff")
    COLOR_TEXT_HOLD = QColor("#ffb74d")
    COLOR_TEXT_EMPTY = QColor("#666666")

    def __init__(
        self,
        index: int,
        geometry: KeyGeometry,
        scale: float,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(parent)

        self.index = index
        self.geometry = geometry
        self.scale = scale
        self._labels: KeyLabels | None = None
        self._full_keycode = ""
        self._pressed = False
        self._hold_mode = False  # True when key is being held (for MT/LT keys)
        self._pressed_layer_index: int | None = None
        self._observed_active_layer_index: int | None = None
        self._hid_active = False
        self._tutor_feedback: str | None = None

        # Multi-layer mode: list of (layer_index, KeyLabels, bg_color)
        self._multi_layer_data: list[tuple[int, KeyLabels, QColor]] | None = None

        # Configurable colors
        self._tap_color = self.COLOR_TEXT_TAP
        self._hold_color = self.COLOR_TEXT_HOLD
        self._active_layer_text_color = QColor("#000000")
        self._tap_fill_color = QColor(self.COLOR_PRESSED)
        self._hold_fill_color = QColor(self.COLOR_PRESSED_HOLD)
        self._tap_border_color = QColor(self.COLOR_BORDER_PRESSED)
        self._hold_border_color = QColor(self.COLOR_BORDER_PRESSED_HOLD)
        self._hid_border_color = QColor(self.COLOR_BORDER_HID)
        self._grid_line_color = QColor(self.COLOR_BORDER)
        self._tap_border_width = 2.0
        self._hold_border_width = 2.0
        self._hid_border_width = 1.5
        self._grid_line_width = 0.5
        self._hid_border_inset = 4.0
        self._hid_border_style = Qt.PenStyle.SolidLine
        self._label_font_scale = 1.0
        self._grid_label_font_scale = 1.0

        # Overlay mode: semi-transparent keys
        self._overlay_mode = False

        # Finger color for tutor mode (None = default color)
        self._finger_color: Optional[QColor] = None
        self._finger_indicator_visible = False
        self._finger_indicator_active = False

        # Click callback for HID control
        self._click_callback: Optional[Callable[[int], None]] = None

        # Key rectangle dimensions (local coordinates, unrotated)
        margin = 2  # Gap between keys
        key_width = geometry.w * scale
        key_height = geometry.h * scale

        self.setRect(margin, margin, key_width - margin * 2, key_height - margin * 2)

        # Enable hover events for tooltips
        self.setAcceptHoverEvents(True)

        # Enable mouse events for click handling
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)

        # Apply position and rotation transforms
        self._apply_transforms()

        # Set initial appearance
        self._update_appearance()

    def _apply_transforms(self) -> None:
        """Apply position and rotation transforms."""
        g = self.geometry

        # Create transform
        transform = QTransform()

        if g.r != 0 and g.rx is not None and g.ry is not None:
            # Rotated key: rotate around (rx, ry) then position
            # Rotation center in pixels
            rx_px = g.rx * self.scale
            ry_px = g.ry * self.scale

            # Key position relative to rotation center
            rel_x = (g.x - g.rx) * self.scale
            rel_y = (g.y - g.ry) * self.scale

            # Build transform: translate to rotation center, rotate, translate to key position
            transform.translate(rx_px, ry_px)
            transform.rotate(g.r)
            transform.translate(rel_x, rel_y)
        else:
            # Non-rotated key: simple translation
            transform.translate(g.x * self.scale, g.y * self.scale)

            # Apply any local rotation (r without rx/ry)
            if g.r != 0:
                # Rotate around key center
                center_x = g.w * self.scale / 2
                center_y = g.h * self.scale / 2
                transform.translate(center_x, center_y)
                transform.rotate(g.r)
                transform.translate(-center_x, -center_y)

        self.setTransform(transform)

    def _update_appearance(self) -> None:
        """Update the key's visual appearance."""
        # Determine base colors
        if self._pressed:
            if self._hold_mode:
                bg_color = QColor(self._hold_fill_color)
                border_color = QColor(self._hold_border_color)
            else:
                bg_color = QColor(self._tap_fill_color)
                border_color = QColor(self._tap_border_color)
        else:
            bg_color = QColor(self.COLOR_DEFAULT)
            border_color = QColor(self.COLOR_BORDER)

        # Apply transparency in overlay mode
        if self._overlay_mode:
            bg_color.setAlpha(180)  # ~70% opacity
            border_color.setAlpha(200)

        self.setBrush(QBrush(bg_color))
        border_width = self._hold_border_width if self._pressed and self._hold_mode else self._tap_border_width
        self.setPen(QPen(border_color, border_width))

    def set_overlay_mode(self, enabled: bool) -> None:
        """Enable overlay mode with semi-transparent keys."""
        self._overlay_mode = enabled
        self._update_appearance()

    def set_finger_color(self, color: Optional[QColor]) -> None:
        """Set finger color for tutor indicator."""
        self._finger_color = color
        self._finger_indicator_visible = color is not None
        self._update_appearance()
        self.update()

    def set_finger_indicator_active(self, active: bool) -> None:
        """Set whether the tutor finger indicator should be filled."""
        if self._finger_indicator_active != active:
            self._finger_indicator_active = active
            self.update()

    def set_labels(self, labels: KeyLabels) -> None:
        """Set the display labels for this key (single layer mode)."""
        self._labels = labels
        self._multi_layer_data = None  # Clear multi-layer mode
        self._full_keycode = labels.raw
        self.setToolTip(labels.raw)
        self.update()

    def set_multi_layer_labels(self, layer_data: list[tuple[int, KeyLabels, QColor]]) -> None:
        """Set labels for multiple layers (grid mode).

        Args:
            layer_data: List of (layer_index, KeyLabels, background_color) tuples
        """
        self._multi_layer_data = layer_data
        self._labels = None  # Clear single-layer mode

        # Build tooltip with all layers
        tooltip_lines = []
        for layer_idx, labels, _ in layer_data:
            if labels.tap or labels.hold:
                line = f"L{layer_idx}: {labels.tap}"
                if labels.hold:
                    line += f" ({labels.hold})"
                tooltip_lines.append(line)
        self.setToolTip("\n".join(tooltip_lines) if tooltip_lines else "")
        self.update()

    def set_text_colors(self, tap_color: QColor, hold_color: QColor) -> None:
        """Set the text colors for tap and hold."""
        self._tap_color = tap_color
        self._hold_color = hold_color
        self.update()

    def set_visual_style(
        self,
        *,
        active_layer_text_color: QColor,
        tap_fill_color: QColor,
        hold_fill_color: QColor,
        tap_border_color: QColor,
        hold_border_color: QColor,
        hid_border_color: QColor,
        grid_line_color: QColor,
        tap_border_width: float,
        hold_border_width: float,
        hid_border_width: float,
        grid_line_width: float,
        hid_border_inset: float,
        hid_border_style: Qt.PenStyle,
    ) -> None:
        """Set configurable visual style for pressed/grid states."""
        self._active_layer_text_color = QColor(active_layer_text_color)
        self._tap_fill_color = QColor(tap_fill_color)
        self._hold_fill_color = QColor(hold_fill_color)
        self._tap_border_color = QColor(tap_border_color)
        self._hold_border_color = QColor(hold_border_color)
        self._hid_border_color = QColor(hid_border_color)
        self._grid_line_color = QColor(grid_line_color)
        self._tap_border_width = float(tap_border_width)
        self._hold_border_width = float(hold_border_width)
        self._hid_border_width = float(hid_border_width)
        self._grid_line_width = float(grid_line_width)
        self._hid_border_inset = float(hid_border_inset)
        self._hid_border_style = hid_border_style
        self._update_appearance()
        self.update()

    def set_font_scales(self, label_scale: float, grid_scale: float) -> None:
        """Set font scaling factors for single-layer and grid labels."""
        self._label_font_scale = label_scale
        self._grid_label_font_scale = grid_scale
        self.update()

    def set_label(self, label: str) -> None:
        """Set the display label for this key (legacy, creates KeyLabels)."""
        self._labels = KeyLabels(tap=label, hold="", raw=label)
        self._multi_layer_data = None
        self.update()

    def set_full_keycode(self, keycode: str) -> None:
        """Set the full keycode (for tooltip)."""
        self._full_keycode = keycode
        self.setToolTip(keycode)

    def set_pressed(
        self,
        pressed: bool,
        hold_mode: bool = False,
        layer_index: int | None = None,
    ) -> None:
        """Set the pressed state of this key.

        Args:
            pressed: Whether the key is pressed
            hold_mode: True if this is a hold action (modifier sent), False for tap
            layer_index: Active layer to highlight in multi-layer view
        """
        effective_layer_index = layer_index if pressed else None
        if (
            self._pressed != pressed
            or self._hold_mode != hold_mode
            or self._pressed_layer_index != effective_layer_index
        ):
            self._pressed = pressed
            self._hold_mode = hold_mode if pressed else False
            self._pressed_layer_index = effective_layer_index
            self._update_appearance()
            self.update()

    def get_pressed_layer_index(self) -> int | None:
        """Return the currently highlighted multi-layer cell, if any."""
        return self._pressed_layer_index

    def set_hid_active(self, active: bool) -> None:
        """Set whether this key should show a firmware/HID contour."""
        if self._hid_active != active:
            self._hid_active = active
            self.update()

    def set_observed_active_layer(self, layer_index: int | None) -> None:
        """Set the layer currently considered active for multi-layer diagnostics."""
        if self._observed_active_layer_index != layer_index:
            self._observed_active_layer_index = layer_index
            self.update()

    def set_tutor_feedback(self, outcome: str | None) -> None:
        """Set transient tutor feedback state."""
        if self._tutor_feedback != outcome:
            self._tutor_feedback = outcome
            self.update()

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        rect = self.rect()

        if self._multi_layer_data:
            # Multi-layer grid mode
            self._paint_grid(painter, rect)
        else:
            # Single-layer mode
            painter.setBrush(self.brush())
            painter.setPen(self.pen())
            painter.drawRoundedRect(rect, 4, 4)
            if self._hid_active:
                hid_pen = QPen(self._hid_border_color, self._hid_border_width)
                hid_pen.setStyle(self._hid_border_style)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(hid_pen)
                painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 4, 4)
            self._paint_tutor_feedback(painter, rect)
            self._paint_finger_indicator(painter, rect)
            self._paint_single_layer_label(painter, rect)

    def _paint_grid(self, painter: QPainter, rect: QRectF) -> None:
        """Paint key as a grid of layers."""
        if not self._multi_layer_data:
            return

        num_layers = len(self._multi_layer_data)
        if num_layers == 0:
            return

        # Calculate grid size (ceil of sqrt)
        grid_size = math.ceil(math.sqrt(num_layers))

        cell_width = rect.width() / grid_size
        cell_height = rect.height() / grid_size

        # Draw border around entire key
        painter.setPen(self.pen())
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 4, 4)

        # Draw each cell
        for i, (layer_idx, labels, bg_color) in enumerate(self._multi_layer_data):
            row = i // grid_size
            col = i % grid_size

            cell_rect = QRectF(
                rect.x() + col * cell_width,
                rect.y() + row * cell_height,
                cell_width,
                cell_height
            )

            cell_bg_color = QColor(bg_color)
            if self._pressed and self._pressed_layer_index == layer_idx:
                cell_bg_color = QColor(self._hold_fill_color if self._hold_mode else self._tap_fill_color)
                if self._overlay_mode:
                    cell_bg_color.setAlpha(180)

            # Draw cell background
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(cell_bg_color))

            # Round corners only for corner cells
            if i == 0:  # Top-left
                painter.drawRoundedRect(cell_rect.adjusted(1, 1, 0, 0), 3, 3)
            elif i == grid_size - 1 and grid_size > 1:  # Top-right
                painter.drawRoundedRect(cell_rect.adjusted(0, 1, -1, 0), 3, 3)
            elif row == grid_size - 1 and col == 0:  # Bottom-left
                painter.drawRoundedRect(cell_rect.adjusted(1, 0, 0, -1), 3, 3)
            elif i == num_layers - 1:  # Last cell (may be bottom-right)
                painter.drawRoundedRect(cell_rect.adjusted(0, 0, -1, -1), 3, 3)
            else:
                painter.drawRect(cell_rect)

            # Draw cell label
            self._paint_cell_label(
                painter,
                cell_rect,
                labels,
                layer_idx,
                active=(layer_idx == self._observed_active_layer_index),
            )

        # Draw grid lines
        painter.setPen(QPen(self._grid_line_color, self._grid_line_width))
        for i in range(1, grid_size):
            # Vertical lines
            x = rect.x() + i * cell_width
            painter.drawLine(int(x), int(rect.y() + 2), int(x), int(rect.bottom() - 2))
            # Horizontal lines
            y = rect.y() + i * cell_height
            painter.drawLine(int(rect.x() + 2), int(y), int(rect.right() - 2), int(y))

        if self._pressed and self._pressed_layer_index is not None:
            self._paint_pressed_grid_cell_border(painter, rect, grid_size)
        if self._hid_active:
            self._paint_hid_grid_cell_border(painter, rect, grid_size)

    def _paint_pressed_grid_cell_border(self, painter: QPainter, rect: QRectF, grid_size: int) -> None:
        """Draw a highlighted border only around the active multi-layer cell."""
        if not self._multi_layer_data or self._pressed_layer_index is None:
            return

        active_cell_index = self._find_grid_cell_index(self._pressed_layer_index)
        if active_cell_index is None:
            return

        cell_width = rect.width() / grid_size
        cell_height = rect.height() / grid_size
        row = active_cell_index // grid_size
        col = active_cell_index % grid_size
        cell_rect = QRectF(
            rect.x() + col * cell_width,
            rect.y() + row * cell_height,
            cell_width,
            cell_height,
        ).adjusted(1.5, 1.5, -1.5, -1.5)

        border_color = self._hold_border_color if self._hold_mode else self._tap_border_color
        painter.setBrush(Qt.NoBrush)
        border_width = self._hold_border_width if self._hold_mode else self._tap_border_width
        painter.setPen(QPen(border_color, border_width))
        painter.drawRect(cell_rect)

    def _paint_hid_grid_cell_border(self, painter: QPainter, rect: QRectF, grid_size: int) -> None:
        """Draw a HID-specific inner border around the active multi-layer cell."""
        if not self._multi_layer_data:
            return

        target_layer = self._pressed_layer_index
        if target_layer is None:
            target_layer = self._observed_active_layer_index
        if target_layer is None:
            return

        active_cell_index = self._find_grid_cell_index(target_layer)
        if active_cell_index is None:
            return

        cell_width = rect.width() / grid_size
        cell_height = rect.height() / grid_size
        row = active_cell_index // grid_size
        col = active_cell_index % grid_size
        cell_rect = QRectF(
            rect.x() + col * cell_width,
            rect.y() + row * cell_height,
            cell_width,
            cell_height,
        ).adjusted(self._hid_border_inset, self._hid_border_inset, -self._hid_border_inset, -self._hid_border_inset)

        painter.setBrush(Qt.NoBrush)
        hid_pen = QPen(self._hid_border_color, self._hid_border_width)
        hid_pen.setStyle(self._hid_border_style)
        painter.setPen(hid_pen)
        painter.drawRect(cell_rect)

    def _find_grid_cell_index(self, layer_index: int | None) -> int | None:
        """Return the grid cell index for a given layer."""
        if not self._multi_layer_data or layer_index is None:
            return None
        for i, (candidate_layer, _, _) in enumerate(self._multi_layer_data):
            if candidate_layer == layer_index:
                return i
        return None

    def _paint_cell_label(
        self,
        painter: QPainter,
        rect: QRectF,
        labels: KeyLabels,
        layer_index: int,
        active: bool = False,
    ) -> None:
        """Paint label inside a grid cell (tap hold format)."""
        if not labels.tap and not labels.hold:
            return

        # Build display text and calculate font size
        if labels.hold:
            display_text = f"{labels.tap} {labels.hold}"
        else:
            display_text = labels.tap

        # Use smaller font for grid cells
        base_size = max(1, round(8 * self._grid_label_font_scale))
        font = QFont("Segoe UI", base_size)
        font_size = self._calculate_font_size(display_text, font, rect, min_size=1)
        font.setPointSize(font_size)
        painter.setFont(font)

        # Draw with different colors for tap and hold
        hold_text_color = self._hold_color
        if self._pressed and self._hold_mode and layer_index == self._pressed_layer_index:
            hold_bg = QColor(self._hold_fill_color)
            hold_text_color = QColor(
                255 - hold_bg.red(),
                255 - hold_bg.green(),
                255 - hold_bg.blue(),
            )

        if labels.hold:
            # Need to draw tap and hold separately with different colors
            metrics = QFontMetrics(font)
            tap_width = metrics.horizontalAdvance(labels.tap)
            space_width = metrics.horizontalAdvance(" ")
            hold_width = metrics.horizontalAdvance(labels.hold)
            total_width = tap_width + space_width + hold_width

            # Calculate starting position (centered)
            start_x = rect.x() + (rect.width() - total_width) / 2
            text_y = rect.y() + rect.height() / 2 + metrics.ascent() / 2 - 2

            # Draw tap
            painter.setPen(self._active_layer_text_color if active else self._tap_color)
            painter.drawText(int(start_x), int(text_y), labels.tap)

            # Draw hold
            painter.setPen(self._active_layer_text_color if active else hold_text_color)
            painter.drawText(int(start_x + tap_width + space_width), int(text_y), labels.hold)
        else:
            # Just tap, centered
            painter.setPen(self._active_layer_text_color if active else self._tap_color)
            painter.drawText(rect, Qt.AlignCenter, labels.tap)

    def _paint_single_layer_label(self, painter: QPainter, rect: QRectF) -> None:
        """Paint the key label for single-layer mode (tap hold format)."""
        if not self._labels:
            return

        if not self._labels.tap and not self._labels.hold:
            return

        # Build display text
        if self._labels.hold:
            display_text = f"{self._labels.tap} {self._labels.hold}"
        else:
            display_text = self._labels.tap

        # Calculate font size
        base_size = max(6, round(11 * self._label_font_scale))
        font = QFont("Segoe UI", base_size)
        font_size = self._calculate_font_size(display_text, font, rect)
        font.setPointSize(font_size)
        painter.setFont(font)

        # Draw with different colors for tap and hold
        if self._labels.hold:
            metrics = QFontMetrics(font)
            tap_width = metrics.horizontalAdvance(self._labels.tap)
            space_width = metrics.horizontalAdvance(" ")
            hold_width = metrics.horizontalAdvance(self._labels.hold)
            total_width = tap_width + space_width + hold_width

            start_x = rect.x() + (rect.width() - total_width) / 2
            text_y = rect.y() + rect.height() / 2 + metrics.ascent() / 2 - 2

            # Draw tap
            painter.setPen(self._tap_color)
            painter.drawText(int(start_x), int(text_y), self._labels.tap)

            # Draw hold
            painter.setPen(self._hold_color)
            painter.drawText(int(start_x + tap_width + space_width), int(text_y), self._labels.hold)
        else:
            painter.setPen(self._tap_color)
            painter.drawText(rect, Qt.AlignCenter, self._labels.tap)

    def _paint_finger_indicator(self, painter: QPainter, rect: QRectF) -> None:
        """Paint a small finger circle for tutor mode."""
        if not self._finger_indicator_visible or self._finger_color is None:
            return

        radius = min(rect.width(), rect.height()) * 0.13
        cx = rect.left() + radius + 8
        cy = rect.top() + radius + 8

        display_color = QColor(self._finger_color)
        display_color = display_color.lighter(120)
        pen = QPen(display_color, 2)
        painter.setPen(pen)
        if self._finger_indicator_active:
            brush_color = QColor(display_color)
            brush_color.setAlpha(245)
            painter.setBrush(brush_color)
        else:
            painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

    def _paint_tutor_feedback(self, painter: QPainter, rect: QRectF) -> None:
        """Paint a transient success/error overlay for tutor mode."""
        if self._tutor_feedback is None:
            return

        if self._tutor_feedback == "correct":
            color = QColor(self.COLOR_TUTOR_FEEDBACK_CORRECT)
        elif self._tutor_feedback == "error":
            color = QColor(self.COLOR_TUTOR_FEEDBACK_ERROR)
        else:
            return

        fill = QColor(color)
        fill.setAlpha(70)
        border = QPen(color, 2)
        painter.setBrush(QBrush(fill))
        painter.setPen(border)
        painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 4, 4)

    def _calculate_font_size(self, text: str, base_font: QFont, rect: QRectF | None = None, min_size: int = 6) -> int:
        """Calculate font size to fit text in given rect."""
        if rect is None:
            rect = self.rect()
        max_width = rect.width() - 4
        max_height = rect.height() - 2

        # Start with base size, reduce if needed
        size = base_font.pointSize()
        while size > min_size:
            metrics = QFontMetrics(QFont(base_font.family(), size))
            text_rect = metrics.boundingRect(text)
            if text_rect.width() <= max_width and text_rect.height() <= max_height:
                break
            size -= 1

        return size

    def set_click_callback(self, callback: Optional[Callable[[int], None]]) -> None:
        """Set callback for key clicks. Callback receives key index."""
        self._click_callback = callback

    def mousePressEvent(self, event) -> None:
        """Handle mouse press to trigger HID highlight."""
        if self._click_callback and event.button() == Qt.MouseButton.LeftButton:
            self._click_callback(self.index)
            event.accept()
        else:
            super().mousePressEvent(event)
