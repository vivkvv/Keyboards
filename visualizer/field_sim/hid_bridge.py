"""Standalone HID bridge for the field simulator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

try:
    import hid
except ImportError:
    hid = None

from .models import KeyCell


@dataclass
class KeyboardDevice:
    """Minimal info about a connected VIA-capable keyboard."""

    vendor_id: int
    product_id: int
    path: bytes
    product: str


class ViaCommand:
    GET_PROTOCOL_VERSION = 0x01
    LIGHTING_SET_VALUE = 0x07
    LIGHTING_GET_VALUE = 0x08


class RGBMatrixValue:
    BRIGHTNESS = 0x80
    EFFECT = 0x81


class ViaChannel:
    CUSTOM = 0x00


class VendorLedCommand:
    SET_LED = 1
    CLEAR_ALL = 3
    SET_MANUAL_MODE = 4
    GET_INFO = 5


class VendorLedResponse:
    INFO = 0x81


KNOWN_KEYBOARDS = {
    (0xA8F8, 0x1832): "Charybdis Nano",
}

# 40-slot visual layout -> firmware LED index.
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


class KeyboardLedBridge:
    """Send simulator colors to the physical keyboard without external project deps."""

    VIA_USAGE_PAGE = 0xFF60

    def __init__(self) -> None:
        self._device = None
        self._device_info: KeyboardDevice | None = None
        self._vendor_led_count: int | None = None
        self._last_error = ""

    def get_last_error(self) -> str:
        """Return the last connection/runtime error."""
        return self._last_error

    def _list_keyboards(self) -> list[KeyboardDevice]:
        """List VIA-compatible HID devices."""
        if hid is None:
            return []
        devices: list[KeyboardDevice] = []
        for device in hid.enumerate():
            if device.get("usage_page") != self.VIA_USAGE_PAGE:
                continue
            devices.append(
                KeyboardDevice(
                    vendor_id=device["vendor_id"],
                    product_id=device["product_id"],
                    path=device["path"],
                    product=device.get("product_string", ""),
                )
            )
        return devices

    def _send_raw(self, data: list[int]) -> bool:
        """Send one 32-byte VIA report."""
        if not self._device:
            return False
        report = [0x00] + data + [0x00] * (32 - len(data))
        try:
            self._device.write(report[:33])
            return True
        except Exception:
            return False

    def _send_and_receive(self, data: list[int], timeout_ms: int = 100) -> list[int] | None:
        """Send a report and wait for the response."""
        if not self._send_raw(data):
            return None
        try:
            response = self._device.read(33, timeout_ms)
        except Exception:
            return None
        if not response:
            return None
        response = list(response)
        if len(response) == 33 and response[0] == 0x00:
            return response[1:]
        return response[:32]

    def _send_via_custom(self, command_id: int, value_id: int, payload: list[int] | None = None) -> list[int] | None:
        """Send one VIA custom-channel command."""
        data = [command_id, ViaChannel.CUSTOM, value_id]
        if payload:
            data.extend(payload)
        return self._send_and_receive(data)

    def connect(self) -> bool:
        """Connect to a known keyboard and enable manual LED mode."""
        self._last_error = ""
        if hid is None:
            self._last_error = "hidapi is not installed"
            return False

        self.disconnect()
        devices = self._list_keyboards()
        target = None
        for device in devices:
            if (device.vendor_id, device.product_id) in KNOWN_KEYBOARDS:
                target = device
                break
        if target is None and devices:
            target = devices[0]
        if target is None:
            self._last_error = "No VIA-compatible keyboard found"
            return False

        try:
            self._device = hid.device()
            self._device.open_path(target.path)
            self._device.set_nonblocking(True)
            self._device_info = target
        except Exception as exc:
            self._last_error = f"open_path failed: {exc}"
            self.disconnect()
            return False

        info = self._send_via_custom(ViaCommand.LIGHTING_GET_VALUE, VendorLedCommand.GET_INFO)
        if not info or info[0] != VendorLedResponse.INFO:
            self._last_error = "Keyboard did not respond to vendor GET_INFO"
            self.disconnect()
            return False
        self._vendor_led_count = info[1]

        self.set_rgb_effect(1)
        self.set_rgb_brightness(0)
        self.set_manual_led_mode(True)
        self.clear_manual_leds()
        return True

    def disconnect(self) -> None:
        """Disconnect from the keyboard."""
        if self._device:
            try:
                self._device.close()
            except Exception:
                pass
        self._device = None
        self._device_info = None
        self._vendor_led_count = None

    def is_connected(self) -> bool:
        """Return whether the bridge currently holds an open HID connection."""
        return self._device is not None

    def set_rgb_effect(self, effect_id: int) -> bool:
        """Set RGB matrix effect."""
        return self._send_raw([ViaCommand.LIGHTING_SET_VALUE, RGBMatrixValue.EFFECT, effect_id])

    def set_rgb_brightness(self, brightness: int) -> bool:
        """Set RGB brightness."""
        return self._send_raw([ViaCommand.LIGHTING_SET_VALUE, RGBMatrixValue.BRIGHTNESS, brightness])

    def set_manual_led_mode(self, enabled: bool) -> bool:
        """Enable or disable firmware manual LED mode."""
        response = self._send_via_custom(
            ViaCommand.LIGHTING_SET_VALUE,
            VendorLedCommand.SET_MANUAL_MODE,
            [1 if enabled else 0],
        )
        return response is not None

    def clear_manual_leds(self) -> bool:
        """Clear all LEDs controlled by manual mode."""
        response = self._send_via_custom(
            ViaCommand.LIGHTING_SET_VALUE,
            VendorLedCommand.CLEAR_ALL,
        )
        return response is not None

    def set_manual_led(self, led_index: int, r: int, g: int, b: int) -> bool:
        """Set one LED through the vendor protocol."""
        if self._vendor_led_count is not None and not (0 <= led_index < self._vendor_led_count):
            return False
        response = self._send_via_custom(
            ViaCommand.LIGHTING_SET_VALUE,
            VendorLedCommand.SET_LED,
            [led_index, r, g, b],
        )
        return response is not None

    def push_colors(self, cells: Iterable[KeyCell], colors: Iterable[tuple[int, int, int]]) -> bool:
        """Send current cell colors to the physical keyboard."""
        if not self.is_connected():
            return False

        self.set_manual_led_mode(True)
        ok = True
        for cell, color in zip(cells, colors):
            led_index = None
            if 0 <= cell.source_index < len(CHARYBDIS_NANO_KEY_TO_LED):
                led_index = CHARYBDIS_NANO_KEY_TO_LED[cell.source_index]
            if led_index is None:
                continue
            ok = self.set_manual_led(led_index, color[0], color[1], color[2]) and ok
        return ok
