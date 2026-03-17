"""Key data models."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..parsers import KeyLabels


@dataclass
class KeyGeometry:
    """Physical key position and rotation."""

    x: float  # X position in key units (1u = standard key)
    y: float  # Y position in key units
    w: float = 1.0  # Width in key units
    h: float = 1.0  # Height in key units
    r: float = 0.0  # Rotation in degrees
    rx: float | None = None  # Rotation center X
    ry: float | None = None  # Rotation center Y
    fake: bool = False  # True for placeholder keys (KC_NO)


@dataclass
class KeyDefinition:
    """Combined key data: geometry + keycode per layer."""

    index: int  # Position in layout (0-based)
    geometry: KeyGeometry
    keycodes: list[str] = field(default_factory=list)  # One keycode per layer
    parsed_labels: list = field(default_factory=list)  # KeyLabels per layer

    def get_labels(self, layer: int) -> KeyLabels | None:
        """Get the KeyLabels for a specific layer."""
        if 0 <= layer < len(self.parsed_labels):
            return self.parsed_labels[layer]
        return None

    def get_label(self, layer: int) -> str:
        """Get the tap label for a specific layer (legacy)."""
        labels = self.get_labels(layer)
        return labels.tap if labels else ""

    def get_keycode(self, layer: int) -> str:
        """Get the raw keycode for a specific layer."""
        if 0 <= layer < len(self.keycodes):
            return self.keycodes[layer]
        return ""
