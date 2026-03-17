"""VIA keymap JSON parser."""

import json
from pathlib import Path

from ..models import Keymap


class KeymapParser:
    """Parser for VIA keymap JSON files."""

    def parse_file(self, file_path: str | Path) -> Keymap:
        """Parse a VIA keymap JSON file."""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return self.parse_dict(data)

    def parse_dict(self, data: dict) -> Keymap:
        """Parse keymap from a dictionary."""
        name = data.get("name", "Unknown")
        layers = data.get("layers", [])
        macros = data.get("macros", [])
        vendor_product_id = data.get("vendorProductId")

        return Keymap(
            name=name,
            layers=layers,
            macros=macros,
            vendor_product_id=vendor_product_id,
        )


class KeymapParseError(Exception):
    """Exception raised when keymap parsing fails."""

    pass
