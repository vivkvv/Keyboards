"""SQLite storage for tutor users and statistics."""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path


MAX_VALID_LATENCY_MS = 5000
DEFAULT_COURSE_ID = "en"


@dataclass(frozen=True)
class TutorUser:
    """Simple tutor user profile."""

    user_id: int
    name: str


@dataclass(frozen=True)
class TutorOverview:
    """High-level tutor statistics for one user."""

    total_attempts: int = 0
    completed_attempts: int = 0
    unique_lessons_completed: int = 0
    average_accuracy: float = 0.0
    average_correct_wpm: float = 0.0
    total_correct_chars: int = 0
    total_error_chars: int = 0


@dataclass(frozen=True)
class LessonStatRow:
    """Aggregated statistics for one lesson."""

    course_id: str
    lesson_id: int
    section_title: str
    lesson_title: str
    attempts: int
    completed_attempts: int
    average_accuracy: float
    best_accuracy: float
    best_correct_wpm: float
    last_played_at: str


@dataclass(frozen=True)
class LessonProgressState:
    """Compact lesson progress state for sidebar rendering."""

    attempts: int = 0
    completed: bool = False
    average_accuracy: float = 0.0
    average_correct_wpm: float = 0.0


@dataclass(frozen=True)
class SectionStatRow:
    """Aggregated statistics for one section."""

    course_id: str
    section_title: str
    lessons_seen: int
    lessons_completed: int
    attempts: int
    average_accuracy: float
    average_correct_wpm: float


@dataclass(frozen=True)
class SymbolStatRow:
    """Per-symbol timing and error statistics."""

    course_id: str
    symbol: str
    sample_count: int
    valid_sample_count: int
    mean_latency_ms: float
    stddev_latency_ms: float
    error_count: int


class TutorStatsDatabase:
    """Small SQLite wrapper for tutor persistence."""

    DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "tutor_stats.db"

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path) if db_path else self.DEFAULT_DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @property
    def path(self) -> Path:
        """Return database path."""
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open a database connection."""
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row['name']) for row in rows}

    def _init_schema(self) -> None:
        """Create base schema if missing and migrate legacy databases."""
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS lesson_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    course_id TEXT NOT NULL DEFAULT 'en',
                    lesson_id INTEGER NOT NULL,
                    lesson_title TEXT NOT NULL DEFAULT '',
                    section_title TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    first_correct_at TEXT,
                    finished_at TEXT,
                    total_chars INTEGER NOT NULL DEFAULT 0,
                    correct_chars INTEGER NOT NULL DEFAULT 0,
                    error_chars INTEGER NOT NULL DEFAULT 0,
                    accuracy REAL NOT NULL DEFAULT 0,
                    correct_wpm REAL NOT NULL DEFAULT 0,
                    error_wpm REAL NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS key_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id INTEGER NOT NULL,
                    position_index INTEGER NOT NULL,
                    expected_char TEXT NOT NULL,
                    typed_char TEXT NOT NULL DEFAULT '',
                    is_correct INTEGER NOT NULL,
                    latency_ms INTEGER,
                    timing_valid INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(attempt_id) REFERENCES lesson_attempts(id) ON DELETE CASCADE
                );
                """
            )

            lesson_columns = self._table_columns(connection, 'lesson_attempts')
            if 'course_id' not in lesson_columns:
                connection.execute(
                    "ALTER TABLE lesson_attempts ADD COLUMN course_id TEXT NOT NULL DEFAULT 'en'"
                )

            symbol_columns = self._table_columns(connection, 'symbol_stats')
            if symbol_columns and 'course_id' not in symbol_columns:
                connection.execute("ALTER TABLE symbol_stats RENAME TO symbol_stats_legacy")
                connection.execute(
                    """
                    CREATE TABLE symbol_stats (
                        user_id INTEGER NOT NULL,
                        course_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        sample_count INTEGER NOT NULL DEFAULT 0,
                        valid_sample_count INTEGER NOT NULL DEFAULT 0,
                        mean_latency_ms REAL NOT NULL DEFAULT 0,
                        m2_latency REAL NOT NULL DEFAULT 0,
                        error_count INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY(user_id, course_id, symbol),
                        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO symbol_stats (
                        user_id,
                        course_id,
                        symbol,
                        sample_count,
                        valid_sample_count,
                        mean_latency_ms,
                        m2_latency,
                        error_count
                    )
                    SELECT
                        user_id,
                        'en',
                        symbol,
                        sample_count,
                        valid_sample_count,
                        mean_latency_ms,
                        m2_latency,
                        error_count
                    FROM symbol_stats_legacy
                    """
                )
                connection.execute("DROP TABLE symbol_stats_legacy")
            elif not symbol_columns:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS symbol_stats (
                        user_id INTEGER NOT NULL,
                        course_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        sample_count INTEGER NOT NULL DEFAULT 0,
                        valid_sample_count INTEGER NOT NULL DEFAULT 0,
                        mean_latency_ms REAL NOT NULL DEFAULT 0,
                        m2_latency REAL NOT NULL DEFAULT 0,
                        error_count INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY(user_id, course_id, symbol),
                        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                    )
                    """
                )

            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_lesson_attempts_user_course
                    ON lesson_attempts(user_id, course_id, lesson_id);
                CREATE INDEX IF NOT EXISTS idx_key_events_attempt
                    ON key_events(attempt_id, position_index);
                CREATE INDEX IF NOT EXISTS idx_key_events_expected
                    ON key_events(expected_char);
                CREATE INDEX IF NOT EXISTS idx_symbol_stats_user_course
                    ON symbol_stats(user_id, course_id, symbol);
                """
            )

    def list_users(self) -> list[TutorUser]:
        """Return available tutor users."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name
                FROM users
                ORDER BY datetime(last_used_at) DESC, lower(name) ASC
                """
            ).fetchall()
        return [TutorUser(user_id=int(row["id"]), name=str(row["name"])) for row in rows]

    def get_user(self, user_id: int) -> TutorUser | None:
        """Fetch one user by id."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, name FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return TutorUser(user_id=int(row["id"]), name=str(row["name"]))

    def create_user(self, name: str) -> TutorUser:
        """Create a new user profile."""
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("User name must not be empty.")

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (name, last_used_at)
                VALUES (?, CURRENT_TIMESTAMP)
                """,
                (clean_name,),
            )
            user_id = int(cursor.lastrowid)
        return TutorUser(user_id=user_id, name=clean_name)

    def touch_user(self, user_id: int) -> None:
        """Mark a user as recently used."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE users
                SET last_used_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (user_id,),
            )

    def start_attempt(
        self,
        user_id: int,
        course_id: str,
        lesson_id: int,
        lesson_title: str,
        section_title: str,
        total_chars: int,
    ) -> int:
        """Start a lesson attempt and return its id."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO lesson_attempts (
                    user_id,
                    course_id,
                    lesson_id,
                    lesson_title,
                    section_title,
                    first_correct_at,
                    total_chars
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                (user_id, course_id, lesson_id, lesson_title, section_title, total_chars),
            )
            attempt_id = int(cursor.lastrowid)
        return attempt_id

    def finish_attempt(
        self,
        attempt_id: int,
        *,
        total_chars: int,
        correct_chars: int,
        error_chars: int,
        accuracy: float,
        correct_wpm: float,
        error_wpm: float,
        completed: bool,
    ) -> None:
        """Finalize or update one lesson attempt."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE lesson_attempts
                SET finished_at = CURRENT_TIMESTAMP,
                    total_chars = ?,
                    correct_chars = ?,
                    error_chars = ?,
                    accuracy = ?,
                    correct_wpm = ?,
                    error_wpm = ?,
                    completed = ?
                WHERE id = ?
                """,
                (
                    total_chars,
                    correct_chars,
                    error_chars,
                    accuracy,
                    correct_wpm,
                    error_wpm,
                    1 if completed else 0,
                    attempt_id,
                ),
            )

    def add_key_event(
        self,
        *,
        user_id: int,
        course_id: str,
        attempt_id: int,
        position_index: int,
        expected_char: str,
        typed_char: str,
        is_correct: bool,
        latency_ms: int | None,
    ) -> None:
        """Persist one key event and update per-symbol aggregates."""
        timing_valid = int(latency_ms is not None and 0 <= latency_ms <= MAX_VALID_LATENCY_MS and is_correct)

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO key_events (
                    attempt_id,
                    position_index,
                    expected_char,
                    typed_char,
                    is_correct,
                    latency_ms,
                    timing_valid
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    position_index,
                    expected_char,
                    typed_char,
                    1 if is_correct else 0,
                    latency_ms,
                    timing_valid,
                ),
            )
            self._update_symbol_stats(
                connection,
                user_id=user_id,
                course_id=course_id,
                symbol=expected_char,
                is_correct=is_correct,
                latency_ms=latency_ms if timing_valid else None,
            )

    def _update_symbol_stats(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: int,
        course_id: str,
        symbol: str,
        is_correct: bool,
        latency_ms: int | None,
    ) -> None:
        """Update running per-symbol statistics using Welford aggregation."""
        row = connection.execute(
            """
            SELECT sample_count, valid_sample_count, mean_latency_ms, m2_latency, error_count
            FROM symbol_stats
            WHERE user_id = ? AND course_id = ? AND symbol = ?
            """,
            (user_id, course_id, symbol),
        ).fetchone()

        if row is None:
            sample_count = 0
            valid_sample_count = 0
            mean_latency_ms = 0.0
            m2_latency = 0.0
            error_count = 0
        else:
            sample_count = int(row["sample_count"])
            valid_sample_count = int(row["valid_sample_count"])
            mean_latency_ms = float(row["mean_latency_ms"])
            m2_latency = float(row["m2_latency"])
            error_count = int(row["error_count"])

        sample_count += 1
        if not is_correct:
            error_count += 1

        if latency_ms is not None:
            valid_sample_count += 1
            delta = float(latency_ms) - mean_latency_ms
            mean_latency_ms += delta / valid_sample_count
            delta2 = float(latency_ms) - mean_latency_ms
            m2_latency += delta * delta2

        connection.execute(
            """
            INSERT INTO symbol_stats (
                user_id,
                course_id,
                symbol,
                sample_count,
                valid_sample_count,
                mean_latency_ms,
                m2_latency,
                error_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, course_id, symbol) DO UPDATE SET
                sample_count = excluded.sample_count,
                valid_sample_count = excluded.valid_sample_count,
                mean_latency_ms = excluded.mean_latency_ms,
                m2_latency = excluded.m2_latency,
                error_count = excluded.error_count
            """,
            (
                user_id,
                course_id,
                symbol,
                sample_count,
                valid_sample_count,
                mean_latency_ms,
                m2_latency,
                error_count,
            ),
        )

    def get_overview(self, user_id: int, course_id: str | None = None) -> TutorOverview:
        """Return top-level statistics for one user."""
        query = """
            SELECT
                COUNT(*) AS total_attempts,
                COALESCE(SUM(completed), 0) AS completed_attempts,
                COUNT(DISTINCT CASE WHEN completed = 1 THEN lesson_id END) AS unique_lessons_completed,
                COALESCE(AVG(accuracy), 0) AS average_accuracy,
                COALESCE(AVG(correct_wpm), 0) AS average_correct_wpm,
                COALESCE(SUM(correct_chars), 0) AS total_correct_chars,
                COALESCE(SUM(error_chars), 0) AS total_error_chars
            FROM lesson_attempts
            WHERE user_id = ?
        """
        params: list[object] = [user_id]
        if course_id:
            query += " AND course_id = ?"
            params.append(course_id)
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return TutorOverview(
            total_attempts=int(row["total_attempts"]),
            completed_attempts=int(row["completed_attempts"]),
            unique_lessons_completed=int(row["unique_lessons_completed"]),
            average_accuracy=float(row["average_accuracy"]),
            average_correct_wpm=float(row["average_correct_wpm"]),
            total_correct_chars=int(row["total_correct_chars"]),
            total_error_chars=int(row["total_error_chars"]),
        )

    def get_lesson_stats(self, user_id: int, course_id: str | None = None) -> list[LessonStatRow]:
        """Return per-lesson aggregated statistics."""
        query = """
            SELECT
                course_id,
                lesson_id,
                lesson_title,
                section_title,
                COUNT(*) AS attempts,
                COALESCE(SUM(completed), 0) AS completed_attempts,
                COALESCE(AVG(accuracy), 0) AS average_accuracy,
                COALESCE(MAX(accuracy), 0) AS best_accuracy,
                COALESCE(MAX(correct_wpm), 0) AS best_correct_wpm,
                MAX(COALESCE(finished_at, started_at)) AS last_played_at
            FROM lesson_attempts
            WHERE user_id = ?
        """
        params: list[object] = [user_id]
        if course_id:
            query += " AND course_id = ?"
            params.append(course_id)
        query += " GROUP BY course_id, lesson_id, lesson_title, section_title ORDER BY lower(course_id), lower(section_title), lesson_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            LessonStatRow(
                course_id=str(row["course_id"]),
                lesson_id=int(row["lesson_id"]),
                section_title=str(row["section_title"]),
                lesson_title=str(row["lesson_title"]),
                attempts=int(row["attempts"]),
                completed_attempts=int(row["completed_attempts"]),
                average_accuracy=float(row["average_accuracy"]),
                best_accuracy=float(row["best_accuracy"]),
                best_correct_wpm=float(row["best_correct_wpm"]),
                last_played_at=str(row["last_played_at"] or ""),
            )
            for row in rows
        ]

    def get_lesson_progress_map(self, user_id: int, course_id: str | None = None) -> dict[int, LessonProgressState]:
        """Return compact per-lesson progress used by the tutor sidebar."""
        query = """
            SELECT
                lesson_id,
                COUNT(*) AS attempts,
                COALESCE(MAX(completed), 0) AS completed,
                COALESCE(AVG(accuracy), 0) AS average_accuracy,
                COALESCE(AVG(correct_wpm), 0) AS average_correct_wpm
            FROM lesson_attempts
            WHERE user_id = ?
        """
        params: list[object] = [user_id]
        if course_id:
            query += " AND course_id = ?"
            params.append(course_id)
        query += " GROUP BY lesson_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return {
            int(row["lesson_id"]): LessonProgressState(
                attempts=int(row["attempts"]),
                completed=bool(row["completed"]),
                average_accuracy=float(row["average_accuracy"]),
                average_correct_wpm=float(row["average_correct_wpm"]),
            )
            for row in rows
        }

    def get_section_stats(self, user_id: int, course_id: str | None = None) -> list[SectionStatRow]:
        """Return aggregated statistics per course section."""
        query = """
            SELECT
                course_id,
                section_title,
                COUNT(*) AS attempts,
                COUNT(DISTINCT lesson_id) AS lessons_seen,
                COUNT(DISTINCT CASE WHEN completed = 1 THEN lesson_id END) AS lessons_completed,
                COALESCE(AVG(accuracy), 0) AS average_accuracy,
                COALESCE(AVG(correct_wpm), 0) AS average_correct_wpm
            FROM lesson_attempts
            WHERE user_id = ?
        """
        params: list[object] = [user_id]
        if course_id:
            query += " AND course_id = ?"
            params.append(course_id)
        query += " GROUP BY course_id, section_title ORDER BY lower(course_id), lower(section_title)"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            SectionStatRow(
                course_id=str(row["course_id"]),
                section_title=str(row["section_title"]),
                lessons_seen=int(row["lessons_seen"]),
                lessons_completed=int(row["lessons_completed"]),
                attempts=int(row["attempts"]),
                average_accuracy=float(row["average_accuracy"]),
                average_correct_wpm=float(row["average_correct_wpm"]),
            )
            for row in rows
        ]

    def get_symbol_stats(self, user_id: int, course_id: str | None = None) -> list[SymbolStatRow]:
        """Return per-symbol timing/error statistics."""
        query = """
            SELECT
                course_id,
                symbol,
                sample_count,
                valid_sample_count,
                mean_latency_ms,
                m2_latency,
                error_count
            FROM symbol_stats
            WHERE user_id = ?
        """
        params: list[object] = [user_id]
        if course_id:
            query += " AND course_id = ?"
            params.append(course_id)
        query += " ORDER BY lower(course_id), symbol COLLATE NOCASE"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()

        result: list[SymbolStatRow] = []
        for row in rows:
            valid_sample_count = int(row["valid_sample_count"])
            m2_latency = float(row["m2_latency"])
            variance = (m2_latency / valid_sample_count) if valid_sample_count > 0 else 0.0
            result.append(
                SymbolStatRow(
                    course_id=str(row["course_id"]),
                    symbol=str(row["symbol"]),
                    sample_count=int(row["sample_count"]),
                    valid_sample_count=valid_sample_count,
                    mean_latency_ms=float(row["mean_latency_ms"]),
                    stddev_latency_ms=math.sqrt(max(variance, 0.0)),
                    error_count=int(row["error_count"]),
                )
            )
        return result
