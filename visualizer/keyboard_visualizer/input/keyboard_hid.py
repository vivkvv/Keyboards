"""HID communication with QMK/VIA keyboards for RGB control and keymap reading."""

import time
import threading
from typing import Optional
from dataclasses import dataclass

from ..models import Keymap

try:
    import hid
    HID_AVAILABLE = True
except ImportError:
    HID_AVAILABLE = False


@dataclass
class KeyboardDevice:
    """Information about a connected keyboard."""
    vendor_id: int
    product_id: int
    path: bytes
    manufacturer: str
    product: str
    serial: str


# VIA Protocol command IDs
class ViaCommand:
    GET_PROTOCOL_VERSION = 0x01
    DYNAMIC_KEYMAP_GET_KEYCODE = 0x04
    LIGHTING_SET_VALUE = 0x07
    LIGHTING_GET_VALUE = 0x08
    LIGHTING_SAVE = 0x09
    DYNAMIC_KEYMAP_MACRO_GET_COUNT = 0x0C
    DYNAMIC_KEYMAP_MACRO_GET_BUFFER_SIZE = 0x0D
    DYNAMIC_KEYMAP_MACRO_GET_BUFFER = 0x0E
    DYNAMIC_KEYMAP_GET_LAYER_COUNT = 0x11
    DYNAMIC_KEYMAP_GET_BUFFER = 0x12
    RGBLIGHT_SET_COLOR = 0x05  # For RGBLIGHT
    RGB_MATRIX_SET_COLOR = 0x24  # For RGB Matrix


# RGB Matrix lighting value IDs (for id_lighting_set_value)
class RGBMatrixValue:
    BRIGHTNESS = 0x80
    EFFECT = 0x81
    EFFECT_SPEED = 0x82
    COLOR_HUE = 0x83  # HSV Hue (0-255)
    COLOR_SAT = 0x84  # HSV Saturation (0-255)


class ViaChannel:
    CUSTOM = 0x00


class VendorLedCommand:
    SET_LED = 1
    SET_ALL = 2
    CLEAR_ALL = 3
    SET_MANUAL_MODE = 4
    GET_INFO = 5
    GET_HIGHEST_LAYER = 6
    GET_LAST_KEY_EVENT = 7


class VendorLedResponse:
    INFO = 0x81
    HIGHEST_LAYER = 0x82
    LAST_KEY_EVENT = 0x83
    ERROR = 0xFF


class VendorKeyEventType:
    NONE = 0
    DOWN = 1
    UP = 2


@dataclass
class VendorKeyEvent:
    """Last keyboard event reported by vendor firmware."""
    counter: int
    event_type: int
    key_index: int


# Known QMK keyboard VID/PIDs (Bastard Keyboards)
KNOWN_KEYBOARDS = {
    (0x1D50, 0x6192): "Charybdis",  # Bastardkb Charybdis
    (0xA8F8, 0x1832): "Charybdis Nano",  # Bastardkb Charybdis Nano Splinky
    (0xFEED, 0x6060): "Generic QMK",
}


# Visualizer key index in the 40-slot layout -> firmware LED index.
# Entries with None correspond to KC_NO placeholder slots.
CHARYBDIS_NANO_KEY_TO_LED = [
    2, 3, 8, 9, 12,
    1, 4, 7, 10, 13,
    0, 5, 6, 11, 14,
    15, None, 16, 17, None,
    20, 21, 26, 27, 30,
    19, 22, 25, 28, 31,
    18, 23, 24, 29, 32,
    33, None, 34, None, None,
]

# Default color used for per-key highlighting in the trainer/visualizer.
# Lower values make the highlight dimmer.
DEFAULT_HIGHLIGHT_COLOR = (255, 0, 0)
DEFAULT_HIGHLIGHT_DURATION_MS = 1000

_BASIC_KEYCODE_MAP: dict[int, str] = {
    0x0000: "KC_NO",
    0x0001: "KC_TRNS",
    0x0004: "KC_A",
    0x0005: "KC_B",
    0x0006: "KC_C",
    0x0007: "KC_D",
    0x0008: "KC_E",
    0x0009: "KC_F",
    0x000A: "KC_G",
    0x000B: "KC_H",
    0x000C: "KC_I",
    0x000D: "KC_J",
    0x000E: "KC_K",
    0x000F: "KC_L",
    0x0010: "KC_M",
    0x0011: "KC_N",
    0x0012: "KC_O",
    0x0013: "KC_P",
    0x0014: "KC_Q",
    0x0015: "KC_R",
    0x0016: "KC_S",
    0x0017: "KC_T",
    0x0018: "KC_U",
    0x0019: "KC_V",
    0x001A: "KC_W",
    0x001B: "KC_X",
    0x001C: "KC_Y",
    0x001D: "KC_Z",
    0x001E: "KC_1",
    0x001F: "KC_2",
    0x0020: "KC_3",
    0x0021: "KC_4",
    0x0022: "KC_5",
    0x0023: "KC_6",
    0x0024: "KC_7",
    0x0025: "KC_8",
    0x0026: "KC_9",
    0x0027: "KC_0",
    0x0028: "KC_ENT",
    0x0029: "KC_ESC",
    0x002A: "KC_BSPC",
    0x002B: "KC_TAB",
    0x002C: "KC_SPC",
    0x002D: "KC_MINS",
    0x002E: "KC_EQL",
    0x002F: "KC_LBRC",
    0x0030: "KC_RBRC",
    0x0031: "KC_BSLS",
    0x0033: "KC_SCLN",
    0x0034: "KC_QUOT",
    0x0035: "KC_GRV",
    0x0036: "KC_COMM",
    0x0037: "KC_DOT",
    0x0038: "KC_SLSH",
    0x0039: "KC_CAPS",
    0x003A: "KC_F1",
    0x003B: "KC_F2",
    0x003C: "KC_F3",
    0x003D: "KC_F4",
    0x003E: "KC_F5",
    0x003F: "KC_F6",
    0x0040: "KC_F7",
    0x0041: "KC_F8",
    0x0042: "KC_F9",
    0x0043: "KC_F10",
    0x0044: "KC_F11",
    0x0045: "KC_F12",
    0x0046: "KC_PSCR",
    0x0047: "KC_SLCK",
    0x0048: "KC_PAUS",
    0x0049: "KC_INS",
    0x004A: "KC_HOME",
    0x004B: "KC_PGUP",
    0x004C: "KC_DEL",
    0x004D: "KC_END",
    0x004E: "KC_PGDN",
    0x004F: "KC_RGHT",
    0x0050: "KC_LEFT",
    0x0051: "KC_DOWN",
    0x0052: "KC_UP",
    0x00A8: "KC_MUTE",
    0x00A9: "KC_VOLU",
    0x00AA: "KC_VOLD",
    0x00AB: "KC_MNXT",
    0x00AC: "KC_MPRV",
    0x00AD: "KC_MSTP",
    0x00AE: "KC_MPLY",
    0x00D1: "KC_MS_BTN1",
    0x00D2: "KC_MS_BTN2",
    0x00D3: "KC_MS_BTN3",
    0x00E0: "KC_LCTL",
    0x00E1: "KC_LSFT",
    0x00E2: "KC_LALT",
    0x00E3: "KC_LGUI",
    0x00E4: "KC_RCTL",
    0x00E5: "KC_RSFT",
    0x00E6: "KC_RALT",
    0x00E7: "KC_RGUI",
    0x7820: "RGB_TOG",
    0x7821: "RGB_MOD",
    0x7822: "RGB_RMOD",
    0x7C00: "RESET",
    0x7C01: "RESET",
    0x7C03: "QK_CLEAR_EEPROM",
}

_MOD_MASK_TO_NAME: dict[int, str] = {
    0x01: "MOD_LCTL",
    0x02: "MOD_LSFT",
    0x04: "MOD_LALT",
    0x08: "MOD_LGUI",
    0x18: "MOD_LGUI | MOD_RGUI",
    0x11: "MOD_LCTL | MOD_RCTL",
    0x12: "MOD_LSFT | MOD_RSFT",
    0x0C: "MOD_LGUI | MOD_RGUI",
}


def _decode_qmk_keycode(keycode: int) -> str:
    """Decode a raw 16-bit QMK keycode into a VIA-style string."""
    if keycode in _BASIC_KEYCODE_MAP:
        return _BASIC_KEYCODE_MAP[keycode]

    if 0x0100 <= keycode <= 0x1FFF:
        mods = (keycode >> 8) & 0x1F
        basic = _BASIC_KEYCODE_MAP.get(keycode & 0xFF)
        if basic is None:
            return f"0x{keycode:04X}"
        if mods == 0x02:
            return f"S({basic})"
        mod_name = _MOD_MASK_TO_NAME.get(mods, f"0x{mods:02X}")
        return f"MT({mod_name},{basic})"

    if 0x2000 <= keycode <= 0x3FFF:
        mods = (keycode >> 8) & 0x1F
        tap_key = _BASIC_KEYCODE_MAP.get(keycode & 0xFF)
        mod_name = _MOD_MASK_TO_NAME.get(mods, f"0x{mods:02X}")
        return f"MT({mod_name},{tap_key or f'0x{keycode & 0xFF:02X}'})"

    if 0x4000 <= keycode <= 0x4FFF:
        layer = (keycode >> 8) & 0x0F
        tap_key = _BASIC_KEYCODE_MAP.get(keycode & 0xFF)
        return f"LT({layer},{tap_key or f'0x{keycode & 0xFF:02X}'})"

    if 0x7E00 <= keycode <= 0x7E3F:
        return f"CUSTOM({keycode - 0x7E00})"

    if 0x7E40 <= keycode <= 0x7FFF:
        return f"CUSTOM({keycode - 0x7E00})"

    return f"0x{keycode:04X}"


def _parse_macro_buffer(raw: bytes, macro_count: int) -> list[str]:
    """Decode VIA macro buffer into string slots."""
    if macro_count <= 0:
        return []

    chunks = raw.split(b"\x00")
    macros = [chunk.decode("utf-8", errors="ignore") for chunk in chunks[:macro_count]]
    if len(macros) < macro_count:
        macros.extend([""] * (macro_count - len(macros)))
    return macros[:macro_count]


class KeyboardHID:
    """
    HID communication with QMK/VIA enabled keyboards.

    Allows sending RGB commands to highlight keys on the physical keyboard.
    """

    # VIA HID interface usage page and usage
    VIA_USAGE_PAGE = 0xFF60
    VIA_USAGE = 0x61

    def __init__(self):
        if not HID_AVAILABLE:
            raise ImportError("hidapi library not available. Install with: pip install hidapi")

        self._device: Optional[hid.device] = None
        self._device_info: Optional[KeyboardDevice] = None
        self._connected = False
        self._vendor_led_supported = False
        self._vendor_led_count: int | None = None
        self._highlight_timer: Optional[threading.Timer] = None
        self._highlight_generation = 0
        self._highlight_lock = threading.Lock()
        self._default_highlight_color: tuple[int, int, int] = DEFAULT_HIGHLIGHT_COLOR
        self._default_highlight_duration_ms = DEFAULT_HIGHLIGHT_DURATION_MS

    @staticmethod
    def list_keyboards() -> list[KeyboardDevice]:
        """List all connected HID devices that might be keyboards."""
        if not HID_AVAILABLE:
            return []

        keyboards = []
        for device in hid.enumerate():
            # Look for VIA-compatible devices (usage page 0xFF60)
            if device.get('usage_page') == KeyboardHID.VIA_USAGE_PAGE:
                keyboards.append(KeyboardDevice(
                    vendor_id=device['vendor_id'],
                    product_id=device['product_id'],
                    path=device['path'],
                    manufacturer=device.get('manufacturer_string', ''),
                    product=device.get('product_string', ''),
                    serial=device.get('serial_number', ''),
                ))
        return keyboards

    def connect(
        self,
        vendor_id: Optional[int] = None,
        product_id: Optional[int] = None,
        path: bytes | None = None,
    ) -> bool:
        """
        Connect to a keyboard.

        If VID/PID not specified, tries to find a known keyboard.
        """
        if self._connected:
            self.disconnect()

        keyboards = self.list_keyboards()
        if not keyboards:
            return False

        # Find matching keyboard
        target = None
        for kb in keyboards:
            if path is not None:
                if kb.path == path:
                    target = kb
                    break
            elif vendor_id and product_id:
                if kb.vendor_id == vendor_id and kb.product_id == product_id:
                    target = kb
                    break
            elif (kb.vendor_id, kb.product_id) in KNOWN_KEYBOARDS:
                target = kb
                break

        if not target:
            # Use first available if no known keyboard found
            target = keyboards[0]

        try:
            self._device = hid.device()
            self._device.open_path(target.path)
            self._device.set_nonblocking(True)
            self._device_info = target
            self._connected = True

            # Query protocol version
            self.get_protocol_version()
            self._detect_vendor_led_support()

            return True
        except Exception as e:
            print(f"Failed to connect to keyboard: {e}")
            self._device = None
            return False

    def disconnect(self):
        """Disconnect from the keyboard."""
        if self._device:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None
        self._connected = False
        self._device_info = None
        self._vendor_led_supported = False
        self._vendor_led_count = None
        with self._highlight_lock:
            self._highlight_generation += 1
            if self._highlight_timer:
                self._highlight_timer.cancel()
                self._highlight_timer = None

    def is_connected(self) -> bool:
        """Check if connected to a keyboard."""
        return self._connected

    def get_protocol_version(self) -> Optional[int]:
        """Query VIA protocol version."""
        response = self._send_and_receive([ViaCommand.GET_PROTOCOL_VERSION])
        if response and len(response) >= 3:
            version = (response[1] << 8) | response[2]
            return version
        return None

    def get_device_info(self) -> Optional[KeyboardDevice]:
        """Get info about connected device."""
        return self._device_info

    def get_dynamic_keymap_layer_count(self) -> int | None:
        """Return dynamic layer count reported by the device."""
        response = self._send_and_receive([ViaCommand.DYNAMIC_KEYMAP_GET_LAYER_COUNT])
        if response and len(response) >= 2 and response[0] == ViaCommand.DYNAMIC_KEYMAP_GET_LAYER_COUNT:
            return response[1]
        return None

    def get_dynamic_keymap_buffer(self, offset: int, size: int) -> bytes | None:
        """Read a chunk of the device dynamic keymap buffer."""
        response = self._send_and_receive(
            [
                ViaCommand.DYNAMIC_KEYMAP_GET_BUFFER,
                (offset >> 8) & 0xFF,
                offset & 0xFF,
                size & 0xFF,
            ]
        )
        if not response or len(response) < 4 or response[0] != ViaCommand.DYNAMIC_KEYMAP_GET_BUFFER:
            return None
        return bytes(response[4:4 + size])

    def get_dynamic_macro_count(self) -> int | None:
        """Return the number of macro slots."""
        response = self._send_and_receive([ViaCommand.DYNAMIC_KEYMAP_MACRO_GET_COUNT])
        if response and len(response) >= 2 and response[0] == ViaCommand.DYNAMIC_KEYMAP_MACRO_GET_COUNT:
            return response[1]
        return None

    def get_dynamic_macro_buffer_size(self) -> int | None:
        """Return the byte size of the dynamic macro buffer."""
        response = self._send_and_receive([ViaCommand.DYNAMIC_KEYMAP_MACRO_GET_BUFFER_SIZE])
        if response and len(response) >= 3 and response[0] == ViaCommand.DYNAMIC_KEYMAP_MACRO_GET_BUFFER_SIZE:
            return (response[1] << 8) | response[2]
        return None

    def get_dynamic_macro_buffer(self, offset: int, size: int) -> bytes | None:
        """Read a chunk of the dynamic macro buffer."""
        response = self._send_and_receive(
            [
                ViaCommand.DYNAMIC_KEYMAP_MACRO_GET_BUFFER,
                (offset >> 8) & 0xFF,
                offset & 0xFF,
                size & 0xFF,
            ]
        )
        if not response or len(response) < 4 or response[0] != ViaCommand.DYNAMIC_KEYMAP_MACRO_GET_BUFFER:
            return None
        return bytes(response[4:4 + size])

    def read_keymap(self, definition: dict) -> Keymap:
        """Read the current VIA dynamic keymap from the connected device."""
        if not self._connected or not self._device_info:
            raise RuntimeError("HID keyboard is not connected")

        matrix_rows = int(definition.get("matrixRows", 0) or 0)
        matrix_cols = int(definition.get("matrixCols", 0) or 0)
        if matrix_rows <= 0 or matrix_cols <= 0:
            raise ValueError("Keyboard definition is missing matrixRows/matrixCols")

        layer_count = self.get_dynamic_keymap_layer_count()
        if layer_count is None or layer_count <= 0:
            raise ValueError("Could not determine dynamic keymap layer count")

        matrix_to_visual = definition.get("matrixToVisual")
        visual_key_count = int(definition.get("visualKeyCount", matrix_rows * matrix_cols) or 0)
        if not isinstance(matrix_to_visual, list):
            matrix_to_visual = [
                list(range(row * matrix_cols, (row + 1) * matrix_cols))
                for row in range(matrix_rows)
            ]
            visual_key_count = matrix_rows * matrix_cols

        total_keymap_bytes = layer_count * matrix_rows * matrix_cols * 2
        keymap_raw = bytearray()
        offset = 0
        while offset < total_keymap_bytes:
            chunk_size = min(28, total_keymap_bytes - offset)
            chunk = self.get_dynamic_keymap_buffer(offset, chunk_size)
            if chunk is None or len(chunk) != chunk_size:
                raise RuntimeError(f"Failed to read dynamic keymap buffer at offset {offset}")
            keymap_raw.extend(chunk)
            offset += chunk_size

        layers: list[list[str]] = []
        for layer_index in range(layer_count):
            layer_keys = ["KC_NO"] * visual_key_count
            base = layer_index * matrix_rows * matrix_cols * 2
            for row in range(matrix_rows):
                row_map = matrix_to_visual[row] if row < len(matrix_to_visual) else []
                for col in range(matrix_cols):
                    visual_index = row_map[col] if col < len(row_map) else None
                    keycode_offset = base + ((row * matrix_cols) + col) * 2
                    raw_keycode = (keymap_raw[keycode_offset] << 8) | keymap_raw[keycode_offset + 1]
                    if isinstance(visual_index, int) and 0 <= visual_index < visual_key_count:
                        layer_keys[visual_index] = _decode_qmk_keycode(raw_keycode)
            layers.append(layer_keys)

        macro_count = self.get_dynamic_macro_count() or 0
        macros: list[str] = []
        macro_buffer_size = self.get_dynamic_macro_buffer_size() or 0
        if macro_count > 0 and macro_buffer_size > 0:
            macro_raw = bytearray()
            offset = 0
            while offset < macro_buffer_size:
                chunk_size = min(28, macro_buffer_size - offset)
                chunk = self.get_dynamic_macro_buffer(offset, chunk_size)
                if chunk is None or len(chunk) != chunk_size:
                    raise RuntimeError(f"Failed to read dynamic macro buffer at offset {offset}")
                macro_raw.extend(chunk)
                offset += chunk_size
            macros = _parse_macro_buffer(bytes(macro_raw), macro_count)

        vendor_product_id = (self._device_info.vendor_id << 16) | self._device_info.product_id
        return Keymap(
            name=self._device_info.product or definition.get("name", "HID Keyboard"),
            layers=layers,
            macros=macros,
            vendor_product_id=vendor_product_id,
        )

    def _send_raw(self, data: list[int]) -> bool:
        """Send raw HID report."""
        if not self._device:
            return False

        try:
            # Pad to 32 bytes (VIA protocol)
            report = [0x00] + data + [0x00] * (32 - len(data))
            self._device.write(report[:33])
            return True
        except Exception as e:
            print(f"HID write error: {e}")
            return False

    def _send_and_receive(self, data: list[int], timeout_ms: int = 100) -> Optional[list[int]]:
        """Send command and wait for response."""
        if not self._send_raw(data):
            return None

        try:
            # Wait for response
            response = self._device.read(33, timeout_ms)
            return list(response) if response else None
        except Exception:
            return None

    def _send_via_custom(self, command_id: int, value_id: int, payload: list[int] | None = None) -> Optional[list[int]]:
        """Send a VIA custom-channel command and return the response payload."""
        data = [command_id, ViaChannel.CUSTOM, value_id]
        if payload:
            data.extend(payload)
        response = self._send_and_receive(data)
        if not response:
            return None
        # Strip report ID if the backend returned 33 bytes.
        if len(response) == 33 and response[0] == 0x00:
            return response[1:]
        return response[:32]

    def _detect_vendor_led_support(self) -> None:
        """Detect support for the custom per-LED protocol used by the vendor firmware."""
        response = self._send_via_custom(ViaCommand.LIGHTING_GET_VALUE, VendorLedCommand.GET_INFO)
        if response and response[0] == VendorLedResponse.INFO:
            self._vendor_led_supported = True
            self._vendor_led_count = response[1]
        else:
            self._vendor_led_supported = False
            self._vendor_led_count = None

    def has_vendor_led_support(self) -> bool:
        """Return whether the connected keyboard supports the vendor LED protocol."""
        return self._vendor_led_supported

    def get_vendor_led_count(self) -> int | None:
        """Return LED count reported by the vendor LED protocol."""
        return self._vendor_led_count

    def get_highest_layer(self) -> int | None:
        """Return the keyboard's current highest active layer."""
        response = self._send_via_custom(
            ViaCommand.LIGHTING_GET_VALUE,
            VendorLedCommand.GET_HIGHEST_LAYER,
        )
        if not response or response[0] != VendorLedResponse.HIGHEST_LAYER:
            return None
        return response[1]

    def get_last_key_event(self) -> VendorKeyEvent | None:
        """Return the last firmware-level key event reported by the keyboard."""
        response = self._send_via_custom(
            ViaCommand.LIGHTING_GET_VALUE,
            VendorLedCommand.GET_LAST_KEY_EVENT,
        )
        if not response or response[0] != VendorLedResponse.LAST_KEY_EVENT or len(response) < 4:
            return None
        return VendorKeyEvent(
            counter=response[1],
            event_type=response[2],
            key_index=response[3],
        )

    def set_default_highlight_color(self, color: tuple[int, int, int]) -> None:
        """Set default RGB color used for key highlighting."""
        self._default_highlight_color = tuple(max(0, min(255, int(channel))) for channel in color[:3])

    def get_default_highlight_color(self) -> tuple[int, int, int]:
        """Return default RGB color used for key highlighting."""
        return self._default_highlight_color

    def set_default_highlight_duration_ms(self, duration_ms: int) -> None:
        """Set default highlight duration."""
        self._default_highlight_duration_ms = max(0, int(duration_ms))

    def get_default_highlight_duration_ms(self) -> int:
        """Return default highlight duration."""
        return self._default_highlight_duration_ms

    def set_manual_led_mode(self, enabled: bool) -> bool:
        """Enable or disable vendor manual LED mode."""
        if not self._vendor_led_supported:
            return False
        response = self._send_via_custom(
            ViaCommand.LIGHTING_SET_VALUE,
            VendorLedCommand.SET_MANUAL_MODE,
            [1 if enabled else 0],
        )
        return response is not None

    def clear_manual_leds(self) -> bool:
        """Clear all vendor-controlled LEDs."""
        if not self._vendor_led_supported:
            return False
        response = self._send_via_custom(
            ViaCommand.LIGHTING_SET_VALUE,
            VendorLedCommand.CLEAR_ALL,
        )
        return response is not None

    def set_manual_led(self, led_index: int, r: int, g: int, b: int) -> bool:
        """Set one LED through the vendor per-LED protocol."""
        if not self._vendor_led_supported:
            return False
        if self._vendor_led_count is not None and not (0 <= led_index < self._vendor_led_count):
            return False
        response = self._send_via_custom(
            ViaCommand.LIGHTING_SET_VALUE,
            VendorLedCommand.SET_LED,
            [led_index, r, g, b],
        )
        return response is not None

    def _clear_after_delay(self, generation: int) -> None:
        """Turn off the currently highlighted LED if it has not been superseded."""
        with self._highlight_lock:
            if generation != self._highlight_generation or not self._connected:
                return
            self.clear_manual_leds()
            self._highlight_timer = None

    def _key_to_led_index(self, key_index: int) -> int | None:
        """Map visualizer key index to firmware LED index for known keyboards."""
        if not self._device_info:
            return None
        if (self._device_info.vendor_id, self._device_info.product_id) == (0xA8F8, 0x1832):
            if 0 <= key_index < len(CHARYBDIS_NANO_KEY_TO_LED):
                return CHARYBDIS_NANO_KEY_TO_LED[key_index]
        return key_index

    def set_key_color(self, key_index: int, r: int, g: int, b: int) -> bool:
        """
        Set the color of a specific key LED.

        Note: This is not supported by standard VIA protocol.
        Use flash_color() for global RGB control instead.

        Args:
            key_index: The LED index (may differ from key matrix index)
            r, g, b: Color values 0-255
        """
        # Per-key RGB control is not supported by standard VIA protocol
        # This method is kept for potential future firmware support
        cmd = [ViaCommand.LIGHTING_SET_VALUE, ViaCommand.RGB_MATRIX_SET_COLOR, key_index, r, g, b]
        return self._send_raw(cmd)

    def highlight_key(
        self,
        key_index: int,
        duration_ms: int | None = None,
        color: tuple[int, int, int] | None = None,
    ) -> bool:
        """
        Highlight one key for a limited time.

        For vendor firmware with custom LED support this lights only the
        requested LED. If another key is highlighted before the timeout expires,
        the previous LED is turned off immediately and the new one takes over.

        Args:
            key_index: Visualizer key index
            duration_ms: How long the key should stay lit
            color: RGB color tuple
        """
        effective_duration_ms = self._default_highlight_duration_ms if duration_ms is None else max(0, duration_ms)
        effective_color = self._default_highlight_color if color is None else color

        if self._vendor_led_supported:
            led_index = self._key_to_led_index(key_index)
            if led_index is None:
                return False
            # Keep the RGB matrix pipeline alive but make the background effectively black.
            self.set_rgb_effect(1)
            self.set_rgb_brightness(0)
            self.set_manual_led_mode(True)
            with self._highlight_lock:
                self._highlight_generation += 1
                generation = self._highlight_generation
                if self._highlight_timer:
                    self._highlight_timer.cancel()
                    self._highlight_timer = None
                self.clear_manual_leds()
                ok = self.set_manual_led(
                    led_index,
                    effective_color[0],
                    effective_color[1],
                    effective_color[2],
                )
                if not ok:
                    return False
                self._highlight_timer = threading.Timer(
                    effective_duration_ms / 1000.0,
                    self._clear_after_delay,
                    args=(generation,),
                )
                self._highlight_timer.daemon = True
                self._highlight_timer.start()
                return True

        # Use key index to vary the color slightly for visual feedback
        # Map key index to hue (0-255)
        hue = (key_index * 17) % 256  # Spread colors across spectrum
        return self.flash_color(hue, effective_duration_ms)

    def reset_lighting(self) -> bool:
        """Reset lighting to default state."""
        # Send lighting save command to restore defaults
        return self._send_raw([ViaCommand.LIGHTING_SAVE])

    def set_rgb_effect(self, effect_id: int) -> bool:
        """Set RGB Matrix effect.

        Common effects: 0=Off, 1=Solid, 2-... various animations
        """
        cmd = [ViaCommand.LIGHTING_SET_VALUE, RGBMatrixValue.EFFECT, effect_id]
        return self._send_raw(cmd)

    def set_rgb_color_hsv(self, hue: int, saturation: int) -> bool:
        """Set RGB color using HSV (Hue 0-255, Saturation 0-255).

        Hue: 0=Red, 85=Green, 170=Blue
        """
        # Set hue
        self._send_raw([ViaCommand.LIGHTING_SET_VALUE, RGBMatrixValue.COLOR_HUE, hue])
        # Set saturation
        self._send_raw([ViaCommand.LIGHTING_SET_VALUE, RGBMatrixValue.COLOR_SAT, saturation])
        return True

    def set_rgb_brightness(self, brightness: int) -> bool:
        """Set RGB brightness (0-255)."""
        return self._send_raw([ViaCommand.LIGHTING_SET_VALUE, RGBMatrixValue.BRIGHTNESS, brightness])

    def flash_color(self, hue: int = 128, duration_ms: int = 500) -> bool:
        """Flash keyboard with a color (for visual feedback).

        Args:
            hue: Color hue (0-255). 0=Red, 85=Green, 128=Cyan, 170=Blue
            duration_ms: Duration (not implemented - just sets color)
        """
        # Set to solid color effect
        self.set_rgb_effect(1)  # Solid color
        # Set the color
        self.set_rgb_color_hsv(hue, 255)  # Full saturation
        return True


# Singleton instance
_keyboard_hid: Optional[KeyboardHID] = None


def get_keyboard_hid() -> Optional[KeyboardHID]:
    """Get the global KeyboardHID instance."""
    global _keyboard_hid
    if _keyboard_hid is None:
        try:
            _keyboard_hid = KeyboardHID()
        except ImportError:
            return None
    return _keyboard_hid
