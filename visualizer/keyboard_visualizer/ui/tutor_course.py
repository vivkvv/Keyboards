"""Tutor course loading and lesson adaptation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import re
from typing import Optional

from ..models import Keymap


EDCLUB_PROGRAM3_PATH = Path(__file__).resolve().parents[2] / "data" / "edclub_program3.json"
RUSSIAN_COURSE_PATH = Path(__file__).resolve().parents[2] / "data" / "tutor_ru_course.json"


@dataclass(frozen=True, slots=True)
class TutorCourseInfo:
    """Metadata describing one available tutor course."""

    course_id: str
    language_code: str
    title: str


@dataclass(slots=True)
class TutorLesson:
    """Single tutor lesson."""

    lesson_id: int
    title: str
    lesson_type: str
    text: str = ""
    playable: bool = False
    score: Optional[int] = None


@dataclass(slots=True)
class TutorSection:
    """Course section containing tutor lessons."""

    title: str
    lessons: list[TutorLesson] = field(default_factory=list)


@dataclass(slots=True)
class TutorCourse:
    """One complete tutor course with metadata and sections."""

    course_id: str
    language_code: str
    title: str
    sections: list[TutorSection] = field(default_factory=list)


STANDARD_BASE_LAYOUT: dict[int, str] = {
    0: "q", 1: "w", 2: "e", 3: "r", 4: "t",
    5: "a", 6: "s", 7: "d", 8: "f", 9: "g",
    10: "z", 11: "x", 12: "c", 13: "v", 14: "b",
    20: "p", 21: "o", 22: "i", 23: "u", 24: "y",
    25: "'", 26: "l", 27: "k", 28: "j", 29: "h",
    30: "/", 31: ".", 32: ",", 33: "m", 34: "n",
}

STANDARD_RUSSIAN_LAYOUT: dict[int, str] = {
    0: "й", 1: "ц", 2: "у", 3: "к", 4: "е",
    5: "ф", 6: "ы", 7: "в", 8: "а", 9: "п",
    10: "я", 11: "ч", 12: "с", 13: "м", 14: "и",
    20: "з", 21: "щ", 22: "ш", 23: "г", 24: "н",
    25: "э", 26: "д", 27: "л", 28: "о", 29: "р",
    30: ".", 31: "ю", 32: "б", 33: "ь", 34: "т",
}


SHIFTED_CHARS = {
    "`": "~",
    "1": "!",
    "2": "@",
    "3": "#",
    "4": "$",
    "5": "%",
    "6": "^",
    "7": "&",
    "8": "*",
    "9": "(",
    "0": ")",
    "-": "_",
    "=": "+",
    "[": "{",
    "]": "}",
    "\\": "|",
    ";": ":",
    "'": '"',
    ",": "<",
    ".": ">",
    "/": "?",
}


POSITION_ADAPTED_SECTIONS = {
    "Home Row",
    "Top Row",
    "Bottom Row",
    "Shift Key",
    "Numbers",
    "Symbols",
    "More Symbols",
}


def _normalize_text(text: str) -> str:
    """Collapse lesson text into a single trainer-friendly line."""
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _unwrap_tap_keycode(keycode: str) -> str:
    """Extract the tap key from LT()/MT() wrappers."""
    if keycode.startswith("MT(") or keycode.startswith("LT("):
        parts = keycode.split(",")
        if len(parts) >= 2:
            return parts[-1].strip().rstrip(")")
    return keycode


def _keycode_to_primary_char(keycode: str) -> Optional[str]:
    """Convert a basic QMK keycode to its unshifted character."""
    if not keycode:
        return None

    keycode = _unwrap_tap_keycode(keycode)
    if not keycode.startswith("KC_"):
        return None

    key = keycode[3:]
    if len(key) == 1 and key.isalpha():
        return key.lower()
    if key.isdigit():
        return key

    special = {
        "GRV": "`",
        "MINS": "-",
        "EQL": "=",
        "LBRC": "[",
        "RBRC": "]",
        "BSLS": "\\",
        "SCLN": ";",
        "QUOT": "'",
        "COMM": ",",
        "DOT": ".",
        "SLSH": "/",
        "SPACE": " ",
        "SPC": " ",
    }
    return special.get(key)


def _build_position_remap(keymap: Optional[Keymap]) -> dict[str, str]:
    """Build a positional remap from standard QWERTY positions to current bindings."""
    if not keymap or not keymap.layers:
        return {}

    base_layer = keymap.layers[0]
    remap: dict[str, str] = {}
    for visual_index, standard_char in STANDARD_BASE_LAYOUT.items():
        if visual_index >= len(base_layer):
            continue
        current_char = _keycode_to_primary_char(base_layer[visual_index])
        if not current_char:
            continue

        remap[standard_char] = current_char
        if standard_char.isalpha():
            remap[standard_char.upper()] = current_char.upper()
        elif standard_char in SHIFTED_CHARS and current_char in SHIFTED_CHARS:
            remap[SHIFTED_CHARS[standard_char]] = SHIFTED_CHARS[current_char]

    return remap


def _build_static_position_remap(source_layout: dict[int, str], target_layout: dict[int, str]) -> dict[str, str]:
    """Build a direct positional remap between two fixed layouts."""
    remap: dict[str, str] = {}
    for visual_index, source_char in source_layout.items():
        target_char = target_layout.get(visual_index)
        if not target_char:
            continue
        remap[source_char] = target_char
        if source_char.isalpha():
            remap[source_char.upper()] = target_char.upper()
    return remap


def _adapt_position_text(text: str, remap: dict[str, str]) -> str:
    """Adapt a drill string to the user's physical layout positions."""
    if not remap or not text:
        return text
    return "".join(remap.get(char, char) for char in text)


def _collect_lesson_text(item: dict) -> str:
    """Extract lesson text from edclub activity payload."""
    activity = item.get("activity") or {}
    text_parts: list[str] = []
    for key in ("text1", "text2", "text3", "text4", "text5"):
        value = activity.get(key)
        if value:
            text_parts.append(str(value))
    return _normalize_text(" ".join(text_parts))


def _is_position_drill(section_title: str, lesson_name: str) -> bool:
    """Return whether a lesson should be positionally adapted."""
    if section_title not in POSITION_ADAPTED_SECTIONS:
        return False

    prefixes = (
        "Keys ",
        "Review:",
        "Practice:",
        "Play:",
        "Placement Test",
        "Home Row",
        "Top Row",
        "Bottom Row",
        "First 8 Keys",
        "Travel ",
        "Dynamic Practice",
    )
    return lesson_name.startswith(prefixes)


def _load_edclub_sections(remap: dict[str, str] | None = None) -> list[TutorSection]:
    """Load and adapt the public edclub Program 3 course into sections."""
    if not EDCLUB_PROGRAM3_PATH.exists():
        return [
            TutorSection(
                title="Lessons",
                lessons=[
                    TutorLesson(
                        lesson_id=0,
                        title="Missing edclub_program3.json",
                        lesson_type="typing",
                        text="asdf jkl;",
                        playable=True,
                    )
                ],
            )
        ]

    raw = json.loads(EDCLUB_PROGRAM3_PATH.read_text(encoding="utf-8"))
    lesson_items = raw.get("lessons", [])
    active_remap = remap or {}

    sections: list[TutorSection] = []
    current_section: Optional[TutorSection] = None

    for item in lesson_items:
        lesson_type = item.get("lesson_type", "")
        name = str(item.get("name") or "").strip()
        if not name or item.get("is_hidden"):
            continue

        if lesson_type == "header":
            current_section = TutorSection(title=name)
            sections.append(current_section)
            continue

        if current_section is None:
            current_section = TutorSection(title="Lessons")
            sections.append(current_section)

        lesson_text = _collect_lesson_text(item)
        title = name
        playable = lesson_type == "typing" and bool(lesson_text)

        if playable and _is_position_drill(current_section.title, name):
            title = _adapt_position_text(title, active_remap)
            lesson_text = _adapt_position_text(lesson_text, active_remap)

        current_section.lessons.append(
            TutorLesson(
                lesson_id=int(item.get("id") or 0),
                title=title,
                lesson_type=lesson_type,
                text=lesson_text,
                playable=playable,
                score=item.get("score"),
            )
        )

    return [section for section in sections if section.lessons]


def load_edclub_course(keymap: Optional[Keymap] = None) -> list[TutorSection]:
    """Backwards-compatible English lesson loader."""
    return _load_edclub_sections(_build_position_remap(keymap))


def _load_structured_course(path: Path) -> TutorCourse:
    """Load a tutor course from a simple structured JSON file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    sections: list[TutorSection] = []
    for section_data in raw.get("sections", []):
        lessons = [
            TutorLesson(
                lesson_id=int(lesson_data.get("id") or 0),
                title=str(lesson_data.get("title") or "").strip(),
                lesson_type=str(lesson_data.get("type") or "typing"),
                text=_normalize_text(str(lesson_data.get("text") or "")),
                playable=bool(lesson_data.get("text")),
            )
            for lesson_data in section_data.get("lessons", [])
        ]
        if lessons:
            sections.append(TutorSection(title=str(section_data.get("title") or "Lessons"), lessons=lessons))

    return TutorCourse(
        course_id=str(raw.get("course_id") or "custom"),
        language_code=str(raw.get("language_code") or ""),
        title=str(raw.get("title") or raw.get("course_id") or "Course"),
        sections=sections,
    )


def list_available_courses() -> list[TutorCourseInfo]:
    """Return all built-in tutor courses."""
    return [
        TutorCourseInfo(course_id="en", language_code="en", title="English"),
        TutorCourseInfo(course_id="ru", language_code="ru", title="Russian"),
    ]


def load_course(course_id: str, keymap: Optional[Keymap] = None) -> TutorCourse:
    """Load one tutor course by id."""
    normalized = (course_id or "en").strip().lower()
    if normalized == "ru":
        if RUSSIAN_COURSE_PATH.exists():
            return _load_structured_course(RUSSIAN_COURSE_PATH)
        return TutorCourse(
            course_id="ru",
            language_code="ru",
            title="Russian",
            sections=_load_edclub_sections(
                _build_static_position_remap(STANDARD_BASE_LAYOUT, STANDARD_RUSSIAN_LAYOUT)
            ),
        )

    return TutorCourse(
        course_id="en",
        language_code="en",
        title="English",
        sections=_load_edclub_sections(_build_position_remap(keymap)),
    )
