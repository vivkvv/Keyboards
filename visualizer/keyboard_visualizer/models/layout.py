"""Layout geometry model."""

from dataclasses import dataclass, field

from .key import KeyGeometry


@dataclass
class Layout:
    """Physical keyboard geometry."""

    id: str
    name: str
    keys: list[KeyGeometry] = field(default_factory=list)

    @property
    def key_count(self) -> int:
        """Return the number of keys in this layout."""
        return len(self.keys)

    def get_bounds(self) -> tuple[float, float, float, float]:
        """Return (min_x, min_y, max_x, max_y) for scaling.

        Fake keys (placeholders) are excluded from bounds calculation.
        """
        real_keys = [k for k in self.keys if not k.fake]
        if not real_keys:
            return (0, 0, 0, 0)

        min_x = min(k.x for k in real_keys)
        min_y = min(k.y for k in real_keys)
        max_x = max(k.x + k.w for k in real_keys)
        max_y = max(k.y + k.h for k in real_keys)

        return (min_x, min_y, max_x, max_y)
