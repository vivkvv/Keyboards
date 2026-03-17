"""HID communication with QMK/VIA keyboards for RGB control."""

import time
import threading
from typing import Optional
from dataclasses import dataclass

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
    LIGHTING_SET_VALUE = 0x07
    LIGHTING_GET_VALUE = 0x08
    LIGHTING_SAVE = 0x09
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

    def connect(self, vendor_id: Optional[int] = None, product_id: Optional[int] = None) -> bool:
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
            if vendor_id and product_id:
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
