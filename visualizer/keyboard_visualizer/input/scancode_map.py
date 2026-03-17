"""Scancode and VK code mapping to QMK keycodes."""

from ..models import Keymap
from ..parsers.qmk_keycodes import QMKKeycodeParser
import re


class ScancodeMapper:
    """
    Maps Windows scancodes/virtual keycodes to QMK key indices.

    This is the bridge between physical key presses and the visual layout.
    Handles both tap keys and hold modifiers from MT (Mod-Tap) keys.
    """

    # Modifier names in MOD_xxx format to QMK keycode
    MOD_TO_QMK: dict[str, str] = {
        "MOD_LSFT": "KC_LSFT",
        "MOD_RSFT": "KC_RSFT",
        "MOD_LCTL": "KC_LCTL",
        "MOD_RCTL": "KC_RCTL",
        "MOD_LALT": "KC_LALT",
        "MOD_RALT": "KC_RALT",
        "MOD_LGUI": "KC_LGUI",
        "MOD_RGUI": "KC_RGUI",
    }

    # Windows VK codes to QMK keycode names
    VK_TO_QMK: dict[int, str] = {
        # Letters
        0x41: "KC_A",
        0x42: "KC_B",
        0x43: "KC_C",
        0x44: "KC_D",
        0x45: "KC_E",
        0x46: "KC_F",
        0x47: "KC_G",
        0x48: "KC_H",
        0x49: "KC_I",
        0x4A: "KC_J",
        0x4B: "KC_K",
        0x4C: "KC_L",
        0x4D: "KC_M",
        0x4E: "KC_N",
        0x4F: "KC_O",
        0x50: "KC_P",
        0x51: "KC_Q",
        0x52: "KC_R",
        0x53: "KC_S",
        0x54: "KC_T",
        0x55: "KC_U",
        0x56: "KC_V",
        0x57: "KC_W",
        0x58: "KC_X",
        0x59: "KC_Y",
        0x5A: "KC_Z",
        # Numbers
        0x30: "KC_0",
        0x31: "KC_1",
        0x32: "KC_2",
        0x33: "KC_3",
        0x34: "KC_4",
        0x35: "KC_5",
        0x36: "KC_6",
        0x37: "KC_7",
        0x38: "KC_8",
        0x39: "KC_9",
        # Function keys
        0x70: "KC_F1",
        0x71: "KC_F2",
        0x72: "KC_F3",
        0x73: "KC_F4",
        0x74: "KC_F5",
        0x75: "KC_F6",
        0x76: "KC_F7",
        0x77: "KC_F8",
        0x78: "KC_F9",
        0x79: "KC_F10",
        0x7A: "KC_F11",
        0x7B: "KC_F12",
        # Modifiers
        0x10: "KC_LSFT",
        0x11: "KC_LCTL",
        0x12: "KC_LALT",
        0x5B: "KC_LGUI",
        0x5C: "KC_RGUI",
        0xA0: "KC_LSFT",  # VK_LSHIFT
        0xA1: "KC_RSFT",  # VK_RSHIFT
        0xA2: "KC_LCTL",  # VK_LCONTROL
        0xA3: "KC_RCTL",  # VK_RCONTROL
        0xA4: "KC_LALT",  # VK_LMENU
        0xA5: "KC_RALT",  # VK_RMENU
        # Special keys
        0x1B: "KC_ESC",
        0x09: "KC_TAB",
        0x14: "KC_CAPS",
        0x20: "KC_SPC",
        0x0D: "KC_ENT",
        0x08: "KC_BSPC",
        0x2E: "KC_DEL",
        0x2D: "KC_INS",
        0x24: "KC_HOME",
        0x23: "KC_END",
        0x21: "KC_PGUP",
        0x22: "KC_PGDN",
        # Arrow keys
        0x25: "KC_LEFT",
        0x26: "KC_UP",
        0x27: "KC_RIGHT",
        0x28: "KC_DOWN",
        # Punctuation
        0xBA: "KC_SCLN",  # ;:
        0xBB: "KC_EQL",  # =+
        0xBC: "KC_COMM",  # ,<
        0xBD: "KC_MINS",  # -_
        0xBE: "KC_DOT",  # .>
        0xBF: "KC_SLSH",  # /?
        0xC0: "KC_GRV",  # `~
        0xDB: "KC_LBRC",  # [{
        0xDC: "KC_BSLS",  # \|
        0xDD: "KC_RBRC",  # ]}
        0xDE: "KC_QUOT",  # '"
        # Print screen, scroll lock, pause
        0x2C: "KC_PSCR",
        0x91: "KC_SLCK",
        0x13: "KC_PAUS",
    }

    # Hardware set-1 scancodes to QMK keycode names.
    # Used when we need the physical key independent of the currently active layer.
    SCANCODE_TO_QMK: dict[int, str] = {
        0x10: "KC_Q", 0x11: "KC_W", 0x12: "KC_E", 0x13: "KC_R", 0x14: "KC_T",
        0x1E: "KC_A", 0x1F: "KC_S", 0x20: "KC_D", 0x21: "KC_F", 0x22: "KC_G",
        0x2C: "KC_Z", 0x2D: "KC_X", 0x2E: "KC_C", 0x2F: "KC_V", 0x30: "KC_B",
        0x19: "KC_P", 0x18: "KC_O", 0x17: "KC_I", 0x16: "KC_U", 0x15: "KC_Y",
        0x28: "KC_QUOT", 0x26: "KC_L", 0x25: "KC_K", 0x24: "KC_J", 0x23: "KC_H",
        0x35: "KC_SLSH", 0x34: "KC_DOT", 0x33: "KC_COMM", 0x32: "KC_M", 0x31: "KC_N",
        0x39: "KC_SPC", 0x1C: "KC_ENT", 0x2A: "KC_LSFT", 0x1D: "KC_LCTL", 0x2E0: "KC_RCTL",
        0x52: "KC_INS", 0x4F: "KC_END", 0x47: "KC_HOME", 0x49: "KC_PGUP", 0x51: "KC_PGDN",
        0x4B: "KC_LEFT", 0x48: "KC_UP", 0x50: "KC_DOWN", 0x4D: "KC_RGHT", 0x3A: "KC_CAPS",
    }

    # Regex patterns for extracting tap key from MT/LT
    MT_PATTERN = re.compile(r"MT\([^,]+,\s*([^)]+)\)")
    LT_PATTERN = re.compile(r"LT\(\d+,\s*([^)]+)\)")
    # Pattern to extract modifier(s) from MT (e.g., "MOD_LGUI | MOD_RGUI" or "MOD_LSFT")
    MT_MOD_PATTERN = re.compile(r"MT\(([^,]+),\s*[^)]+\)")

    def __init__(self, keymap: Keymap, base_layer: int = 0) -> None:
        self.keymap = keymap
        self.base_layer = base_layer
        self.qmk_to_index: dict[str, int] = {}
        # Track which QMK codes are hold modifiers (not tap keys)
        self._hold_modifiers: set[str] = set()
        self._build_reverse_map()

    def _build_reverse_map(self) -> None:
        """Build QMK keycode -> key index mapping from base layer."""
        self.qmk_to_index.clear()
        self._hold_modifiers.clear()

        if self.base_layer >= len(self.keymap.layers):
            return

        layer = self.keymap.layers[self.base_layer]

        for index, keycode in enumerate(layer):
            # Extract the tap key from MT/LT
            tap_key = self._extract_tap_key(keycode)
            if tap_key and tap_key not in ("KC_NO", "KC_TRNS"):
                # Only store first occurrence
                if tap_key not in self.qmk_to_index:
                    self.qmk_to_index[tap_key] = index

            # Also extract hold modifiers from MT keys
            hold_mods = self._extract_hold_modifiers(keycode)
            for mod_key in hold_mods:
                # Map modifier to same key index (don't overwrite if exists)
                if mod_key not in self.qmk_to_index:
                    self.qmk_to_index[mod_key] = index
                # Track this as a hold modifier
                self._hold_modifiers.add(mod_key)

    def _extract_tap_key(self, keycode: str) -> str | None:
        """Extract the tap key from MT/LT or return the keycode itself."""
        keycode = keycode.strip()

        if keycode in ("KC_NO", "KC_TRNS"):
            return keycode

        # Mod-Tap
        if match := self.MT_PATTERN.match(keycode):
            return match.group(1)

        # Layer-Tap
        if match := self.LT_PATTERN.match(keycode):
            return match.group(1)

        # Regular keycode
        if keycode.startswith("KC_"):
            return keycode

        return None

    def _extract_hold_modifiers(self, keycode: str) -> list[str]:
        """Extract hold modifier keys from MT keycode.

        For MT(MOD_LGUI | MOD_RGUI, KC_A), returns ["KC_LGUI", "KC_RGUI"].
        For non-MT keycodes, returns empty list.
        """
        keycode = keycode.strip()
        result = []

        # Only process MT keycodes
        if match := self.MT_MOD_PATTERN.match(keycode):
            mods_str = match.group(1)
            # Parse "MOD_LGUI | MOD_RGUI" or just "MOD_LSFT"
            for part in mods_str.split("|"):
                mod_name = part.strip()
                if mod_name in self.MOD_TO_QMK:
                    result.append(self.MOD_TO_QMK[mod_name])

        return result

    def vk_to_key_index(self, vk_code: int) -> int | None:
        """Convert Windows VK code to key index in layout."""
        qmk_code = self.VK_TO_QMK.get(vk_code)
        if qmk_code:
            return self.qmk_to_index.get(qmk_code)
        return None

    def scancode_to_key_index(self, scancode: int) -> int | None:
        """Convert Windows hardware scancode to physical key index in layout."""
        qmk_code = self.SCANCODE_TO_QMK.get(scancode)
        if qmk_code:
            return self.qmk_to_index.get(qmk_code)
        return None

    def vk_to_qmk(self, vk_code: int) -> str | None:
        """Convert Windows VK code to QMK keycode name."""
        return self.VK_TO_QMK.get(vk_code)

    def is_hold_action(self, vk_code: int) -> bool:
        """Check if a VK code represents a hold action on an MT key.

        Returns True if the VK code maps to a modifier that was extracted
        from an MT key (meaning this keypress is a hold action, not a tap).
        """
        qmk_code = self.VK_TO_QMK.get(vk_code)
        if qmk_code:
            return qmk_code in self._hold_modifiers
        return False

    def rebuild_map(self, base_layer: int = 0) -> None:
        """Rebuild the reverse map with a different base layer."""
        self.base_layer = base_layer
        self._build_reverse_map()
