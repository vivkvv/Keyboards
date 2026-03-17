"""QMK keycode parser - converts keycodes to human-readable labels."""

import re
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..input.keyboard_layout import KeyboardLayoutDetector


@dataclass
class KeyLabels:
    """Parsed key labels for display."""
    tap: str       # Main tap action (shown larger, at bottom)
    hold: str      # Hold action (shown smaller, at top) - empty if no hold
    raw: str       # Original keycode


class QMKKeycodeParser:
    """
    Parses QMK keycodes to human-readable labels.

    Handles:
    - Basic: KC_Q -> "Q", KC_1 -> "1", KC_ESC -> "Esc"
    - Mod-Tap: MT(MOD_LGUI,KC_A) -> "A" (shows tap key)
    - Layer-Tap: LT(4,KC_Z) -> "Z" (shows tap key)
    - Shifted: S(KC_LBRC) -> "{" (shows shifted symbol)
    - Transparent: KC_TRNS -> "▽"
    - No key: KC_NO -> ""
    - Custom: CUSTOM(0) -> "C0"
    - RGB/Media: RGB_TOG -> "RGB", KC_VOLU -> "Vol+"
    """

    # Regex patterns
    MT_PATTERN = re.compile(r"MT\(([^,]+),\s*([^)]+)\)")  # MT(mods, kc)
    LT_PATTERN = re.compile(r"LT\((\d+),\s*([^)]+)\)")  # LT(layer, kc)
    S_PATTERN = re.compile(r"S\(([^)]+)\)")  # S(kc)
    CUSTOM_PATTERN = re.compile(r"CUSTOM\((\d+)\)")  # CUSTOM(n)

    # Shift symbol mapping
    SHIFT_MAP: dict[str, str] = {
        # Numbers
        "KC_1": "!",
        "KC_2": "@",
        "KC_3": "#",
        "KC_4": "$",
        "KC_5": "%",
        "KC_6": "^",
        "KC_7": "&",
        "KC_8": "*",
        "KC_9": "(",
        "KC_0": ")",
        # Punctuation
        "KC_MINS": "_",
        "KC_EQL": "+",
        "KC_LBRC": "{",
        "KC_RBRC": "}",
        "KC_BSLS": "|",
        "KC_SCLN": ":",
        "KC_QUOT": '"',
        "KC_GRV": "~",
        "KC_COMM": "<",
        "KC_DOT": ">",
        "KC_SLSH": "?",
    }

    # Basic keycode to display label
    BASIC_MAP: dict[str, str] = {
        # Modifiers
        "KC_LCTL": "Ctrl",
        "KC_RCTL": "Ctrl",
        "KC_LSFT": "Shift",
        "KC_RSFT": "Shift",
        "KC_LALT": "Alt",
        "KC_RALT": "Alt",
        "KC_LGUI": "Win",
        "KC_RGUI": "Win",
        # Navigation
        "KC_LEFT": "←",
        "KC_RGHT": "→",
        "KC_RIGHT": "→",
        "KC_UP": "↑",
        "KC_DOWN": "↓",
        "KC_HOME": "Home",
        "KC_END": "End",
        "KC_PGUP": "PgUp",
        "KC_PGDN": "PgDn",
        # Editing
        "KC_SPC": "Space",
        "KC_ENT": "Enter",
        "KC_TAB": "Tab",
        "KC_BSPC": "Bksp",
        "KC_DEL": "Del",
        "KC_ESC": "Esc",
        "KC_INS": "Ins",
        "KC_CAPS": "Caps",
        # Function keys
        **{f"KC_F{i}": f"F{i}" for i in range(1, 13)},
        # Punctuation (unshifted)
        "KC_MINS": "-",
        "KC_EQL": "=",
        "KC_LBRC": "[",
        "KC_RBRC": "]",
        "KC_BSLS": "\\",
        "KC_SCLN": ";",
        "KC_QUOT": "'",
        "KC_GRV": "`",
        "KC_COMM": ",",
        "KC_DOT": ".",
        "KC_SLSH": "/",
        # Media
        "KC_MUTE": "Mute",
        "KC_VOLU": "Vol+",
        "KC_VOLD": "Vol-",
        "KC_MPLY": "Play",
        "KC_MSTP": "Stop",
        "KC_MPRV": "Prev",
        "KC_MNXT": "Next",
        # Mouse
        "KC_MS_BTN1": "M1",
        "KC_MS_BTN2": "M2",
        "KC_MS_BTN3": "M3",
        # Special
        "KC_PSCR": "PrtSc",
        "KC_SLCK": "ScrLk",
        "KC_PAUS": "Pause",
    }

    # Special non-KC_ keycodes
    SPECIAL_MAP: dict[str, str] = {
        "RESET": "RST",
        "QK_CLEAR_EEPROM": "CLR",
        "RGB_TOG": "RGB",
        "RGB_MOD": "RGB+",
        "RGB_RMOD": "RGB-",
        "LAS0": "LA+S+0",
        "LAS1": "LA+S+1",
        "LAS2": "LA+S+2",
        "LAS3": "LA+S+3",
        "LAS4": "LA+S+4",
        "LAS5": "LA+S+5",
        "LAS6": "LA+S+6",
        "LAS7": "LA+S+7",
        "LAS8": "LA+S+8",
        "LAS9": "LA+S+9",
    }

    # Modifier map for display
    MOD_MAP: dict[str, str] = {
        "MOD_LCTL": "Ctrl",
        "MOD_RCTL": "Ctrl",
        "MOD_LSFT": "Shift",
        "MOD_RSFT": "Shift",
        "MOD_LALT": "Alt",
        "MOD_RALT": "Alt",
        "MOD_LGUI": "Win",
        "MOD_RGUI": "Win",
    }

    def parse(self, keycode: str) -> str:
        """Parse keycode to display label (simple version, tap only)."""
        return self.parse_full(keycode).tap

    def parse_full(self, keycode: str) -> KeyLabels:
        """Parse keycode returning both tap and hold labels."""
        keycode = keycode.strip()

        # Empty/transparent
        if keycode == "KC_NO":
            return KeyLabels(tap="", hold="", raw=keycode)
        if keycode == "KC_TRNS":
            return KeyLabels(tap="▽", hold="", raw=keycode)

        # Mod-Tap: tap key + modifier on hold
        if match := self.MT_PATTERN.match(keycode):
            mod = match.group(1)
            tap_key = match.group(2)
            tap_label = self._parse_basic(tap_key)
            hold_label = self.MOD_MAP.get(mod, mod.replace("MOD_", ""))
            return KeyLabels(tap=tap_label, hold=hold_label, raw=keycode)

        # Layer-Tap: tap key + layer on hold
        if match := self.LT_PATTERN.match(keycode):
            layer = match.group(1)
            tap_key = match.group(2)
            tap_label = self._parse_basic(tap_key)
            hold_label = f"L{layer}"
            return KeyLabels(tap=tap_label, hold=hold_label, raw=keycode)

        # Shifted key
        if match := self.S_PATTERN.match(keycode):
            base_key = match.group(1)
            label = self.SHIFT_MAP.get(base_key, self._parse_basic(base_key))
            return KeyLabels(tap=label, hold="", raw=keycode)

        # Custom function
        if match := self.CUSTOM_PATTERN.match(keycode):
            return KeyLabels(tap=f"C{match.group(1)}", hold="", raw=keycode)

        # Special keycodes
        if keycode in self.SPECIAL_MAP:
            return KeyLabels(tap=self.SPECIAL_MAP[keycode], hold="", raw=keycode)

        # Basic keycode
        return KeyLabels(tap=self._parse_basic(keycode), hold="", raw=keycode)

    def _parse_basic(self, keycode: str) -> str:
        """Convert KC_X to display label."""
        # Check basic map first
        if keycode in self.BASIC_MAP:
            return self.BASIC_MAP[keycode]

        if keycode.startswith("KC_"):
            key = keycode[3:]  # Remove KC_ prefix

            # Single letter/number
            if len(key) == 1:
                return key

            # Return capitalized version for unknown keys
            return key.capitalize()

        # Return as-is for unknown patterns
        return keycode

    def parse_with_layout(
        self,
        keycode: str,
        layout_detector: "KeyboardLayoutDetector",
        hkl: Optional[int] = None,
        shift: bool = False,
        caps_lock: bool = False,
    ) -> KeyLabels:
        """Parse keycode using OS keyboard layout for character keys.

        For letter/number/punctuation keys, returns the actual character
        that would be produced with the current OS keyboard layout.
        For special keys (modifiers, navigation, etc.), returns QMK labels.

        Args:
            keycode: QMK keycode string
            layout_detector: Keyboard layout detector instance
            hkl: Keyboard layout handle (optional)
            shift: If True, return shifted characters
        """
        keycode = keycode.strip()

        # Empty/transparent - same as regular parse
        if keycode in ("KC_NO", "KC_TRNS"):
            return self.parse_full(keycode)

        # Mod-Tap: tap key + modifier on hold
        if match := self.MT_PATTERN.match(keycode):
            mod = match.group(1)
            tap_key = match.group(2)
            # Try to get layout-aware tap label
            tap_label = self._get_layout_char(tap_key, layout_detector, hkl, shift, caps_lock)
            hold_label = self.MOD_MAP.get(mod, mod.replace("MOD_", ""))
            return KeyLabels(tap=tap_label, hold=hold_label, raw=keycode)

        # Layer-Tap: tap key + layer on hold
        if match := self.LT_PATTERN.match(keycode):
            layer = match.group(1)
            tap_key = match.group(2)
            tap_label = self._get_layout_char(tap_key, layout_detector, hkl, shift, caps_lock)
            hold_label = f"L{layer}"
            return KeyLabels(tap=tap_label, hold=hold_label, raw=keycode)

        # Shifted key - already shifted, don't apply shift again
        if match := self.S_PATTERN.match(keycode):
            base_key = match.group(1)
            char = layout_detector.get_char_for_qmk(keycode, hkl, caps_lock=caps_lock)
            if char:
                return KeyLabels(tap=char, hold="", raw=keycode)
            # Fallback to QMK shift map
            label = self.SHIFT_MAP.get(base_key, self._parse_basic(base_key))
            return KeyLabels(tap=label, hold="", raw=keycode)

        # Custom/Special - use regular parsing
        if self.CUSTOM_PATTERN.match(keycode) or keycode in self.SPECIAL_MAP:
            return self.parse_full(keycode)

        # Basic keycode - try layout-aware with shift
        tap_label = self._get_layout_char(keycode, layout_detector, hkl, shift, caps_lock)
        return KeyLabels(tap=tap_label, hold="", raw=keycode)

    def _get_layout_char(
        self,
        keycode: str,
        layout_detector: "KeyboardLayoutDetector",
        hkl: Optional[int] = None,
        shift: bool = False,
        caps_lock: bool = False,
    ) -> str:
        """Get character for keycode using OS layout, fallback to QMK.

        Args:
            keycode: QMK keycode string
            layout_detector: Keyboard layout detector instance
            hkl: Keyboard layout handle (optional)
            shift: If True, get shifted character
        """
        # Get VK code for this keycode
        vk = layout_detector.QMK_TO_VK.get(keycode)
        if vk:
            char = layout_detector.vk_to_char(vk, shift=shift, hkl=hkl, caps_lock=caps_lock)
            if char:
                return char  # Return actual character that will be typed

        # Fallback to regular parsing
        return self._parse_basic(keycode)
