"""Tutor hand scheme loading and persistence."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


SCHEMES_PATH = Path(__file__).parent.parent / "resources" / "tutor_hand_schemes.json"
ASSIGNMENTS_PATH = Path(__file__).parent.parent / "resources" / "tutor_key_scheme_assignments.json"


@dataclass(frozen=True, slots=True)
class TutorHandScheme:
    """Single hand home-position scheme."""

    name: str
    label: str
    hand: str
    home_positions: dict[str, int]


@dataclass(frozen=True, slots=True)
class TutorHandSchemeSet:
    """Collection of available tutor hand schemes."""

    default_left_scheme: str
    default_right_scheme: str
    schemes: dict[str, TutorHandScheme]

    def schemes_for_hand(self, hand: str) -> list[TutorHandScheme]:
        return [scheme for scheme in self.schemes.values() if scheme.hand == hand]


@dataclass(frozen=True, slots=True)
class TutorKeySchemeAssignments:
    """Per-key tutor scheme assignment plus optional finger overrides."""

    schemes: dict[int, str]
    overrides: dict[int, dict[str, int]]


def load_tutor_hand_schemes() -> TutorHandSchemeSet:
    """Load available tutor hand schemes from JSON."""
    raw = json.loads(SCHEMES_PATH.read_text(encoding="utf-8"))
    schemes: dict[str, TutorHandScheme] = {}
    for name, item in raw.get("schemes", {}).items():
        home_positions = {
            str(finger_name): int(key_index)
            for finger_name, key_index in item.get("home_positions", {}).items()
        }
        schemes[name] = TutorHandScheme(
            name=name,
            label=str(item.get("label") or name),
            hand=str(item.get("hand") or ""),
            home_positions=home_positions,
        )

    return TutorHandSchemeSet(
        default_left_scheme=str(raw.get("default_left_scheme") or ""),
        default_right_scheme=str(raw.get("default_right_scheme") or ""),
        schemes=schemes,
    )


def load_tutor_key_scheme_assignments() -> TutorKeySchemeAssignments:
    """Load per-key tutor scheme assignments and finger overrides."""
    if not ASSIGNMENTS_PATH.exists():
        return TutorKeySchemeAssignments(schemes={}, overrides={})
    raw = json.loads(ASSIGNMENTS_PATH.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "schemes" in raw:
        scheme_data = raw.get("schemes", {})
        override_data = raw.get("overrides", {})
    else:
        scheme_data = raw
        override_data = {}

    assignments: dict[int, str] = {}
    for key, value in scheme_data.items():
        try:
            assignments[int(key)] = str(value)
        except (TypeError, ValueError):
            continue
    overrides: dict[int, dict[str, int]] = {}
    for key, value in override_data.items():
        try:
            key_index = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(value, dict):
            continue
        finger_positions: dict[str, int] = {}
        for finger_name, override_key_index in value.items():
            try:
                finger_positions[str(finger_name)] = int(override_key_index)
            except (TypeError, ValueError):
                continue
        if finger_positions:
            overrides[key_index] = finger_positions
    return TutorKeySchemeAssignments(schemes=assignments, overrides=overrides)


def save_tutor_key_scheme_assignments(assignments: TutorKeySchemeAssignments) -> None:
    """Save per-key tutor scheme assignments and finger overrides."""
    serializable = {
        "schemes": {str(key): value for key, value in sorted(assignments.schemes.items())},
        "overrides": {
            str(key): {
                finger: override_key
                for finger, override_key in sorted(
                    finger_positions.items(),
                    key=lambda item: item[0],
                )
            }
            for key, finger_positions in sorted(assignments.overrides.items())
        },
    }
    ASSIGNMENTS_PATH.write_text(
        json.dumps(serializable, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def is_left_hand_key(key_index: int) -> bool:
    """Return whether a visual key index belongs to the left half."""
    return key_index < 20


def get_default_scheme_name(schemes: TutorHandSchemeSet, hand: str) -> str:
    """Return the default scheme name for a hand."""
    return schemes.default_left_scheme if hand == "left" else schemes.default_right_scheme


def get_assigned_scheme_name(
    key_index: int,
    schemes: TutorHandSchemeSet,
    assignments: TutorKeySchemeAssignments,
) -> str:
    """Return the effective scheme name for a key."""
    hand = "left" if is_left_hand_key(key_index) else "right"
    return assignments.schemes.get(key_index, get_default_scheme_name(schemes, hand))
