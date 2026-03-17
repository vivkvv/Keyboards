"""Application configuration with INI file persistence."""

import configparser
import json
import os
from pathlib import Path
from dataclasses import dataclass


@dataclass
class LayerViewConfig:
    """Configuration for a layer view (single or multi-layer)."""
    name: str
    layers: list[int]
    is_builtin: bool = False  # True for "Layer 0", "All Layers", etc.


@dataclass
class SoundBinding:
    """Binding between a key on a specific layer and a sound file."""

    layer: int
    key_index: int
    sound_path: str


@dataclass
class LanguageSoundBinding:
    """Binding between a system input language and a sound file."""

    language: str
    sound_path: str


class Config:
    """
    Manages application configuration with INI file persistence.

    Stores:
    - Recent keymap files
    - Recent layout files
    - Last loaded keymap/layout paths
    - UI state (layer, always_on_top, etc.)
    - Layer colors and text colors
    - Custom layer views
    """

    MAX_RECENT_FILES = 10
    DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config.ini"

    # Default layer colors
    DEFAULT_LAYER_COLORS = [
        "#4fc3f7",  # Layer 0 - light blue
        "#81c784",  # Layer 1 - green
        "#ffb74d",  # Layer 2 - orange
        "#ba68c8",  # Layer 3 - purple
        "#e57373",  # Layer 4 - red
        "#64b5f6",  # Layer 5 - blue
        "#fff176",  # Layer 6 - yellow
        "#4db6ac",  # Layer 7 - teal
        "#f06292",  # Layer 8 - pink
        "#aed581",  # Layer 9 - light green
    ]

    DEFAULT_TAP_COLOR = "#ffffff"
    DEFAULT_HOLD_COLOR = "#ffb74d"
    DEFAULT_HID_HIGHLIGHT_COLOR = "#ff0000"
    DEFAULT_HID_HIGHLIGHT_DURATION_MS = 1000
    DEFAULT_TUTOR_SHOW_HOLD_LABELS = True
    DEFAULT_TUTOR_SHOW_MOVEMENT_ARROWS = False
    DEFAULT_TUTOR_CLICK_SOUNDS_ENABLED = False
    DEFAULT_FINGER_COLORS = {
        "pinky": "#e57373",
        "ring": "#ffb74d",
        "middle": "#fff176",
        "index": "#81c784",
        "thumb": "#64b5f6",
    }
    DEFAULT_TUTOR_CORRECT_SOUND = (
        Path(__file__).parent.parent / "resources" / "sounds" / "mixkit-modern-technology-select-3124.wav"
    )
    DEFAULT_TUTOR_INCORRECT_SOUND = (
        Path(__file__).parent.parent / "resources" / "sounds" / "mixkit-hard-typewriter-click-1119.wav"
    )

    def __init__(self, config_path: Path | str | None = None) -> None:
        self._path = Path(config_path) if config_path else self.DEFAULT_CONFIG_PATH
        self._config = configparser.ConfigParser()
        self._load()

    def _load(self) -> None:
        """Load config from file."""
        if self._path.exists():
            self._config.read(self._path, encoding="utf-8")

        # Ensure sections exist
        for section in ["recent", "last_session", "ui"]:
            if section not in self._config:
                self._config[section] = {}

    def save(self) -> None:
        """Save config to file."""
        with open(self._path, "w", encoding="utf-8") as f:
            self._config.write(f)

    def _config_dir(self) -> Path:
        return self._path.resolve().parent

    def _serialize_path(self, path: str | Path | None) -> str:
        if not path:
            return ""
        raw = Path(path)
        try:
            absolute = raw.resolve() if raw.exists() or raw.is_absolute() else (Path.cwd() / raw).resolve()
        except OSError:
            absolute = raw
        try:
            return os.path.relpath(str(absolute), str(self._config_dir()))
        except ValueError:
            return str(absolute)

    def _deserialize_path(self, value: str | None) -> str | None:
        if not value:
            return None
        path = Path(value)
        if path.is_absolute():
            return str(path)
        return str((self._config_dir() / path).resolve())

    def _serialize_path_list(self, paths: list[str]) -> list[str]:
        return [stored for path in paths if (stored := self._serialize_path(path))]

    def _deserialize_path_list(self, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            resolved = self._deserialize_path(value)
            if resolved:
                result.append(resolved)
        return result

    def _serialize_path_set(self, paths: set[str]) -> list[str]:
        return sorted({stored for path in paths if (stored := self._serialize_path(path))})

    def _deserialize_path_set(self, values: list[str]) -> set[str]:
        result: set[str] = set()
        for value in values:
            resolved = self._deserialize_path(value)
            if resolved:
                result.add(resolved)
        return result

    # Recent files
    def get_recent_keymaps(self) -> list[str]:
        """Get list of recent keymap file paths."""
        value = self._config.get("recent", "keymaps", fallback="")
        return self._deserialize_path_list([p for p in value.split("|") if p])

    def add_recent_keymap(self, path: str) -> None:
        """Add a keymap to recent files list."""
        recent = self.get_recent_keymaps()
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        recent = recent[: self.MAX_RECENT_FILES]
        self._config["recent"]["keymaps"] = "|".join(self._serialize_path_list(recent))
        self.save()

    def get_recent_layouts(self) -> list[str]:
        """Get list of recent layout file paths."""
        value = self._config.get("recent", "layouts", fallback="")
        return self._deserialize_path_list([p for p in value.split("|") if p])

    def add_recent_layout(self, path: str) -> None:
        """Add a layout to recent files list."""
        recent = self.get_recent_layouts()
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        recent = recent[: self.MAX_RECENT_FILES]
        self._config["recent"]["layouts"] = "|".join(self._serialize_path_list(recent))
        self.save()

    # Last session
    def get_last_keymap(self) -> str | None:
        """Get last loaded keymap path."""
        value = self._config.get("last_session", "keymap", fallback=None) or None
        return self._deserialize_path(value)

    def set_last_keymap(self, path: str | None) -> None:
        """Set last loaded keymap path."""
        self._config["last_session"]["keymap"] = self._serialize_path(path)
        self.save()

    def get_last_layout(self) -> str | None:
        """Get last loaded layout path."""
        value = self._config.get("last_session", "layout", fallback=None) or None
        return self._deserialize_path(value)

    def set_last_layout(self, path: str | None) -> None:
        """Set last loaded layout path."""
        self._config["last_session"]["layout"] = self._serialize_path(path)
        self.save()

    def get_last_variant(self) -> str | None:
        """Get last selected layout variant."""
        return self._config.get("last_session", "variant", fallback=None) or None

    def set_last_variant(self, variant: str | None) -> None:
        """Set last selected layout variant."""
        self._config["last_session"]["variant"] = variant or ""
        self.save()

    def get_last_layer(self) -> int:
        """Get last selected layer index."""
        return self._config.getint("last_session", "layer", fallback=0)

    def set_last_layer(self, layer: int) -> None:
        """Set last selected layer index."""
        self._config["last_session"]["layer"] = str(layer)
        self.save()

    def get_last_tutor_user_id(self) -> int | None:
        """Get last selected tutor user id."""
        value = self._config.get("last_session", "tutor_user_id", fallback="").strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def set_last_tutor_user_id(self, user_id: int | None) -> None:
        """Set last selected tutor user id."""
        self._config["last_session"]["tutor_user_id"] = "" if user_id is None else str(user_id)
        self.save()

    def get_last_tutor_course_id(self) -> str:
        """Get last selected tutor course id."""
        return self._config.get("last_session", "tutor_course_id", fallback="en") or "en"

    def set_last_tutor_course_id(self, course_id: str | None) -> None:
        """Set last selected tutor course id."""
        value = (course_id or "en").strip().lower() or "en"
        self._config["last_session"]["tutor_course_id"] = value
        self.save()

    # UI state
    def get_always_on_top(self) -> bool:
        """Get always on top setting."""
        return self._config.getboolean("ui", "always_on_top", fallback=False)

    def set_always_on_top(self, value: bool) -> None:
        """Set always on top setting."""
        self._config["ui"]["always_on_top"] = str(value).lower()
        self.save()

    def get_hook_enabled(self) -> bool:
        """Get hook enabled on startup setting."""
        return self._config.getboolean("ui", "hook_enabled", fallback=False)

    def set_hook_enabled(self, value: bool) -> None:
        """Set hook enabled setting."""
        self._config["ui"]["hook_enabled"] = str(value).lower()
        self.save()

    def get_hid_connected(self) -> bool:
        """Get whether HID should auto-connect on startup."""
        return self._config.getboolean("ui", "hid_connected", fallback=False)

    def set_hid_connected(self, value: bool) -> None:
        """Set whether HID should auto-connect on startup."""
        self._config["ui"]["hid_connected"] = str(value).lower()
        self.save()

    def get_language_enabled(self) -> bool:
        """Get whether system language labels are enabled."""
        return self._config.getboolean("ui", "language_enabled", fallback=False)

    def set_language_enabled(self, value: bool) -> None:
        """Set whether system language labels are enabled."""
        self._config["ui"]["language_enabled"] = str(value).lower()
        self.save()

    def get_hid_click_enabled(self) -> bool:
        """Get whether HID click highlighting is enabled."""
        return self._config.getboolean("ui", "hid_click_enabled", fallback=False)

    def set_hid_click_enabled(self, value: bool) -> None:
        """Set whether HID click highlighting is enabled."""
        self._config["ui"]["hid_click_enabled"] = str(value).lower()
        self.save()

    def get_tutor_show_hold_labels(self) -> bool:
        """Get whether tutor should show hold labels for LT/MT keys."""
        return self._config.getboolean(
            "ui",
            "tutor_show_hold_labels",
            fallback=self.DEFAULT_TUTOR_SHOW_HOLD_LABELS,
        )

    def set_tutor_show_hold_labels(self, value: bool) -> None:
        """Set whether tutor should show hold labels for LT/MT keys."""
        self._config["ui"]["tutor_show_hold_labels"] = str(value).lower()
        self.save()

    def get_tutor_show_movement_arrows(self) -> bool:
        """Get whether tutor should show movement arrows for active fingers."""
        return self._config.getboolean(
            "ui",
            "tutor_show_movement_arrows",
            fallback=self.DEFAULT_TUTOR_SHOW_MOVEMENT_ARROWS,
        )

    def set_tutor_show_movement_arrows(self, value: bool) -> None:
        """Set whether tutor should show movement arrows for active fingers."""
        self._config["ui"]["tutor_show_movement_arrows"] = str(value).lower()
        self.save()

    def get_tutor_click_sounds_enabled(self) -> bool:
        """Get whether tutor should play correct/incorrect click sounds."""
        return self._config.getboolean(
            "ui",
            "tutor_click_sounds_enabled",
            fallback=self.DEFAULT_TUTOR_CLICK_SOUNDS_ENABLED,
        )

    def set_tutor_click_sounds_enabled(self, value: bool) -> None:
        """Set whether tutor should play correct/incorrect click sounds."""
        self._config["ui"]["tutor_click_sounds_enabled"] = str(value).lower()
        self.save()

    def get_tutor_correct_sound(self) -> str:
        """Get tutor sound for correct keystrokes."""
        value = self._config.get(
            "ui",
            "tutor_correct_sound",
            fallback=str(self.DEFAULT_TUTOR_CORRECT_SOUND),
        )
        return self._deserialize_path(value) or str(self.DEFAULT_TUTOR_CORRECT_SOUND)

    def set_tutor_correct_sound(self, path: str) -> None:
        """Set tutor sound for correct keystrokes."""
        self._config["ui"]["tutor_correct_sound"] = self._serialize_path(path)
        self.save()

    def get_tutor_incorrect_sound(self) -> str:
        """Get tutor sound for incorrect keystrokes."""
        value = self._config.get(
            "ui",
            "tutor_incorrect_sound",
            fallback=str(self.DEFAULT_TUTOR_INCORRECT_SOUND),
        )
        return self._deserialize_path(value) or str(self.DEFAULT_TUTOR_INCORRECT_SOUND)

    def set_tutor_incorrect_sound(self, path: str) -> None:
        """Set tutor sound for incorrect keystrokes."""
        self._config["ui"]["tutor_incorrect_sound"] = self._serialize_path(path)
        self.save()

    def get_hid_highlight_color(self) -> str:
        """Get physical keyboard highlight color."""
        return self._config.get(
            "ui",
            "hid_highlight_color",
            fallback=self.DEFAULT_HID_HIGHLIGHT_COLOR,
        )

    def set_hid_highlight_color(self, color: str) -> None:
        """Set physical keyboard highlight color."""
        self._config["ui"]["hid_highlight_color"] = color
        self.save()

    def get_hid_highlight_duration_ms(self) -> int:
        """Get physical keyboard highlight duration."""
        return self._config.getint(
            "ui",
            "hid_highlight_duration_ms",
            fallback=self.DEFAULT_HID_HIGHLIGHT_DURATION_MS,
        )

    def set_hid_highlight_duration_ms(self, duration_ms: int) -> None:
        """Set physical keyboard highlight duration."""
        self._config["ui"]["hid_highlight_duration_ms"] = str(max(0, duration_ms))
        self.save()

    def get_finger_color(self, finger_name: str) -> str:
        """Get configured tutor color for a logical finger."""
        return self._config.get(
            "finger_colors",
            finger_name,
            fallback=self.DEFAULT_FINGER_COLORS[finger_name],
        )

    def set_finger_color(self, finger_name: str, color: str) -> None:
        """Set configured tutor color for a logical finger."""
        if "finger_colors" not in self._config:
            self._config["finger_colors"] = {}
        self._config["finger_colors"][finger_name] = color
        self.save()

    # Layer colors
    def get_layer_color(self, layer: int) -> str:
        """Get color for a layer."""
        section = "layer_colors"
        if section not in self._config:
            self._config[section] = {}
        key = f"layer_{layer}"
        default = self.DEFAULT_LAYER_COLORS[layer % len(self.DEFAULT_LAYER_COLORS)]
        return self._config.get(section, key, fallback=default)

    def set_layer_color(self, layer: int, color: str) -> None:
        """Set color for a layer."""
        section = "layer_colors"
        if section not in self._config:
            self._config[section] = {}
        self._config[section][f"layer_{layer}"] = color
        self.save()

    def get_all_layer_colors(self, num_layers: int = 10) -> list[str]:
        """Get colors for all layers."""
        return [self.get_layer_color(i) for i in range(num_layers)]

    # Text colors
    def get_tap_color(self) -> str:
        """Get tap text color."""
        return self._config.get("text_colors", "tap", fallback=self.DEFAULT_TAP_COLOR)

    def set_tap_color(self, color: str) -> None:
        """Set tap text color."""
        if "text_colors" not in self._config:
            self._config["text_colors"] = {}
        self._config["text_colors"]["tap"] = color
        self.save()

    def get_hold_color(self) -> str:
        """Get hold text color."""
        return self._config.get("text_colors", "hold", fallback=self.DEFAULT_HOLD_COLOR)

    def set_hold_color(self, color: str) -> None:
        """Set hold text color."""
        if "text_colors" not in self._config:
            self._config["text_colors"] = {}
        self._config["text_colors"]["hold"] = color
        self.save()

    # Custom layer views
    def get_custom_views(self) -> list[LayerViewConfig]:
        """Get all custom layer views."""
        section = "custom_views"
        if section not in self._config:
            return []

        views = []
        for name, layers_str in self._config[section].items():
            try:
                layers = [int(x.strip()) for x in layers_str.split(",") if x.strip()]
                views.append(LayerViewConfig(name=name, layers=layers, is_builtin=False))
            except ValueError:
                continue
        return views

    def add_custom_view(self, name: str, layers: list[int]) -> bool:
        """Add a custom layer view. Returns False if name already exists."""
        section = "custom_views"
        if section not in self._config:
            self._config[section] = {}

        # Check for duplicate names
        if name.lower() in [k.lower() for k in self._config[section].keys()]:
            return False

        self._config[section][name] = ",".join(str(l) for l in layers)
        self.save()
        return True

    def update_custom_view(self, old_name: str, new_name: str, layers: list[int]) -> bool:
        """Update a custom layer view."""
        section = "custom_views"
        if section not in self._config:
            return False

        # Remove old entry
        if old_name in self._config[section]:
            del self._config[section][old_name]

        # Check for duplicate names (if renaming)
        if old_name != new_name and new_name.lower() in [k.lower() for k in self._config[section].keys()]:
            return False

        self._config[section][new_name] = ",".join(str(l) for l in layers)
        self.save()
        return True

    def delete_custom_view(self, name: str) -> bool:
        """Delete a custom layer view."""
        section = "custom_views"
        if section not in self._config or name not in self._config[section]:
            return False

        del self._config[section][name]
        self.save()
        return True

    # Last layer view
    def get_last_layer_view(self) -> str:
        """Get last selected layer view name."""
        return self._config.get("last_session", "layer_view", fallback="Layer 0")

    def set_last_layer_view(self, view_name: str) -> None:
        """Set last selected layer view name."""
        self._config["last_session"]["layer_view"] = view_name
        self.save()

    # Sound bindings
    def get_sound_bindings(self) -> list[SoundBinding]:
        """Get configured key sound bindings."""
        raw = self._config.get("ui", "sound_bindings", fallback="[]")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []

        bindings: list[SoundBinding] = []
        for item in data:
            try:
                layer = int(item["layer"])
                key_index = int(item["key_index"])
                sound_path = self._deserialize_path(str(item["sound_path"])) or ""
            except (KeyError, TypeError, ValueError):
                continue
            if sound_path:
                bindings.append(SoundBinding(layer=layer, key_index=key_index, sound_path=sound_path))

        bindings.sort(key=lambda binding: (binding.layer, binding.key_index, binding.sound_path.lower()))
        return bindings

    def set_sound_bindings(self, bindings: list[SoundBinding]) -> None:
        """Persist key sound bindings."""
        data = [
            {
                "layer": binding.layer,
                "key_index": binding.key_index,
                "sound_path": self._serialize_path(binding.sound_path),
            }
            for binding in bindings
        ]
        self._config["ui"]["sound_bindings"] = json.dumps(data, ensure_ascii=True)
        self.save()

    def get_language_sound_bindings(self) -> list[LanguageSoundBinding]:
        """Get configured language sound bindings."""
        raw = self._config.get("ui", "language_sound_bindings", fallback="[]")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []

        bindings: list[LanguageSoundBinding] = []
        for item in data:
            try:
                language = str(item["language"]).strip()
                sound_path = self._deserialize_path(str(item["sound_path"])) or ""
            except (KeyError, TypeError, ValueError):
                continue
            if language and sound_path:
                bindings.append(LanguageSoundBinding(language=language, sound_path=sound_path))

        bindings.sort(key=lambda binding: (binding.language.lower(), binding.sound_path.lower()))
        return bindings

    def set_language_sound_bindings(self, bindings: list[LanguageSoundBinding]) -> None:
        """Persist language sound bindings."""
        data = [
            {
                "language": binding.language,
                "sound_path": self._serialize_path(binding.sound_path),
            }
            for binding in bindings
        ]
        self._config["ui"]["language_sound_bindings"] = json.dumps(data, ensure_ascii=True)
        self.save()

    # Invalid recent files
    def get_invalid_recent_keymaps(self) -> set[str]:
        """Get recent keymap paths previously marked as invalid."""
        raw = self._config.get("ui", "invalid_recent_keymaps", fallback="[]")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return set()
        return self._deserialize_path_set([str(item) for item in data if item])

    def set_invalid_recent_keymaps(self, paths: set[str]) -> None:
        """Persist recent keymap paths marked as invalid."""
        self._config["ui"]["invalid_recent_keymaps"] = json.dumps(self._serialize_path_set(paths), ensure_ascii=True)
        self.save()

    def get_invalid_recent_layouts(self) -> set[str]:
        """Get recent geometry paths previously marked as invalid."""
        raw = self._config.get("ui", "invalid_recent_layouts", fallback="[]")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return set()
        return self._deserialize_path_set([str(item) for item in data if item])

    def set_invalid_recent_layouts(self, paths: set[str]) -> None:
        """Persist recent geometry paths marked as invalid."""
        self._config["ui"]["invalid_recent_layouts"] = json.dumps(self._serialize_path_set(paths), ensure_ascii=True)
        self.save()

    def get_warning_recent_keymaps(self) -> set[str]:
        """Get recent keymap paths previously marked as warning-loaded."""
        raw = self._config.get("ui", "warning_recent_keymaps", fallback="[]")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return set()
        return self._deserialize_path_set([str(item) for item in data if item])

    def set_warning_recent_keymaps(self, paths: set[str]) -> None:
        """Persist recent keymap paths marked as warning-loaded."""
        self._config["ui"]["warning_recent_keymaps"] = json.dumps(self._serialize_path_set(paths), ensure_ascii=True)
        self.save()

    def get_warning_recent_layouts(self) -> set[str]:
        """Get recent geometry paths previously marked as warning-loaded."""
        raw = self._config.get("ui", "warning_recent_layouts", fallback="[]")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return set()
        return self._deserialize_path_set([str(item) for item in data if item])

    def set_warning_recent_layouts(self, paths: set[str]) -> None:
        """Persist recent geometry paths marked as warning-loaded."""
        self._config["ui"]["warning_recent_layouts"] = json.dumps(self._serialize_path_set(paths), ensure_ascii=True)
        self.save()
