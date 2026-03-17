"""Visual layout JSON parser."""

import json
from pathlib import Path

from ..models import KeyGeometry
from ..models.layout import Layout


class LayoutParser:
    """Parser for visual layout JSON files."""

    def parse_file(self, file_path: str | Path) -> Layout:
        """Parse a visual layout JSON file."""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return self.parse_dict(data)

    def parse_dict(self, data: dict) -> Layout:
        """Parse layout from a dictionary."""
        layout_id = data.get("id", "unknown")
        name = data.get("name", "Unknown")
        keys_data = data.get("layout", [])

        keys: list[KeyGeometry] = []
        for key_data in keys_data:
            key = KeyGeometry(
                x=float(key_data.get("x", 0)),
                y=float(key_data.get("y", 0)),
                w=float(key_data.get("w", 1)),
                h=float(key_data.get("h", 1)),
                r=float(key_data.get("r", 0)),
                rx=float(key_data["rx"]) if "rx" in key_data else None,
                ry=float(key_data["ry"]) if "ry" in key_data else None,
                fake=bool(key_data.get("fake", False)),
            )
            keys.append(key)

        return Layout(id=layout_id, name=name, keys=keys)


class LayoutParseError(Exception):
    """Exception raised when layout parsing fails."""

    pass
