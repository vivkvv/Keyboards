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
        self._hid_active = False
        self._tutor_feedback: str | None = None

        # Multi-layer mode: list of (layer_index, KeyLabels, bg_color)
        self._multi_layer_data: list[tuple[int, KeyLabels, QColor]] | None = None

        # Configurable colors
        self._tap_color = self.COLOR_TEXT_TAP
        self._hold_color = self.COLOR_TEXT_HOLD

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
                bg_color = QColor(self.COLOR_PRESSED_HOLD)
                border_color = QColor(self.COLOR_BORDER_PRESSED_HOLD)
            else:
                bg_color = QColor(self.COLOR_PRESSED)
                border_color = QColor(self.COLOR_BORDER_PRESSED)
        else:
            bg_color = QColor(self.COLOR_DEFAULT)
            border_color = QColor(self.COLOR_BORDER)

        # Apply transparency in overlay mode
        if self._overlay_mode:
            bg_color.setAlpha(180)  # ~70% opacity
            border_color.setAlpha(200)

        self.setBrush(QBrush(bg_color))
        self.setPen(QPen(border_color, 1))

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

    def set_label(self, label: str) -> None:
        """Set the display label for this key (legacy, creates KeyLabels)."""
        self._labels = KeyLabels(tap=label, hold="", raw=label)
        self._multi_layer_data = None
        self.update()

    def set_full_keycode(self, keycode: str) -> None:
        """Set the full keycode (for tooltip)."""
        self._full_keycode = keycode
        self.setToolTip(keycode)

    def set_pressed(self, pressed: bool, hold_mode: bool = False) -> None:
        """Set the pressed state of this key.

        Args:
            pressed: Whether the key is pressed
            hold_mode: True if this is a hold action (modifier sent), False for tap
        """
        if self._pressed != pressed or self._hold_mode != hold_mode:
            self._pressed = pressed
            self._hold_mode = hold_mode if pressed else False
            self._update_appearance()
            self.update()

    def set_hid_active(self, active: bool) -> None:
        """Set whether this key should show a firmware/HID contour."""
        if self._hid_active != active:
            self._hid_active = active
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
                hid_pen = QPen(self.COLOR_BORDER_HID, 2)
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

            # Draw cell background
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(bg_color))

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
            self._paint_cell_label(painter, cell_rect, labels)

        # Draw grid lines
        painter.setPen(QPen(self.COLOR_BORDER, 0.5))
        for i in range(1, grid_size):
            # Vertical lines
            x = rect.x() + i * cell_width
            painter.drawLine(int(x), int(rect.y() + 2), int(x), int(rect.bottom() - 2))
            # Horizontal lines
            y = rect.y() + i * cell_height
            painter.drawLine(int(rect.x() + 2), int(y), int(rect.right() - 2), int(y))

    def _paint_cell_label(self, painter: QPainter, rect: QRectF, labels: KeyLabels) -> None:
        """Paint label inside a grid cell (tap hold format)."""
        if not labels.tap and not labels.hold:
            return

        # Build display text and calculate font size
        if labels.hold:
            display_text = f"{labels.tap} {labels.hold}"
        else:
            display_text = labels.tap

        # Use smaller font for grid cells
        base_size = 8
        font = QFont("Segoe UI", base_size)
        font_size = self._calculate_font_size(display_text, font, rect, min_size=5)
        font.setPointSize(font_size)
        painter.setFont(font)

        # Draw with different colors for tap and hold
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
            painter.setPen(self._tap_color)
            painter.drawText(int(start_x), int(text_y), labels.tap)

            # Draw hold
            painter.setPen(self._hold_color)
            painter.drawText(int(start_x + tap_width + space_width), int(text_y), labels.hold)
        else:
            # Just tap, centered
            painter.setPen(self._tap_color)
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
        font = QFont("Segoe UI", 11)
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
