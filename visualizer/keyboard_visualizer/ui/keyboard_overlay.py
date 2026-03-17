"""Transparent keyboard-only overlay window."""

from typing import Optional, TYPE_CHECKING

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtCore import Qt, QPoint, Signal, QEvent

from .keyboard_widget import KeyboardWidget
from ..models import Keymap
from ..models.layout import Layout

if TYPE_CHECKING:
    from ..input.keyboard_layout import KeyboardLayoutDetector


class KeyboardOverlayWindow(QWidget):
    """Transparent always-on-top window showing only the keyboard."""

    closed = Signal()

    def __init__(self, layout: Optional[Layout] = None, keymap: Optional[Keymap] = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("keyboardOverlayRoot")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self.setStyleSheet(
            """
            QWidget#keyboardOverlayRoot {
                background: transparent;
            }
            QWidget#keyboardOverlayPanel {
                background: transparent;
                border: none;
            }
            """
        )

        self._drag_position: Optional[QPoint] = None
        self._normal_geometry = None
        self._pseudo_maximized = False
        self._mirrored_keyboard_transform = None

        self._drag_handle = QLabel("Overlay")
        self._drag_handle.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._drag_handle.setMinimumHeight(30)
        self._drag_handle.setCursor(Qt.CursorShape.SizeAllCursor)
        self._drag_handle.setStyleSheet("color: #b0bec5; font-size: 12px; padding-left: 8px;")
        self._drag_handle.installEventFilter(self)

        self._close_btn = QPushButton("✕")
        self._close_btn.setToolTip("Close Overlay")
        self._close_btn.setFixedWidth(36)
        self._close_btn.clicked.connect(self.close)

        self._maximize_btn = QPushButton("Maximize")
        self._maximize_btn.setFixedWidth(90)
        self._maximize_btn.clicked.connect(self._toggle_maximize_restore)

        self._keyboard_widget = KeyboardWidget()
        self._keyboard_widget.set_transparent_background(True)
        self._keyboard_widget.viewport().installEventFilter(self)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)
        outer_layout.setSpacing(6)

        top_controls = QHBoxLayout()
        top_controls.addWidget(self._drag_handle, 1)
        top_controls.addWidget(self._maximize_btn, 0)
        top_controls.addWidget(self._close_btn, 0)
        outer_layout.addLayout(top_controls)

        panel = QWidget()
        panel.setObjectName("keyboardOverlayPanel")
        panel.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        panel.setAutoFillBackground(False)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addWidget(self._keyboard_widget, 1)
        outer_layout.addWidget(panel, 1)

        self.resize(1200, 420)
        if layout:
            self.set_layout(layout)
        if keymap:
            self.set_keymap(keymap)

    def keyboard_widget(self) -> KeyboardWidget:
        return self._keyboard_widget

    def set_layout(self, layout: Layout) -> None:
        self._keyboard_widget.set_layout(layout)

    def set_keymap(self, keymap: Keymap) -> None:
        self._keyboard_widget.set_keymap(keymap)

    def set_layer(self, layer_index: int) -> None:
        self._keyboard_widget.set_layer(layer_index)

    def set_keyboard_view_state(self, size, transform) -> None:
        self._mirrored_keyboard_transform = transform
        self._keyboard_widget.setMinimumSize(size)
        self._keyboard_widget.resize(size)
        self._keyboard_widget.set_locked_transform(transform)

    def set_show_hold_labels(self, enabled: bool) -> None:
        self._keyboard_widget.set_show_hold_labels(enabled)

    def set_os_layout_mode(self, enabled: bool, layout_detector: Optional["KeyboardLayoutDetector"] = None, hkl: Optional[int] = None) -> None:
        self._keyboard_widget.set_os_layout_mode(enabled, layout_detector, hkl)

    def set_caps_lock_mode(self, caps_lock_on: bool) -> None:
        self._keyboard_widget.set_caps_lock_mode(caps_lock_on)

    def highlight_key(self, key_index: int, pressed: bool, hold_mode: bool = False) -> None:
        self._keyboard_widget.highlight_key(key_index, pressed, hold_mode)

    def set_hid_key_active(self, key_index: int, active: bool) -> None:
        self._keyboard_widget.set_hid_key_active(key_index, active)

    def eventFilter(self, obj, event):
        if obj is self._drag_handle:
            if event.type() == QEvent.Type.MouseButtonPress:
                self.mousePressEvent(event)
                return True
            if event.type() == QEvent.Type.MouseMove:
                self.mouseMoveEvent(event)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self.mouseReleaseEvent(event)
                return True
        if obj is self._keyboard_widget.viewport() and event.type() in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonRelease,
        }:
            if event.button() == Qt.MouseButton.RightButton or event.buttons() & Qt.MouseButton.RightButton:
                if event.type() == QEvent.Type.MouseButtonPress:
                    self.mousePressEvent(event)
                elif event.type() == QEvent.Type.MouseMove:
                    self.mouseMoveEvent(event)
                else:
                    self.mouseReleaseEvent(event)
                return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & (Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton) and self._drag_position is not None:
            if self._pseudo_maximized:
                self._toggle_maximize_restore()
                self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_position = None
        super().mouseReleaseEvent(event)

    def _toggle_maximize_restore(self) -> None:
        screen = self.screen() or self.windowHandle().screen() if self.windowHandle() else None
        if not self._pseudo_maximized:
            self._normal_geometry = self.geometry()
            available = screen.availableGeometry() if screen else self.geometry()
            self.setGeometry(available)
            self._pseudo_maximized = True
            self._maximize_btn.setText("Restore")
            self._keyboard_widget.unlock_transform()
        else:
            if self._normal_geometry is not None:
                self.setGeometry(self._normal_geometry)
            self._pseudo_maximized = False
            self._maximize_btn.setText("Maximize")
            if self._mirrored_keyboard_transform is not None:
                self._keyboard_widget.set_locked_transform(self._mirrored_keyboard_transform)

    def closeEvent(self, event) -> None:
        self.closed.emit()
        super().closeEvent(event)
