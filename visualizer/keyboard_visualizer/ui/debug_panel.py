"""Debug panel widget for logging events."""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QLabel,
    QPushButton,
    QHBoxLayout,
)
from PySide6.QtCore import Qt
from datetime import datetime


class DebugPanel(QWidget):
    """Debug panel showing event log and status information."""

    MAX_LOG_LINES = 500

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._setup_ui()
        self._log_lines = 0

    def _setup_ui(self) -> None:
        """Setup the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Header with clear button
        header_layout = QHBoxLayout()
        header_label = QLabel("Debug Log")
        header_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(header_label)
        header_layout.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(60)
        clear_btn.clicked.connect(self.clear)
        header_layout.addWidget(clear_btn)

        layout.addLayout(header_layout)

        # Log text area
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setStyleSheet(
            """
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """
        )
        layout.addWidget(self._log_text)

    def log(self, message: str) -> None:
        """Add a log message."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = f"[{timestamp}] {message}"
        self._log_text.append(formatted)
        self._log_lines += 1

        # Trim old lines if needed
        if self._log_lines > self.MAX_LOG_LINES:
            self._trim_log()

        # Auto-scroll to bottom
        scrollbar = self._log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def log_error(self, message: str) -> None:
        """Add an error log message (highlighted)."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = f'<span style="color: #f44336;">[{timestamp}] ERROR: {message}</span>'
        self._log_text.append(formatted)
        self._log_lines += 1

    def log_success(self, message: str) -> None:
        """Add a success log message (highlighted)."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = f'<span style="color: #4caf50;">[{timestamp}] {message}</span>'
        self._log_text.append(formatted)
        self._log_lines += 1

    def log_key_event(
        self,
        event_type: str,
        scancode: int,
        vk_code: int,
        qmk_code: str | None,
        key_index: int | None,
    ) -> None:
        """Log a keyboard event with details."""
        parts = [f"{event_type}: sc=0x{scancode:02X}, vk=0x{vk_code:02X}"]

        if qmk_code:
            parts.append(f"qmk={qmk_code}")

        if key_index is not None:
            parts.append(f"idx={key_index}")
            self.log(" ".join(parts))
        else:
            # Log unmapped keys in different color
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            formatted = f'<span style="color: #888888;">[{timestamp}] {" ".join(parts)} (unmapped)</span>'
            self._log_text.append(formatted)
            self._log_lines += 1

    def clear(self) -> None:
        """Clear the log."""
        self._log_text.clear()
        self._log_lines = 0

    def _trim_log(self) -> None:
        """Trim old log lines."""
        # Get current text, split into lines, keep last MAX_LOG_LINES
        text = self._log_text.toHtml()
        # This is a simple approach - in production would use a proper log buffer
        self._log_text.clear()
        self._log_lines = 0
