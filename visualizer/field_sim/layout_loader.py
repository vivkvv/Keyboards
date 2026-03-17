"""Load keyboard layout JSON into field-simulator cells."""

from __future__ import annotations

import json
from pathlib import Path

from .models import KeyCell


def _get_all_empty_indices(keymap_path: Path, key_count: int) -> set[int]:
    """Return indices that are KC_NO on all layers for a VIA keymap JSON."""
    try:
        data = json.loads(keymap_path.read_text(encoding="utf-8"))
    except Exception:
        return set()

    layers = data.get("layers")
    if not isinstance(layers, list) or not layers:
        return set()
    if any(not isinstance(layer, list) or len(layer) != key_count for layer in layers):
        return set()

    empty_indices: set[int] = set()
    for index in range(key_count):
        if all((layer[index] or "").strip() in ("", "KC_NO") for layer in layers):
            empty_indices.add(index)
    return empty_indices


def _find_empty_indices(layout_path: Path, key_count: int) -> set[int]:
    """Try to find a matching keymap JSON near the layout and use it as a mask."""
    candidates = sorted(
        candidate
        for candidate in layout_path.parent.glob("*.json")
        if candidate != layout_path
    )

    preferred = [
        candidate for candidate in candidates
        if "layout" in candidate.stem.lower() and "visual" not in candidate.stem.lower()
    ]
    for candidate in preferred + [candidate for candidate in candidates if candidate not in preferred]:
        empty_indices = _get_all_empty_indices(candidate, key_count)
        if empty_indices:
            return empty_indices
    return set()


def load_layout(path: str | Path) -> tuple[str, list[KeyCell]]:
    """Load the first layout variant from a visual layout JSON file."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    layouts = data.get("layouts", {})
    if not layouts:
        raise ValueError("No layouts found in JSON file.")

    first_variant_name = next(iter(layouts))
    variant = layouts[first_variant_name]
    raw_cells = [
        KeyCell(
            source_index=index,
            x=float(item.get("x", 0.0)),
            y=float(item.get("y", 0.0)),
            w=float(item.get("w", 1.0)),
            h=float(item.get("h", 1.0)),
            r=float(item.get("r", 0.0)),
        )
        for index, item in enumerate(variant.get("layout", []))
    ]
    empty_indices = _find_empty_indices(path, len(raw_cells))
    cells = [cell for index, cell in enumerate(raw_cells) if index not in empty_indices]
    return variant.get("name", first_variant_name), cells
