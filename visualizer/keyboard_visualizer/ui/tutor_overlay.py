"""Tutor overlay window for typing lessons."""

import time
from typing import Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QMenu,
    QLabel,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QSplitter,
    QPushButton,
    QComboBox,
)
from PySide6.QtGui import QColor, QMouseEvent, QAction, QPainter, QPalette, QFont
from PySide6.QtCore import Qt, QPoint, Signal, QTimer, QEvent

from .keyboard_widget import KeyboardWidget
from .typing_lesson import (
    TypingTextWidget,
    RichTypingTextWidget,
    TypingStatsWidget,
    TypingStats,
    ErrorMode,
    AttemptOutcome,
)
from .tutor_course import (
    TutorCourse,
    TutorCourseInfo,
    TutorLesson,
    TutorSection,
    list_available_courses,
    load_course,
)
from .hand_overlay import Finger
from ..input.scancode_map import ScancodeMapper
from ..models import Keymap
from ..models.layout import Layout
from ..utils import LessonProgressState, SoundPlayer, TutorStatsDatabase, TutorUser
from ..utils.tutor_hand_schemes import TutorHandSchemeSet, TutorKeySchemeAssignments

if TYPE_CHECKING:
    from ..input.keyboard_layout import KeyboardLayoutDetector


class TutorOverlayWindow(QWidget):
    """
    Overlay window for typing tutor mode.

    Layout (top to bottom):
    - Typing text widget (text to type)
    - Stats widget (accuracy, progress)
    - Keyboard with hands
    """

    closed = Signal()
    stats_requested = Signal()
    course_changed = Signal(str)

    def __init__(
        self,
        layout: Optional[Layout] = None,
        keymap: Optional[Keymap] = None,
        parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("tutorOverlayRoot")

        # Window flags: frameless, transparent, always on top
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
            QWidget#tutorOverlayRoot {
                background: transparent;
            }
            QSplitter {
                background: transparent;
            }
            QWidget#tutorOverlayLeftPanel,
            QWidget#tutorOverlayRightPanel {
                background: transparent;
                border: none;
            }
            """
        )

        # Current error mode
        self._error_mode = ErrorMode.CONTINUE

        # For dragging
        self._drag_position: Optional[QPoint] = None
        self._normal_geometry = None
        self._pseudo_maximized = False
        self._mirrored_keyboard_transform = None

        # Keymap for character to key mapping
        self._keymap: Optional[Keymap] = keymap
        self._char_to_key_map: dict[str, int] = {}
        self._scancode_mapper: ScancodeMapper | None = None
        self._layout_detector: Optional["KeyboardLayoutDetector"] = None
        self._layout_hkl: int | None = None
        self._caps_lock_on = False
        self._available_courses: list[TutorCourseInfo] = list_available_courses()
        self._current_course_id = 'en'
        self._current_course: TutorCourse | None = None
        self._course_sections: list[TutorSection] = []
        self._current_lesson: Optional[TutorLesson] = None
        self._sound_player = SoundPlayer()
        self._click_sounds_enabled = False
        self._correct_sound_path = ""
        self._incorrect_sound_path = ""
        self._lesson_start_sound_path = ""
        self._lesson_complete_sound_path = ""
        self._stats_db: TutorStatsDatabase | None = None
        self._tutor_user: TutorUser | None = None
        self._active_attempt_id: int | None = None
        self._last_timed_event_at: float | None = None

        # Create widgets
        self._lesson_tree = QTreeWidget()
        self._lesson_tree.setHeaderHidden(True)
        self._lesson_tree.setMinimumWidth(280)
        self._lesson_tree.setAlternatingRowColors(True)
        self._lesson_tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._section_label = QLabel("Typing Course")
        section_font = QFont()
        section_font.setPointSize(11)
        section_font.setBold(True)
        self._section_label.setFont(section_font)
        self._section_label.setStyleSheet("color: #d0d0d0;")

        self._finger_legend = QLabel("")
        self._finger_legend.setWordWrap(True)
        self._finger_legend.setStyleSheet("color: #d0d0d0; font-size: 12px;")
        self._course_combo = QComboBox()
        self._course_combo.setMinimumWidth(150)
        self._course_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for course in self._available_courses:
            self._course_combo.addItem(course.title, course.course_id)
        self._stats_button = QPushButton("Statistics")
        self._stats_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._stats_button.clicked.connect(self.stats_requested.emit)
        self._drag_handle = QLabel("Tutor")
        self._drag_handle.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._drag_handle.setMinimumHeight(30)
        self._drag_handle.setCursor(Qt.CursorShape.SizeAllCursor)
        self._drag_handle.setStyleSheet(
            "color: #b0bec5; font-size: 12px; padding-left: 8px;"
        )
        self._drag_handle.installEventFilter(self)
        self._close_btn = QPushButton("✕")
        self._close_btn.setToolTip("Close Tutor")
        self._close_btn.setFixedWidth(36)
        self._close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._close_btn.clicked.connect(self.close)
        self._maximize_btn = QPushButton("Maximize")
        self._maximize_btn.setFixedWidth(90)
        self._maximize_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._maximize_btn.clicked.connect(self._toggle_maximize_restore)

        self._lesson_label = QLabel("")
        lesson_font = QFont()
        lesson_font.setPointSize(16)
        lesson_font.setBold(True)
        self._lesson_label.setFont(lesson_font)
        self._lesson_label.setStyleSheet("color: white;")
        self._lesson_status_label = QLabel("Ready")
        self._lesson_status_label.setStyleSheet("color: #b0bec5; font-size: 12px;")

        self._prev_lesson_btn = QPushButton("Previous")
        self._prev_lesson_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._prev_lesson_btn.clicked.connect(lambda: self._navigate_lesson(-1))
        self._restart_lesson_btn = QPushButton("Restart")
        self._restart_lesson_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._restart_lesson_btn.clicked.connect(self._reset_lesson)
        self._next_lesson_btn = QPushButton("Next")
        self._next_lesson_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._next_lesson_btn.clicked.connect(lambda: self._navigate_lesson(1))

        self._text_widget = TypingTextWidget()
        self._rich_text_widget = RichTypingTextWidget()
        self._rich_text_widget.set_debug_log_callback(self._debug_log)
        self._stats_widget = TypingStatsWidget()
        self._keyboard_widget = KeyboardWidget()

        # Enable tutor mode on keyboard
        self._keyboard_widget.set_tutor_mode(True)

        # Make keyboard background transparent (keys remain opaque)
        self._keyboard_widget.set_transparent_background(True)

        # Layout
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)
        outer_layout.setSpacing(6)

        top_controls = QHBoxLayout()
        top_controls.addWidget(self._drag_handle, 1)
        top_controls.addWidget(self._maximize_btn, 0)
        top_controls.addWidget(self._close_btn, 0)
        outer_layout.addLayout(top_controls)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        splitter.setAutoFillBackground(False)

        left_panel = QWidget()
        left_panel.setObjectName("tutorOverlayLeftPanel")
        left_panel.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        left_panel.setAutoFillBackground(False)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        section_row = QHBoxLayout()
        section_row.addWidget(self._section_label, 1)
        section_row.addWidget(QLabel('Course:'), 0)
        section_row.addWidget(self._course_combo, 0)
        section_row.addWidget(self._stats_button, 0)
        left_layout.addLayout(section_row)
        left_layout.addWidget(self._finger_legend)
        left_layout.addWidget(self._lesson_tree, 1)

        right_panel = QWidget()
        right_panel.setObjectName("tutorOverlayRightPanel")
        right_panel.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        right_panel.setAutoFillBackground(False)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)
        right_layout.addWidget(self._lesson_label)
        right_layout.addWidget(self._lesson_status_label)
        lesson_nav_row = QHBoxLayout()
        lesson_nav_row.addWidget(self._prev_lesson_btn)
        lesson_nav_row.addWidget(self._restart_lesson_btn)
        lesson_nav_row.addWidget(self._next_lesson_btn)
        lesson_nav_row.addStretch()
        right_layout.addLayout(lesson_nav_row)
        right_layout.addWidget(self._text_widget)
        right_layout.addWidget(self._rich_text_widget)
        right_layout.addWidget(self._stats_widget)
        right_layout.addWidget(self._keyboard_widget, 1)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 900])
        main_layout.addWidget(splitter, 1)
        outer_layout.addLayout(main_layout, 1)

        # Connect signals
        self._text_widget.char_expected.connect(self._on_char_expected)
        self._text_widget.lesson_complete.connect(self._on_lesson_complete)
        self._lesson_tree.itemSelectionChanged.connect(self._on_lesson_selection_changed)
        self._course_combo.currentIndexChanged.connect(self._on_course_combo_changed)
        self._stats_refresh_timer = QTimer(self)
        self._stats_refresh_timer.setInterval(200)
        self._stats_refresh_timer.timeout.connect(self._refresh_stats)
        self._stats_refresh_timer.start()

        # Set initial size
        self.resize(1200, 700)

        # Apply layout and keymap if provided
        if layout:
            self.set_layout(layout)
        if keymap:
            self.set_keymap(keymap)

        self._reload_course()

    def _sync_text_views(self) -> None:
        """Keep experimental text renderer in sync with the legacy widget."""
        text, char_states, current_pos = self._text_widget.get_render_snapshot()
        self._rich_text_widget.sync_from_snapshot(text, char_states, current_pos)

    def _debug_log(self, message: str) -> None:
        """Forward debug messages when a logger is attached."""
        callback = getattr(self, "_debug_log_callback", None)
        if callable(callback):
            callback(message)

    def set_debug_log_callback(self, callback) -> None:
        """Attach a debug logger used by experimental tutor subcomponents."""
        self._debug_log_callback = callback

    def set_layout(self, layout: Layout) -> None:
        """Set the keyboard layout."""
        self._keyboard_widget.set_layout(layout)

    def keyboard_widget(self) -> KeyboardWidget:
        """Expose the internal keyboard widget for shared styling."""
        return self._keyboard_widget

    def set_keymap(self, keymap: Keymap) -> None:
        """Set the keymap and build character to key mapping."""
        self._keymap = keymap
        self._keyboard_widget.set_keymap(keymap)
        self._scancode_mapper = ScancodeMapper(keymap, base_layer=0)
        self._build_char_to_key_map()
        # Update text widget with mapping callback
        self._text_widget.set_char_to_key_callback(self._get_key_for_char)
        self._reload_course()

    def set_layer(self, layer_index: int) -> None:
        """Set the displayed layer."""
        self._keyboard_widget.set_layer(layer_index)

    def set_keyboard_view_state(self, size, transform) -> None:
        """Mirror the main window keyboard size/transform inside tutor."""
        self._mirrored_keyboard_transform = transform
        self._keyboard_widget.setMinimumSize(size)
        self._keyboard_widget.resize(size)
        self._keyboard_widget.set_locked_transform(transform)

    def set_show_hold_labels(self, enabled: bool) -> None:
        """Show or hide hold labels on tutor keys."""
        self._keyboard_widget.set_show_hold_labels(enabled)

    def set_show_finger_movement_arrows(self, enabled: bool) -> None:
        """Show or hide finger movement arrows on tutor keys."""
        self._keyboard_widget.set_show_finger_movement_arrows(enabled)

    def set_click_sounds(self, enabled: bool, correct_sound: str, incorrect_sound: str) -> None:
        """Configure tutor click sounds."""
        self._click_sounds_enabled = enabled
        self._correct_sound_path = correct_sound
        self._incorrect_sound_path = incorrect_sound

    def set_lesson_sounds(self, start_sound: str, complete_sound: str) -> None:
        """Configure tutor lesson start and completion sounds."""
        self._lesson_start_sound_path = start_sound
        self._lesson_complete_sound_path = complete_sound

    def set_finger_palette(self, palette: dict[Finger, QColor]) -> None:
        """Set tutor finger colors and refresh legend."""
        self._keyboard_widget.set_finger_palette(palette)
        self._update_finger_legend(palette)

    def set_tutor_scheme_data(
        self,
        schemes: TutorHandSchemeSet | None,
        assignments: TutorKeySchemeAssignments,
    ) -> None:
        """Set tutor hand scheme data."""
        self._keyboard_widget.set_tutor_scheme_data(schemes, assignments)

    def set_stats_context(
        self,
        stats_db: TutorStatsDatabase | None,
        tutor_user: TutorUser | None,
    ) -> None:
        """Set persistence objects used for tutor statistics."""
        self._stats_db = stats_db
        self._tutor_user = tutor_user
        self._refresh_lesson_tree_progress()

    def set_course(self, course_id: str) -> None:
        """Switch to another tutor course."""
        normalized = (course_id or 'en').strip().lower()
        if normalized not in {course.course_id for course in self._available_courses}:
            normalized = 'en'
        combo_index = self._course_combo.findData(normalized)
        if combo_index >= 0 and combo_index != self._course_combo.currentIndex():
            self._course_combo.blockSignals(True)
            self._course_combo.setCurrentIndex(combo_index)
            self._course_combo.blockSignals(False)
        if normalized == self._current_course_id and self._current_course is not None:
            return
        self._current_course_id = normalized
        self._finalize_current_attempt(False)
        self._reload_course()
        self.course_changed.emit(self._current_course_id)

    def current_course_id(self) -> str:
        """Return the currently selected tutor course id."""
        return self._current_course_id

    def _build_char_to_key_map(self) -> None:
        """Build mapping from lesson characters to visual key indices."""
        self._char_to_key_map.clear()

        if not self._keymap:
            return

        if self._layout_detector and self._scancode_mapper:
            char_map = self._layout_detector.build_char_map(
                hkl=self._layout_hkl,
                caps_lock=self._caps_lock_on,
            )
            for vk_code, chars in char_map.items():
                key_index = self._scancode_mapper.vk_to_key_index(vk_code)
                if key_index is None:
                    continue
                for char in chars:
                    if char:
                        self._char_to_key_map.setdefault(char, key_index)

        if self._char_to_key_map:
            return

        for layer in self._keymap.layers:
            for key_index, keycode in enumerate(layer):
                for char in self._keycode_to_chars(keycode):
                    self._char_to_key_map.setdefault(char, key_index)

    def _keycode_to_chars(self, keycode: str) -> list[str]:
        """Convert a QMK keycode to one or more display characters."""
        if not keycode:
            return []

        # Handle MT() - Mod-Tap
        if keycode.startswith("MT(") or keycode.startswith("LT("):
            # Extract the tap key: MT(MOD_xxx, KC_X) -> KC_X
            parts = keycode.split(",")
            if len(parts) >= 2:
                tap_key = parts[-1].strip().rstrip(")")
                keycode = tap_key

        # Handle basic keycodes
        if keycode.startswith("KC_"):
            key = keycode[3:]
            if len(key) == 1 and key.isalpha():
                return [key.lower(), key.upper()]
            if key.isdigit():
                shifted = {
                    "1": "!", "2": "@", "3": "#", "4": "$", "5": "%",
                    "6": "^", "7": "&", "8": "*", "9": "(", "0": ")",
                }
                result = [key]
                if key in shifted:
                    result.append(shifted[key])
                return result
            special = {
                "SPACE": [" "], "SPC": [" "],
                "COMMA": [",", "<"], "COMM": [",", "<"],
                "DOT": [".", ">"], "PERIOD": [".", ">"],
                "SLASH": ["/", "?"], "SLSH": ["/", "?"],
                "SEMICOLON": [";", ":"], "SCLN": [";", ":"],
                "QUOTE": ["'", '"'], "QUOT": ["'", '"'],
                "MINUS": ["-", "_"], "MINS": ["-", "_"],
                "EQUAL": ["=", "+"], "EQL": ["=", "+"],
                "GRV": ["`", "~"],
                "LBRC": ["[", "{"],
                "RBRC": ["]", "}"],
                "BSLS": ["\\", "|"],
            }
            return special.get(key, [])

        return []

    def _get_key_for_char(self, char: str) -> Optional[int]:
        """Get key index for a character."""
        return self._char_to_key_map.get(char)

    def _reload_course(self) -> None:
        """Reload the course tree, preserving current lesson if possible."""
        current_lesson_id = self._current_lesson.lesson_id if self._current_lesson else None
        self._current_course = load_course(self._current_course_id, self._keymap)
        self._course_sections = self._current_course.sections
        self._section_label.setText(self._current_course.title)
        self._populate_lesson_tree(current_lesson_id)

    def _populate_lesson_tree(self, current_lesson_id: Optional[int] = None) -> None:
        """Populate sidebar lesson tree."""
        self._lesson_tree.clear()
        first_playable_item: Optional[QTreeWidgetItem] = None
        selected_item: Optional[QTreeWidgetItem] = None

        for section in self._course_sections:
            section_item = QTreeWidgetItem([section.title])
            section_item.setFlags(section_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            section_font = section_item.font(0)
            section_font.setBold(True)
            section_item.setFont(0, section_font)
            self._lesson_tree.addTopLevelItem(section_item)

            for lesson in section.lessons:
                prefix = {
                    "typing": "",
                    "video": "[Video] ",
                }.get(lesson.lesson_type, f"[{lesson.lesson_type.title()}] ")
                lesson_item = QTreeWidgetItem([prefix + lesson.title])
                lesson_item.setData(0, Qt.ItemDataRole.UserRole, lesson)
                lesson_item.setData(0, Qt.ItemDataRole.UserRole + 1, prefix)
                if not lesson.playable:
                    lesson_item.setFlags(lesson_item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                    lesson_item.setForeground(0, QColor("#6f6f6f"))
                elif first_playable_item is None:
                    first_playable_item = lesson_item

                section_item.addChild(lesson_item)
                if current_lesson_id and lesson.lesson_id == current_lesson_id:
                    selected_item = lesson_item

            section_item.setExpanded(section.title == "Home Row")

        target_item = selected_item or first_playable_item
        self._refresh_lesson_tree_progress()
        if target_item is not None:
            self._lesson_tree.setCurrentItem(target_item)
            self._load_lesson_from_item(target_item)

    def _load_lesson_from_item(self, item: QTreeWidgetItem) -> None:
        """Load lesson from selected tree item."""
        lesson = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(lesson, TutorLesson) or not lesson.playable:
            return

        self._finalize_current_attempt(False)

        self._current_lesson = lesson
        parent = item.parent()
        self._section_label.setText(parent.text(0) if parent else "Typing Course")
        self._lesson_label.setText(lesson.title)
        self._text_widget.set_text(lesson.text)
        self._sync_text_views()
        self._stats_widget.update_stats(self._text_widget.get_stats())
        self._last_timed_event_at = None
        self._update_lesson_status()
        self._update_navigation_buttons()
        self._play_lesson_start_sound()

    def _on_lesson_selection_changed(self) -> None:
        """Handle left sidebar lesson selection."""
        items = self._lesson_tree.selectedItems()
        if items:
            self._load_lesson_from_item(items[0])

    def _on_course_combo_changed(self) -> None:
        """Reload tutor content when the selected course changes."""
        course_id = str(self._course_combo.currentData() or 'en')
        if course_id != self._current_course_id:
            self.set_course(course_id)

    def _on_char_expected(self, char: str, key_index: int) -> None:
        """Handle expected character signal - show finger hint."""
        if key_index >= 0:
            self._keyboard_widget.show_finger_hint(key_index)

    def _on_lesson_complete(self, stats: TypingStats) -> None:
        """Handle lesson completion."""
        self._stats_widget.update_stats(stats)
        self._sync_text_views()
        self._keyboard_widget.hide_finger_hints()
        self._finalize_current_attempt(True)
        self._update_lesson_status()
        self._update_navigation_buttons()
        self._refresh_lesson_tree_progress()
        self._play_lesson_complete_sound()

    def _play_lesson_start_sound(self) -> None:
        """Play a short cue when a lesson is loaded or restarted."""
        if self._lesson_start_sound_path:
            self._sound_player.play_file(self._lesson_start_sound_path)

    def _play_lesson_complete_sound(self) -> None:
        """Play a short cue when a lesson is completed."""
        if self._lesson_complete_sound_path:
            self._sound_player.play_file(self._lesson_complete_sound_path)

    def _refresh_stats(self) -> None:
        """Refresh lesson stats while the overlay is visible."""
        stats = self._text_widget.get_stats()
        self._stats_widget.update_stats(stats)
        self._sync_text_views()
        self._update_lesson_status(stats)

    def _update_finger_legend(self, palette: dict[Finger, QColor]) -> None:
        """Render a compact legend for tutor finger colors."""
        logical = [
            ("Pinky", palette.get(Finger.LEFT_PINKY)),
            ("Ring", palette.get(Finger.LEFT_RING)),
            ("Middle", palette.get(Finger.LEFT_MIDDLE)),
            ("Index", palette.get(Finger.LEFT_INDEX)),
            ("Thumb", palette.get(Finger.LEFT_THUMB)),
        ]
        parts = []
        for label, color in logical:
            if color is None:
                continue
            parts.append(
                f"<span style='color:{color.name()}; font-weight:600;'>&#9675;</span> {label}"
            )
        self._finger_legend.setText("  ".join(parts))

    def navigate_previous_lesson(self) -> None:
        """Move to the previous playable lesson."""
        self._navigate_lesson(-1)

    def restart_current_lesson(self) -> None:
        """Restart the currently selected lesson."""
        self._reset_lesson()

    def navigate_next_lesson(self) -> None:
        """Move to the next playable lesson."""
        self._navigate_lesson(1)

    def handle_keypress(self, char: str, key_index: int | None = None) -> bool:
        """Handle a keypress during typing lesson."""
        expected_char = self._text_widget.get_expected_char() or ""
        position_index = self._text_widget.get_current_position()
        now = time.monotonic()

        # Return fingers to neutral before the next expected symbol is emitted.
        self._keyboard_widget.hide_finger_hints()

        result = self._text_widget.handle_keypress(char)
        outcome = self._text_widget.get_last_attempt_outcome()
        stats = self._text_widget.get_stats()
        self._stats_widget.update_stats(self._text_widget.get_stats())
        self._sync_text_views()
        if key_index is not None:
            if outcome == AttemptOutcome.CORRECT:
                self._keyboard_widget.show_tutor_key_feedback(key_index, True)
            elif outcome == AttemptOutcome.ERROR:
                self._keyboard_widget.show_tutor_key_feedback(key_index, False)
        if self._click_sounds_enabled:
            if outcome == AttemptOutcome.CORRECT:
                self._sound_player.play_file(self._correct_sound_path)
            elif outcome == AttemptOutcome.ERROR:
                self._sound_player.play_file(self._incorrect_sound_path)

        if outcome in {AttemptOutcome.CORRECT, AttemptOutcome.ERROR}:
            self._record_attempt_event(
                expected_char=expected_char,
                typed_char=char,
                position_index=position_index,
                is_correct=(outcome == AttemptOutcome.CORRECT),
                event_time=now,
                stats=stats,
            )
        return result

    def _record_attempt_event(
        self,
        *,
        expected_char: str,
        typed_char: str,
        position_index: int,
        is_correct: bool,
        event_time: float,
        stats: TypingStats,
    ) -> None:
        """Persist one tutor key event if stats context is available."""
        if self._stats_db is None or self._tutor_user is None or self._current_lesson is None:
            return

        if self._active_attempt_id is None:
            if not is_correct:
                return
            self._active_attempt_id = self._stats_db.start_attempt(
                self._tutor_user.user_id,
                self._current_course_id,
                self._current_lesson.lesson_id,
                self._current_lesson.title,
                self._section_label.text(),
                stats.total_chars,
            )

        latency_ms: int | None = None
        if self._last_timed_event_at is not None:
            latency_ms = max(0, int((event_time - self._last_timed_event_at) * 1000))
        self._last_timed_event_at = event_time

        self._stats_db.add_key_event(
            user_id=self._tutor_user.user_id,
            course_id=self._current_course_id,
            attempt_id=self._active_attempt_id,
            position_index=position_index,
            expected_char=expected_char,
            typed_char=typed_char,
            is_correct=is_correct,
            latency_ms=latency_ms,
        )

    def _finalize_current_attempt(self, completed: bool) -> None:
        """Persist final attempt stats if one is currently active."""
        if self._active_attempt_id is None:
            self._last_timed_event_at = None
            return

        stats = self._text_widget.get_stats()
        self._stats_db.finish_attempt(
            self._active_attempt_id,
            total_chars=stats.total_chars,
            correct_chars=stats.correct_chars,
            error_chars=stats.error_chars,
            accuracy=stats.accuracy,
            correct_wpm=stats.correct_wpm,
            error_wpm=stats.error_wpm,
            completed=completed and stats.completed,
        )
        self._active_attempt_id = None
        self._last_timed_event_at = None

    def _update_lesson_status(self, stats: TypingStats | None = None) -> None:
        """Refresh the lesson status line."""
        stats = stats or self._text_widget.get_stats()
        if stats.completed:
            self._lesson_status_label.setText("Lesson complete")
            self._lesson_status_label.setStyleSheet("color: #66bb6a; font-size: 12px; font-weight: 600;")
        elif stats.started:
            self._lesson_status_label.setText("Lesson in progress")
            self._lesson_status_label.setStyleSheet("color: #64b5f6; font-size: 12px; font-weight: 600;")
        else:
            self._lesson_status_label.setText("Ready. The lesson starts on the first correct symbol.")
            self._lesson_status_label.setStyleSheet("color: #b0bec5; font-size: 12px;")

    def _iter_playable_items(self) -> list[QTreeWidgetItem]:
        """Return all playable lesson items in visual order."""
        items: list[QTreeWidgetItem] = []
        for section_index in range(self._lesson_tree.topLevelItemCount()):
            section_item = self._lesson_tree.topLevelItem(section_index)
            for row in range(section_item.childCount()):
                child = section_item.child(row)
                lesson = child.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(lesson, TutorLesson) and lesson.playable:
                    items.append(child)
        return items

    def _navigate_lesson(self, delta: int) -> None:
        """Move to the previous or next playable lesson."""
        items = self._iter_playable_items()
        if not items:
            return
        current_item = self._lesson_tree.currentItem()
        if current_item not in items:
            target_item = items[0]
        else:
            current_index = items.index(current_item)
            target_index = max(0, min(len(items) - 1, current_index + delta))
            target_item = items[target_index]
        if target_item is not current_item:
            self._lesson_tree.setCurrentItem(target_item)
            self._load_lesson_from_item(target_item)
        self._update_navigation_buttons()

    def _update_navigation_buttons(self) -> None:
        """Enable or disable lesson navigation buttons."""
        items = self._iter_playable_items()
        if not items:
            self._prev_lesson_btn.setEnabled(False)
            self._next_lesson_btn.setEnabled(False)
            self._restart_lesson_btn.setEnabled(False)
            return
        current_item = self._lesson_tree.currentItem()
        if current_item not in items:
            self._prev_lesson_btn.setEnabled(False)
            self._next_lesson_btn.setEnabled(False)
        else:
            current_index = items.index(current_item)
            self._prev_lesson_btn.setEnabled(current_index > 0)
            self._next_lesson_btn.setEnabled(current_index < len(items) - 1)
        self._restart_lesson_btn.setEnabled(self._current_lesson is not None)

    def _refresh_lesson_tree_progress(self) -> None:
        """Apply per-user lesson progress markers to the lesson tree."""
        progress_map: dict[int, LessonProgressState] = {}
        if self._stats_db is not None and self._tutor_user is not None:
            progress_map = self._stats_db.get_lesson_progress_map(
                self._tutor_user.user_id,
                self._current_course_id,
            )

        for section_index in range(self._lesson_tree.topLevelItemCount()):
            section_item = self._lesson_tree.topLevelItem(section_index)
            for row in range(section_item.childCount()):
                item = section_item.child(row)
                lesson = item.data(0, Qt.ItemDataRole.UserRole)
                prefix = str(item.data(0, Qt.ItemDataRole.UserRole + 1) or "")
                if not isinstance(lesson, TutorLesson):
                    continue
                if not lesson.playable:
                    continue

                state = progress_map.get(lesson.lesson_id)
                if state is None:
                    marker = ""
                    color = QColor("#d0d0d0")
                    suffix = ""
                elif state.completed:
                    marker = "✓ "
                    color = self._color_for_accuracy(state.average_accuracy)
                    suffix = self._format_lesson_metrics_suffix(
                        state.average_accuracy,
                        state.average_correct_wpm,
                    )
                else:
                    marker = "• "
                    color = self._color_for_accuracy(state.average_accuracy)
                    suffix = self._format_lesson_metrics_suffix(
                        state.average_accuracy,
                        state.average_correct_wpm,
                    )

                display_text = f"{marker}{prefix}{lesson.title}{suffix}"
                item.setText(0, display_text)
                item.setToolTip(0, display_text)
                item.setForeground(0, color)

    @staticmethod
    def _color_for_accuracy(accuracy: float) -> QColor:
        """Return a coarse lesson-tree color for average accuracy."""
        if accuracy >= 97.0:
            return QColor("#66bb6a")
        if accuracy >= 90.0:
            return QColor("#d4c15a")
        return QColor("#e57373")

    @staticmethod
    def _format_lesson_metrics_suffix(average_accuracy: float, correct_wpm: float) -> str:
        """Format accuracy and speed as a compact suffix for the lesson tree."""
        parts: list[str] = []
        if average_accuracy > 0:
            parts.append(f"{int(round(average_accuracy))}%")
        if correct_wpm > 0:
            parts.append(f"{int(round(correct_wpm))}w")
        if not parts:
            return ""
        return "   " + "   ".join(parts)

    def highlight_key(
        self,
        key_index: int,
        pressed: bool,
        hold_mode: bool = False,
        active_layer: int | None = None,
    ) -> None:
        """Highlight a key."""
        self._keyboard_widget.highlight_key(key_index, pressed, hold_mode, active_layer)

    def set_error_mode(self, mode: ErrorMode) -> None:
        """Set how errors are handled."""
        self._error_mode = mode
        self._text_widget.set_error_mode(mode)
        self._sync_text_views()

    def set_os_layout_mode(
        self,
        enabled: bool,
        layout_detector: Optional["KeyboardLayoutDetector"] = None,
        hkl: Optional[int] = None
    ) -> None:
        """Enable or disable OS keyboard layout mode."""
        self._layout_detector = layout_detector if enabled else None
        self._layout_hkl = hkl if enabled else None
        self._keyboard_widget.set_os_layout_mode(enabled, layout_detector, hkl)
        self._build_char_to_key_map()
        self._text_widget.set_char_to_key_callback(self._get_key_for_char)
        self._text_widget.refresh_key_indices()
        self._sync_text_views()

    def set_caps_lock_mode(self, caps_lock_on: bool) -> None:
        """Set Caps Lock mode for displayed key labels."""
        self._caps_lock_on = caps_lock_on
        self._keyboard_widget.set_caps_lock_mode(caps_lock_on)
        self._build_char_to_key_map()
        self._text_widget.set_char_to_key_callback(self._get_key_for_char)
        self._text_widget.refresh_key_indices()
        self._sync_text_views()

    # Dragging support
    def _on_drag_started(self, global_pos: QPoint) -> None:
        self._drag_position = global_pos - self.frameGeometry().topLeft()

    def _on_drag_moved(self, global_pos: QPoint) -> None:
        if self._drag_position:
            self.move(global_pos - self._drag_position)

    def _on_drag_ended(self) -> None:
        self._drag_position = None

    def _toggle_maximize_restore(self) -> None:
        """Toggle between current size and screen-filling size without a window frame."""
        if not self._pseudo_maximized:
            self._normal_geometry = self.geometry()
            screen = self.screen()
            if screen is not None:
                self.setGeometry(screen.availableGeometry())
            self._keyboard_widget.unlock_transform()
            self._pseudo_maximized = True
            self._maximize_btn.setText("Restore")
            return

        if self._normal_geometry is not None:
            self.setGeometry(self._normal_geometry)
        if self._mirrored_keyboard_transform is not None:
            self._keyboard_widget.set_locked_transform(self._mirrored_keyboard_transform)
        self._pseudo_maximized = False
        self._maximize_btn.setText("Maximize")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_position:
            self.move(event.globalPosition().toPoint() - self._drag_position)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_position = None

    def eventFilter(self, watched, event) -> bool:
        """Use the dedicated top bar handle as a reliable drag area."""
        if watched is self._drag_handle:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_position and event.buttons() & Qt.MouseButton.LeftButton:
                self.move(event.globalPosition().toPoint() - self._drag_position)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_position = None
                return True
        return super().eventFilter(watched, event)

    def _show_context_menu(self, position: QPoint) -> None:
        """Show context menu with options."""
        menu = QMenu(self)

        # Error mode submenu with checkmarks
        error_menu = menu.addMenu("Error Mode")

        continue_action = error_menu.addAction("Continue on error")
        continue_action.setCheckable(True)
        continue_action.setChecked(self._error_mode == ErrorMode.CONTINUE)
        continue_action.triggered.connect(lambda: self.set_error_mode(ErrorMode.CONTINUE))

        wait_action = error_menu.addAction("Wait for correct key")
        wait_action.setCheckable(True)
        wait_action.setChecked(self._error_mode == ErrorMode.WAIT)
        wait_action.triggered.connect(lambda: self.set_error_mode(ErrorMode.WAIT))

        menu.addSeparator()

        # Reset lesson
        reset_action = menu.addAction("Reset Lesson")
        reset_action.triggered.connect(self._reset_lesson)

        menu.addSeparator()

        # Opacity submenu
        opacity_menu = menu.addMenu("Window Opacity")
        current_opacity = int(self.windowOpacity() * 100)
        for opacity in [100, 80, 60, 40]:
            action = opacity_menu.addAction(f"{opacity}%")
            action.setCheckable(True)
            action.setChecked(current_opacity == opacity)
            action.triggered.connect(lambda checked, o=opacity: self.setWindowOpacity(o / 100))

        menu.addSeparator()

        # Close
        close_action = QAction("Close Tutor", self)
        close_action.triggered.connect(self.close)
        menu.addAction(close_action)

        menu.exec(position)

    def closeEvent(self, event) -> None:
        """Emit signal when closed."""
        self._finalize_current_attempt(False)
        self.closed.emit()
        super().closeEvent(event)

    def _reset_lesson(self) -> None:
        """Reset lesson and finish any in-progress attempt as incomplete."""
        self._finalize_current_attempt(False)
        self._text_widget.reset()
        self._sync_text_views()
        self._stats_widget.update_stats(self._text_widget.get_stats())
        self._keyboard_widget.hide_finger_hints()
        self._update_lesson_status()
