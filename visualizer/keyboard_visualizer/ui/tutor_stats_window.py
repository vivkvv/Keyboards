"""Window showing tutor statistics."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QGridLayout,
    QGroupBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QMessageBox,
    QInputDialog,
)
from PySide6.QtCore import Qt

from ..utils import (
    LessonStatRow,
    SectionStatRow,
    SymbolStatRow,
    TutorOverview,
    TutorStatsDatabase,
    TutorUser,
)
from .tutor_course import list_available_courses


class TutorStatsWindow(QWidget):
    """Top-level tutor statistics window."""

    def __init__(
        self,
        stats_db: TutorStatsDatabase,
        current_user: TutorUser | None = None,
        current_course_id: str = "en",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._stats_db = stats_db
        self._current_user: TutorUser | None = current_user
        self._current_course_id = (current_course_id or "en").strip().lower()

        self.setWindowTitle("Tutor Statistics")
        self.resize(1050, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("User:"))
        self._user_combo = QComboBox()
        self._user_combo.currentIndexChanged.connect(self._on_user_changed)
        top_row.addWidget(self._user_combo, 1)
        self._new_user_btn = QPushButton("New User")
        self._new_user_btn.clicked.connect(self._create_user)
        top_row.addWidget(self._new_user_btn)
        top_row.addWidget(QLabel("Course:"))
        self._course_combo = QComboBox()
        self._course_combo.currentIndexChanged.connect(self._on_course_changed)
        top_row.addWidget(self._course_combo)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        top_row.addWidget(self._refresh_btn)
        root.addLayout(top_row)

        summary_group = QGroupBox("Summary")
        summary_layout = QGridLayout(summary_group)
        self._summary_labels: dict[str, QLabel] = {}
        labels = [
            ("total_attempts", "Attempts"),
            ("completed_attempts", "Completed"),
            ("unique_lessons_completed", "Lessons Completed"),
            ("average_accuracy", "Avg Accuracy"),
            ("average_correct_wpm", "Avg Correct WPM"),
            ("total_correct_chars", "Correct"),
            ("total_error_chars", "Errors"),
        ]
        for row, (key, title) in enumerate(labels):
            title_label = QLabel(f"{title}:")
            title_label.setStyleSheet("font-weight: 600;")
            value_label = QLabel("-")
            value_label.setStyleSheet("color: #d0d0d0;")
            summary_layout.addWidget(title_label, row // 2, (row % 2) * 2)
            summary_layout.addWidget(value_label, row // 2, (row % 2) * 2 + 1)
            self._summary_labels[key] = value_label
        root.addWidget(summary_group)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs, 1)

        self._sections_table = self._build_table(
            ["Section", "Lessons", "Completed", "Attempts", "Avg Accuracy", "Avg WPM"]
        )
        self._tabs.addTab(self._sections_table, "Sections")

        self._lessons_table = self._build_table(
            ["Section", "Lesson", "Attempts", "Completed", "Best Accuracy", "Best WPM", "Last Played"]
        )
        self._tabs.addTab(self._lessons_table, "Lessons")

        self._symbols_table = self._build_table(
            ["Symbol", "Samples", "Valid Timing %", "Avg ms", "StdDev ms", "Error %"]
        )
        self._tabs.addTab(self._symbols_table, "Symbols")

        self._populate_users()
        self._populate_courses()
        self.refresh()

    def set_overlay_mode(self, enabled: bool) -> None:
        """Keep the stats window above tutor when tutor runs as an overlay."""
        self.setWindowFlag(Qt.WindowType.Tool, enabled)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if self.isVisible():
            self.show()

    def _build_table(self, headers: list[str]) -> QTableWidget:
        """Create a read-only table with stretch headers."""
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setSortingEnabled(True)
        header = table.horizontalHeader()
        for idx in range(len(headers)):
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.Stretch)
        return table

    def _populate_courses(self) -> None:
        """Load available tutor courses into the combo box."""
        courses = list_available_courses()
        self._course_combo.blockSignals(True)
        self._course_combo.clear()
        for course in courses:
            self._course_combo.addItem(course.title, course.course_id)
        index = self._course_combo.findData(self._current_course_id)
        self._course_combo.setCurrentIndex(index if index >= 0 else 0)
        if self._course_combo.currentData() is not None:
            self._current_course_id = str(self._course_combo.currentData())
        self._course_combo.blockSignals(False)

    def _on_course_changed(self) -> None:
        """Handle course selection change."""
        course_id = self._course_combo.currentData()
        self._current_course_id = str(course_id or 'en')
        self.refresh()

    def set_current_course(self, course_id: str | None) -> None:
        """Switch currently displayed tutor course."""
        normalized = (course_id or 'en').strip().lower()
        self._current_course_id = normalized
        index = self._course_combo.findData(normalized)
        if index >= 0 and index != self._course_combo.currentIndex():
            self._course_combo.setCurrentIndex(index)
        else:
            self.refresh()

    def _populate_users(self) -> None:
        """Load available users into the combo box."""
        users = self._stats_db.list_users()
        self._user_combo.blockSignals(True)
        self._user_combo.clear()
        for user in users:
            self._user_combo.addItem(user.name, user.user_id)
        self._user_combo.blockSignals(False)

        if not users:
            self._current_user = None
            return

        if self._current_user is not None:
            current_index = self._user_combo.findData(self._current_user.user_id)
            if current_index >= 0:
                self._user_combo.setCurrentIndex(current_index)
                return

        self._user_combo.setCurrentIndex(0)
        self._current_user = TutorUser(
            user_id=int(self._user_combo.currentData()),
            name=self._user_combo.currentText(),
        )

    def _create_user(self) -> None:
        """Create a new tutor user from this window."""
        name, ok = QInputDialog.getText(self, "New Tutor User", "User name:")
        if not ok:
            return
        clean_name = name.strip()
        if not clean_name:
            QMessageBox.warning(self, "Tutor User", "User name must not be empty.")
            return
        try:
            user = self._stats_db.create_user(clean_name)
        except Exception as exc:
            QMessageBox.warning(self, "Tutor User", str(exc))
            return
        self._current_user = user
        self._populate_users()
        current_index = self._user_combo.findData(user.user_id)
        if current_index >= 0:
            self._user_combo.setCurrentIndex(current_index)
        self.refresh()

    def _on_user_changed(self) -> None:
        """Handle user selection change."""
        user_id = self._user_combo.currentData()
        if user_id is None:
            self._current_user = None
        else:
            self._current_user = TutorUser(user_id=int(user_id), name=self._user_combo.currentText())
        self.refresh()

    def refresh(self) -> None:
        """Reload all statistics for the current user."""
        self._populate_summary()
        self._populate_sections()
        self._populate_lessons()
        self._populate_symbols()

    def set_current_user(self, user: TutorUser | None) -> None:
        """Switch currently displayed user."""
        self._current_user = user
        self._populate_users()
        self._populate_courses()
        self.refresh()

    def _populate_summary(self) -> None:
        """Fill summary labels."""
        if self._current_user is None:
            for label in self._summary_labels.values():
                label.setText("-")
            return

        overview = self._stats_db.get_overview(self._current_user.user_id, self._current_course_id)
        self._summary_labels["total_attempts"].setText(str(overview.total_attempts))
        self._summary_labels["completed_attempts"].setText(str(overview.completed_attempts))
        self._summary_labels["unique_lessons_completed"].setText(str(overview.unique_lessons_completed))
        self._summary_labels["average_accuracy"].setText(f"{overview.average_accuracy:.1f}%")
        self._summary_labels["average_correct_wpm"].setText(f"{overview.average_correct_wpm:.1f}")
        total_chars = overview.total_correct_chars + overview.total_error_chars
        if total_chars > 0:
            correct_pct = (overview.total_correct_chars / total_chars) * 100.0
            error_pct = (overview.total_error_chars / total_chars) * 100.0
            self._summary_labels["total_correct_chars"].setText(f"{correct_pct:.1f}%")
            self._summary_labels["total_error_chars"].setText(f"{error_pct:.1f}%")
        else:
            self._summary_labels["total_correct_chars"].setText("-")
            self._summary_labels["total_error_chars"].setText("-")

    def _populate_sections(self) -> None:
        """Fill sections table."""
        rows: list[SectionStatRow] = []
        if self._current_user is not None:
            rows = self._stats_db.get_section_stats(self._current_user.user_id, self._current_course_id)

        self._sections_table.setRowCount(len(rows))
        self._sections_table.setSortingEnabled(False)
        for row_index, row in enumerate(rows):
            values = [
                row.section_title,
                str(row.lessons_seen),
                str(row.lessons_completed),
                str(row.attempts),
                f"{row.average_accuracy:.1f}%",
                f"{row.average_correct_wpm:.1f}",
            ]
            for column, value in enumerate(values):
                self._sections_table.setItem(row_index, column, QTableWidgetItem(value))
        self._sections_table.setSortingEnabled(True)
        self._sections_table.sortItems(0, Qt.SortOrder.AscendingOrder)

    def _populate_lessons(self) -> None:
        """Fill lessons table."""
        rows: list[LessonStatRow] = []
        if self._current_user is not None:
            rows = self._stats_db.get_lesson_stats(self._current_user.user_id, self._current_course_id)

        self._lessons_table.setRowCount(len(rows))
        self._lessons_table.setSortingEnabled(False)
        for row_index, row in enumerate(rows):
            values = [
                row.section_title,
                row.lesson_title,
                str(row.attempts),
                str(row.completed_attempts),
                f"{row.best_accuracy:.1f}%",
                f"{row.best_correct_wpm:.1f}",
                row.last_played_at.replace("T", " ")[:19],
            ]
            for column, value in enumerate(values):
                self._lessons_table.setItem(row_index, column, QTableWidgetItem(value))
        self._lessons_table.setSortingEnabled(True)
        self._lessons_table.sortItems(5, Qt.SortOrder.DescendingOrder)

    def _populate_symbols(self) -> None:
        """Fill symbols table."""
        rows: list[SymbolStatRow] = []
        if self._current_user is not None:
            rows = self._stats_db.get_symbol_stats(self._current_user.user_id, self._current_course_id)

        self._symbols_table.setRowCount(len(rows))
        self._symbols_table.setSortingEnabled(False)
        for row_index, row in enumerate(rows):
            display_symbol = row.symbol
            if display_symbol == " ":
                display_symbol = "Space"
            if row.sample_count > 0:
                valid_pct = (row.valid_sample_count / row.sample_count) * 100.0
                error_pct = (row.error_count / row.sample_count) * 100.0
                valid_text = f"{valid_pct:.1f}%"
                error_text = f"{error_pct:.1f}%"
            else:
                valid_text = "-"
                error_text = "-"
            values = [
                display_symbol,
                str(row.sample_count),
                valid_text,
                f"{row.mean_latency_ms:.1f}",
                f"{row.stddev_latency_ms:.1f}",
                error_text,
            ]
            for column, value in enumerate(values):
                self._symbols_table.setItem(row_index, column, QTableWidgetItem(value))
        self._symbols_table.setSortingEnabled(True)
        self._symbols_table.sortItems(3, Qt.SortOrder.AscendingOrder)
