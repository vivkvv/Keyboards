"""Keymap data model."""

from dataclasses import dataclass, field


@dataclass
class Keymap:
    """Full keymap data from VIA export."""

    name: str
    layers: list[list[str]] = field(default_factory=list)  # layers[layer_index][key_index] = keycode
    macros: list[str] = field(default_factory=list)
    vendor_product_id: int | None = None

    @property
    def layer_count(self) -> int:
        """Return the number of layers."""
        return len(self.layers)

    @property
    def key_count(self) -> int:
        """Return the number of keys (from first layer)."""
        if self.layers:
            return len(self.layers[0])
        return 0

    def get_keycode(self, layer: int, key_index: int) -> str | None:
        """Get keycode for a specific layer and key index."""
        if 0 <= layer < len(self.layers):
            layer_keys = self.layers[layer]
            if 0 <= key_index < len(layer_keys):
                return layer_keys[key_index]
        return None

    def get_layer_names(self) -> list[str]:
        """Return default layer names (Layer 0, Layer 1, etc.)."""
        return [f"Layer {i}" for i in range(self.layer_count)]
