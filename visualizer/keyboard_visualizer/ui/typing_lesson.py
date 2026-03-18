"""Typing lesson widget for tutor mode."""

from enum import Enum
from typing import Optional, Callable
from dataclasses import dataclass, field
import time

from html import escape

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QProgressBar, QTextBrowser
from PySide6.QtGui import QFont, QColor, QPainter, QFontMetrics, QTextCursor, QTextDocument
from PySide6.QtCore import Qt, Signal, QRect, QTimer


class ErrorMode(Enum):
    """How to handle typing errors."""
    CONTINUE = "continue"  # Mark error red and continue
    WAIT = "wait"  # Wait for correct key before continuing


class AttemptOutcome(Enum):
    """Result of a single keypress attempt inside a lesson."""

    IGNORED = "ignored"
    CORRECT = "correct"
    ERROR = "error"


@dataclass
class TypingStats:
    """Statistics for typing session."""
    total_chars: int = 0
    correct_chars: int = 0
    error_chars: int = 0
    current_position: int = 0
    elapsed_seconds: float = 0.0
    started: bool = False
    completed: bool = False

    @property
    def accuracy(self) -> float:
        """Calculate accuracy percentage."""
        if self.total_chars == 0:
            return 100.0
        return (self.correct_chars / self.total_chars) * 100

    @property
    def correct_wpm(self) -> float:
        """Calculate speed of correctly typed characters."""
        if self.elapsed_seconds <= 0:
            return 0.0
        return (self.correct_chars / 5.0) / (self.elapsed_seconds / 60.0)

    @property
    def error_wpm(self) -> float:
        """Calculate speed of mistyped characters."""
        if self.elapsed_seconds <= 0:
            return 0.0
        return (self.error_chars / 5.0) / (self.elapsed_seconds / 60.0)


@dataclass
class CharState:
    """State of a character in the lesson."""
    char: str
    typed: bool = False
    correct: bool = True
    typed_char: Optional[str] = None
    # Which key index should be pressed (for finger hints)
    key_index: Optional[int] = None


class TypingTextWidget(QWidget):
    """
    Widget displaying text to type with color-coded progress.

    Characters are colored:
    - Gray: not yet typed
    - Green: typed correctly
    - Red: typed incorrectly
    - Highlighted: current character to type
    """

    # Signal emitted when a character should be typed (for finger hints)
    char_expected = Signal(str, int)  # (char, key_index or -1)

    # Signal emitted when lesson is complete
    lesson_complete = Signal(TypingStats)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._text = ""
        self._char_states: list[CharState] = []
        self._current_pos = 0
        self._error_mode = ErrorMode.CONTINUE
        self._stats = TypingStats()
        self._started_at: Optional[float] = None
        self._completed_at: Optional[float] = None
        self._last_attempt_outcome = AttemptOutcome.IGNORED
        self._cursor_visible = True

        # Callback to get key index for a character
        self._char_to_key: Optional[Callable[[str], Optional[int]]] = None

        # Colors
        self._color_pending = QColor("#888888")  # Gray - not typed
        self._color_correct = QColor("#4CAF50")  # Green - correct
        self._color_error = QColor("#F44336")    # Red - error
        self._color_current_bg = QColor("#FFEB3B")  # Yellow highlight
        self._color_current_fg = QColor("#000000")  # Black text on yellow

        # Font
        self._font = QFont("Consolas", 24)
        self._font.setBold(True)

        self.setMinimumHeight(80)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(500)
        self._cursor_timer.timeout.connect(self._toggle_cursor)
        self._cursor_timer.start()

    def set_text(self, text: str) -> None:
        """Set the text to type."""
        self._text = text
        self._char_states = [CharState(char=c) for c in text]
        self._current_pos = 0
        self._stats = TypingStats(total_chars=len(text))
        self._started_at = None
        self._completed_at = None
        self._last_attempt_outcome = AttemptOutcome.IGNORED
        self._cursor_visible = True

        # Map characters to key indices if callback is set
        if self._char_to_key:
            for state in self._char_states:
                state.key_index = self._char_to_key(state.char)

        self.update()
        self._emit_current_char()

    def set_error_mode(self, mode: ErrorMode) -> None:
        """Set how errors are handled."""
        self._error_mode = mode

    def set_char_to_key_callback(self, callback: Callable[[str], Optional[int]]) -> None:
        """Set callback to convert character to key index."""
        self._char_to_key = callback

    def refresh_key_indices(self) -> None:
        """Recompute key indices for the current lesson text."""
        if not self._char_to_key:
            return
        for state in self._char_states:
            state.key_index = self._char_to_key(state.char)
        self.update()
        self._emit_current_char()

    def handle_keypress(self, char: str) -> bool:
        """
        Handle a typed character.

        Returns True if the character was accepted (correct or error in CONTINUE mode).
        Returns False if waiting for correct character (WAIT mode).
        """
        if self._current_pos >= len(self._char_states):
            self._last_attempt_outcome = AttemptOutcome.IGNORED
            return False

        expected = self._char_states[self._current_pos].char
        is_correct = (char == expected)

        if is_correct:
            self._last_attempt_outcome = AttemptOutcome.CORRECT
            self._ensure_started()
            self._char_states[self._current_pos].typed = True
            self._char_states[self._current_pos].correct = True
            self._char_states[self._current_pos].typed_char = None
            self._stats.correct_chars += 1
            self._current_pos += 1
            self._stats.current_position = self._current_pos

            self.update()
            self._emit_current_char()

            # Check if lesson complete
            if self._current_pos >= len(self._char_states):
                self._mark_completed()
                self.lesson_complete.emit(self._stats)

            return True

        else:
            if self._started_at is None:
                # Do not start or penalize the lesson until the first correct symbol.
                self._last_attempt_outcome = AttemptOutcome.IGNORED
                return False

            # Error
            self._last_attempt_outcome = AttemptOutcome.ERROR
            self._stats.error_chars += 1
            self._char_states[self._current_pos].correct = False
            self._char_states[self._current_pos].typed_char = char

            if self._error_mode == ErrorMode.CONTINUE:
                self._char_states[self._current_pos].typed = True
                self._current_pos += 1
                self._stats.current_position = self._current_pos

                self.update()
                self._emit_current_char()

                if self._current_pos >= len(self._char_states):
                    self._mark_completed()
                    self.lesson_complete.emit(self._stats)

                return True
            else:
                # WAIT mode - don't advance
                self.update()
                return False

    def _emit_current_char(self) -> None:
        """Emit signal for current character to type."""
        if self._current_pos < len(self._char_states):
            state = self._char_states[self._current_pos]
            key_index = state.key_index if state.key_index is not None else -1
            self.char_expected.emit(state.char, key_index)

    def get_current_key_index(self) -> Optional[int]:
        """Get the key index for the current character."""
        if self._current_pos < len(self._char_states):
            return self._char_states[self._current_pos].key_index
        return None

    def get_current_position(self) -> int:
        """Return the current lesson position."""
        return self._current_pos

    def get_expected_char(self) -> Optional[str]:
        """Return the currently expected character, if any."""
        if self._current_pos < len(self._char_states):
            return self._char_states[self._current_pos].char
        return None

    def get_stats(self) -> TypingStats:
        """Get current typing statistics."""
        self._refresh_elapsed()
        return self._stats

    def reset(self) -> None:
        """Reset to beginning of text."""
        for state in self._char_states:
            state.typed = False
            state.correct = True
            state.typed_char = None
        self._current_pos = 0
        self._stats = TypingStats(total_chars=len(self._char_states))
        self._started_at = None
        self._completed_at = None
        self._last_attempt_outcome = AttemptOutcome.IGNORED
        self._cursor_visible = True
        self.update()
        self._emit_current_char()

    def get_last_attempt_outcome(self) -> AttemptOutcome:
        """Return the outcome of the most recent keypress attempt."""
        return self._last_attempt_outcome

    def get_render_snapshot(self) -> tuple[str, list[CharState], int]:
        """Return a lightweight snapshot for alternative renderers."""
        copied = [
            CharState(
                char=state.char,
                typed=state.typed,
                correct=state.correct,
                typed_char=state.typed_char,
                key_index=state.key_index,
            )
            for state in self._char_states
        ]
        return self._text, copied, self._current_pos

    def _ensure_started(self) -> None:
        """Start lesson timing on the first keypress."""
        if self._started_at is None:
            self._started_at = time.monotonic()
            self._stats.started = True
            self._refresh_elapsed()

    def _mark_completed(self) -> None:
        """Freeze lesson time on completion."""
        if self._completed_at is None:
            self._completed_at = time.monotonic()
            self._stats.completed = True
            self._refresh_elapsed()

    def _refresh_elapsed(self) -> None:
        """Refresh elapsed time in stats."""
        if self._started_at is None:
            self._stats.elapsed_seconds = 0.0
            return

        end_time = self._completed_at if self._completed_at is not None else time.monotonic()
        self._stats.elapsed_seconds = max(0.0, end_time - self._started_at)

    def _toggle_cursor(self) -> None:
        """Blink the current-character cursor."""
        if self._stats.completed:
            if self._cursor_visible:
                self._cursor_visible = False
                self.update()
            return
        self._cursor_visible = not self._cursor_visible
        self.update()

    def paintEvent(self, event) -> None:
        """Paint the text with colored characters."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self._font)

        metrics = QFontMetrics(self._font)
        char_height = metrics.height()
        wrong_font = QFont(self._font)
        wrong_font.setBold(False)
        wrong_font.setPointSize(max(10, self._font.pointSize() - 6))
        wrong_metrics = QFontMetrics(wrong_font)

        # Center text vertically
        y = (self.height() + char_height) // 2 - metrics.descent()

        # Calculate total width for centering
        total_width = sum(metrics.horizontalAdvance(s.char) for s in self._char_states)
        x = max(10, (self.width() - total_width) // 2)

        for i, state in enumerate(self._char_states):
            char_width = metrics.horizontalAdvance(state.char)

            # Draw highlight for current character
            if i == self._current_pos:
                highlight_rect = QRect(x - 2, y - char_height + metrics.descent(), char_width + 4, char_height + 4)
                painter.fillRect(highlight_rect, self._color_current_bg)
                painter.setPen(self._color_current_fg)
            elif state.typed:
                if state.correct:
                    painter.setPen(self._color_correct)
                else:
                    painter.setPen(self._color_error)
            else:
                painter.setPen(self._color_pending)

            painter.drawText(x, y, state.char)

            if state.typed_char and state.typed_char != state.char and not state.correct:
                wrong_y = y + wrong_metrics.height()
                painter.setFont(wrong_font)
                painter.setPen(self._color_error)
                painter.drawText(x, wrong_y, state.typed_char)
                painter.setFont(self._font)

            if i == self._current_pos and self._cursor_visible:
                cursor_rect = QRect(x, y + 4, max(2, char_width), 3)
                painter.fillRect(cursor_rect, QColor("#40c4ff"))

            x += char_width

        painter.end()


class RichTypingTextWidget(QTextBrowser):
    """Experimental rich-text renderer for tutor text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshot_text = ""
        self._snapshot_states: list[CharState] = []
        self._snapshot_current_pos = 0
        self._debug_log_callback: Optional[Callable[[str], None]] = None
        self._last_layout_log_signature: tuple[int, int, int, int] | None = None
        self._cursor_visible = True
        self.setReadOnly(True)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            """
            QTextBrowser {
                background: transparent;
                border: 1px solid #303030;
                border-radius: 6px;
                padding: 6px;
            }
            """
        )
        self.document().setDocumentMargin(6)
        font = QFont("Consolas", 24)
        font.setBold(True)
        self.setFont(font)
        self.setMinimumHeight(150)
        self.setMaximumHeight(170)
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(500)
        self._cursor_timer.timeout.connect(self._toggle_cursor)
        self._cursor_timer.start()

    def sync_from_snapshot(self, text: str, char_states: list[CharState], current_pos: int) -> None:
        """Render a lesson snapshot using wrapped rich text."""
        self._snapshot_text = text
        self._snapshot_states = char_states
        if current_pos != self._snapshot_current_pos:
            self._cursor_visible = True
        self._snapshot_current_pos = current_pos
        self._rebuild_html()

    def set_debug_log_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        """Set optional debug logger for layout diagnostics."""
        self._debug_log_callback = callback

    def resizeEvent(self, event) -> None:
        """Reflow character blocks on resize."""
        super().resizeEvent(event)
        self._rebuild_html()

    def _toggle_cursor(self) -> None:
        """Blink the current-character cursor."""
        self._cursor_visible = not self._cursor_visible
        self._rebuild_html()

    def _rebuild_html(self) -> None:
        """Rebuild wrapped HTML from the latest snapshot."""
        states = self._snapshot_states
        if not states:
            self.clear()
            return

        available_width = max(1, self.viewport().width() - 16)
        columns = self._fit_columns(states, available_width)

        rows: list[list[tuple[int, CharState]]] = []
        for start in range(0, len(states), columns):
            chunk = [(index, states[index]) for index in range(start, min(len(states), start + columns))]
            rows.append(chunk)

        current_index = min(max(self._snapshot_current_pos, 0), max(0, len(states) - 1))
        current_row = current_index // columns
        signature = (
            available_width,
            columns,
            len(rows),
            current_row,
        )
        if self._debug_log_callback is not None and signature != self._last_layout_log_signature:
            self._last_layout_log_signature = signature
            self._debug_log_callback(
                "RichTypingTextWidget layout: "
                f"available_width={available_width} columns={columns} rows={len(rows)} "
                f"current_pos={self._snapshot_current_pos} current_row={current_row}"
            )

        html_parts: list[str] = [
            "<div style='font-family: Consolas, monospace; font-size: 24pt; font-weight: 700;'>"
        ]
        for row in rows:
            html_parts.append(self._build_row_table_html(row))
        html_parts.append("</div>")
        self.setHtml("".join(html_parts))
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.setTextCursor(cursor)
        self.scrollToAnchor("current-char")

    @staticmethod
    def _wrap_cell_span(char_html: str, style: str) -> str:
        """Wrap one expected character with the desired style."""
        return f"<span style='{style}'>{char_html}</span>"

    def _fit_columns(self, states: list[CharState], available_width: int) -> int:
        """Fit the number of columns by measuring actual rendered width."""
        if not states:
            return 1
        low = 1
        high = len(states)
        best = 1
        while low <= high:
            mid = (low + high) // 2
            sample_row = [(index, states[index]) for index in range(min(len(states), mid))]
            row_html = (
                "<div style='font-family: Consolas, monospace; font-size: 24pt; font-weight: 700;'>"
                f"{self._build_row_table_html(sample_row)}"
                "</div>"
            )
            if self._measure_html_width(row_html) <= available_width:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        return max(1, best)

    def _measure_html_width(self, html: str) -> float:
        """Measure rendered document width for a candidate row."""
        document = QTextDocument()
        document.setDefaultFont(self.font())
        document.setDocumentMargin(6)
        document.setHtml(html)
        return document.size().width()

    def _build_row_table_html(self, row: list[tuple[int, CharState]]) -> str:
        """Build a two-row HTML table for one wrapped line."""
        html_parts: list[str] = [
            "<table cellspacing='0' cellpadding='0' style='border-collapse:collapse; margin:0 0 6px 0;'>",
            "<tr>",
        ]
        for index, state in row:
            char_html = "&nbsp;" if state.char == " " else escape(state.char)
            style = "color:#888888;"
            if index == self._snapshot_current_pos:
                style = "color:#000000; background-color:#FFEB3B;"
            elif state.typed:
                style = "color:#4CAF50;" if state.correct else "color:#F44336;"
            anchor = "<a name='current-char'></a>" if index == self._snapshot_current_pos else ""
            html_parts.append(
                "<td style='text-align:center; vertical-align:bottom; padding:0 2px 0 2px;'>"
                f"{anchor}{self._wrap_cell_span(char_html, style)}</td>"
            )
        html_parts.append("</tr><tr>")
        for index, _ in row:
            is_current_cursor = index == self._snapshot_current_pos and self._cursor_visible
            html_parts.append(
                "<td style='text-align:center; vertical-align:top; padding:0 2px 0 2px; "
                f"border-top: 3px solid {'#40c4ff' if is_current_cursor else 'transparent'};"
                "font-size:1pt; line-height:0.2; height:4px;'>&nbsp;</td>"
            )
        html_parts.append("</tr><tr>")
        for _, state in row:
            wrong_html = "&nbsp;"
            if state.typed_char and state.typed_char != state.char and not state.correct:
                wrong_html = "&nbsp;" if state.typed_char == " " else escape(state.typed_char)
            html_parts.append(
                "<td style='text-align:center; vertical-align:top; padding:0 2px 0 2px; "
                "color:#F44336; font-size:14pt; font-weight:400;'>"
                f"{wrong_html}</td>"
            )
        html_parts.append("</tr></table>")
        return "".join(html_parts)


class TypingStatsWidget(QWidget):
    """Widget showing typing statistics."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 5, 10, 5)
        root_layout.setSpacing(4)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self._accuracy_label = QLabel("Accuracy: 100%")
        self._accuracy_label.setStyleSheet("color: #4CAF50; font-size: 14px;")

        self._progress_label = QLabel("0 / 0")
        self._progress_label.setStyleSheet("color: #888; font-size: 14px;")

        self._time_label = QLabel("Time: 00:00")
        self._time_label.setStyleSheet("color: #64b5f6; font-size: 14px;")

        self._speed_label = QLabel("Correct: 0.0 WPM")
        self._speed_label.setStyleSheet("color: #ce93d8; font-size: 14px;")

        self._error_speed_label = QLabel("Errors: 0.0 WPM")
        self._error_speed_label.setStyleSheet("color: #ef9a9a; font-size: 14px;")

        self._errors_label = QLabel("Errors: 0")
        self._errors_label.setStyleSheet("color: #F44336; font-size: 14px;")

        layout.addWidget(self._accuracy_label)
        layout.addStretch()
        layout.addWidget(self._progress_label)
        layout.addStretch()
        layout.addWidget(self._time_label)
        layout.addStretch()
        layout.addWidget(self._speed_label)
        layout.addStretch()
        layout.addWidget(self._error_speed_label)
        layout.addStretch()
        layout.addWidget(self._errors_label)

        self._speed_bar_label = QLabel("Speed")
        self._speed_bar_label.setStyleSheet("color: #9e9e9e; font-size: 12px;")
        self._speed_bar = QProgressBar()
        self._speed_bar.setRange(0, 100)
        self._speed_bar.setValue(0)
        self._speed_bar.setTextVisible(True)
        self._speed_bar.setFormat("0.0 WPM")
        self._speed_bar.setFixedHeight(10)
        self._speed_bar.setMaximumWidth(180)

        speed_row = QHBoxLayout()
        speed_row.setContentsMargins(0, 0, 0, 0)
        speed_row.setSpacing(8)
        speed_row.addWidget(self._speed_bar_label, 0)
        speed_row.addWidget(self._speed_bar, 0)
        speed_row.addStretch()

        root_layout.addLayout(layout)
        root_layout.addLayout(speed_row)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self._update_speed_bar(0.0)

    def update_stats(self, stats: TypingStats) -> None:
        """Update displayed statistics."""
        accuracy = stats.accuracy
        if accuracy >= 95:
            color = "#4CAF50"  # Green
        elif accuracy >= 80:
            color = "#FFEB3B"  # Yellow
        else:
            color = "#F44336"  # Red

        self._accuracy_label.setText(f"Accuracy: {accuracy:.1f}%")
        self._accuracy_label.setStyleSheet(f"color: {color}; font-size: 14px;")

        self._progress_label.setText(f"{stats.current_position} / {stats.total_chars}")
        elapsed_seconds = int(stats.elapsed_seconds)
        minutes, seconds = divmod(elapsed_seconds, 60)
        self._time_label.setText(f"Time: {minutes:02d}:{seconds:02d}")
        self._speed_label.setText(f"Correct: {stats.correct_wpm:.1f} WPM")
        self._error_speed_label.setText(f"Errors: {stats.error_wpm:.1f} WPM")
        self._errors_label.setText(f"Errors: {stats.error_chars}")
        self._update_speed_bar(stats.correct_wpm)

    def _update_speed_bar(self, wpm: float) -> None:
        """Update the live speed indicator."""
        clamped = max(0.0, min(100.0, wpm))
        if wpm >= 100.0:
            color = "#42a5f5"
        elif wpm >= 70.0:
            color = "#66bb6a"
        elif wpm >= 50.0:
            color = "#9ccc65"
        elif wpm >= 30.0:
            color = "#ffee58"
        elif wpm >= 20.0:
            color = "#ffb74d"
        else:
            color = "#ef5350"
        self._speed_bar.setValue(int(round(clamped)))
        self._speed_bar.setFormat(f"{wpm:.1f} WPM")
        self._speed_bar.setStyleSheet(
            f"""
            QProgressBar {{
                border: 1px solid #424242;
                border-radius: 5px;
                background-color: #1f1f1f;
                color: #d0d0d0;
                text-align: center;
                font-size: 10px;
            }}
            QProgressBar::chunk {{
                border-radius: 4px;
                background-color: {color};
            }}
            """
        )
