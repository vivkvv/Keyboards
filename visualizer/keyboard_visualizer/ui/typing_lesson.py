"""Typing lesson widget for tutor mode."""

from enum import Enum
from typing import Optional, Callable
from dataclasses import dataclass, field
import time

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout
from PySide6.QtGui import QFont, QColor, QPainter, QFontMetrics
from PySide6.QtCore import Qt, Signal, QRect


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

    def set_text(self, text: str) -> None:
        """Set the text to type."""
        self._text = text
        self._char_states = [CharState(char=c) for c in text]
        self._current_pos = 0
        self._stats = TypingStats(total_chars=len(text))
        self._started_at = None
        self._completed_at = None
        self._last_attempt_outcome = AttemptOutcome.IGNORED

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

            if self._error_mode == ErrorMode.CONTINUE:
                self._char_states[self._current_pos].typed = True
                self._char_states[self._current_pos].correct = False
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
        self._current_pos = 0
        self._stats = TypingStats(total_chars=len(self._char_states))
        self._started_at = None
        self._completed_at = None
        self._last_attempt_outcome = AttemptOutcome.IGNORED
        self.update()
        self._emit_current_char()

    def get_last_attempt_outcome(self) -> AttemptOutcome:
        """Return the outcome of the most recent keypress attempt."""
        return self._last_attempt_outcome

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

    def paintEvent(self, event) -> None:
        """Paint the text with colored characters."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self._font)

        metrics = QFontMetrics(self._font)
        char_height = metrics.height()

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
            x += char_width

        painter.end()


class TypingStatsWidget(QWidget):
    """Widget showing typing statistics."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

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

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

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
