"""Windows keyboard layout detection and character mapping."""

import ctypes
from ctypes import wintypes
from typing import Optional

user32 = ctypes.windll.user32

# Windows API functions
GetKeyboardLayout = user32.GetKeyboardLayout
GetKeyboardLayout.argtypes = [wintypes.DWORD]
GetKeyboardLayout.restype = wintypes.HKL

GetForegroundWindow = user32.GetForegroundWindow
GetForegroundWindow.argtypes = []
GetForegroundWindow.restype = wintypes.HWND

GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
GetWindowThreadProcessId.restype = wintypes.DWORD

ToUnicodeEx = user32.ToUnicodeEx
ToUnicodeEx.argtypes = [
    wintypes.UINT,  # wVirtKey
    wintypes.UINT,  # wScanCode
    ctypes.POINTER(ctypes.c_ubyte),  # lpKeyState
    ctypes.c_wchar_p,  # pwszBuff
    ctypes.c_int,  # cchBuff
    wintypes.UINT,  # wFlags
    wintypes.HKL,  # dwhkl
]
ToUnicodeEx.restype = ctypes.c_int

MapVirtualKeyExW = user32.MapVirtualKeyExW
MapVirtualKeyExW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.HKL]
MapVirtualKeyExW.restype = wintypes.UINT

GetKeyState = user32.GetKeyState
GetKeyState.argtypes = [wintypes.INT]
GetKeyState.restype = wintypes.SHORT

# Constants
MAPVK_VK_TO_VSC = 0
VK_CAPITAL = 0x14


class KeyboardLayoutDetector:
    """Detects current keyboard layout and maps VK codes to characters."""

    # VK codes for printable keys (letters, numbers, punctuation)
    PRINTABLE_VK_CODES = [
        # Letters A-Z
        *range(0x41, 0x5B),
        # Numbers 0-9
        *range(0x30, 0x3A),
        # Punctuation
        0xBA,  # ;:
        0xBB,  # =+
        0xBC,  # ,<
        0xBD,  # -_
        0xBE,  # .>
        0xBF,  # /?
        0xC0,  # `~
        0xDB,  # [{
        0xDC,  # \|
        0xDD,  # ]}
        0xDE,  # '"
    ]

    # QMK keycode to VK code mapping
    QMK_TO_VK = {
        "KC_A": 0x41, "KC_B": 0x42, "KC_C": 0x43, "KC_D": 0x44,
        "KC_E": 0x45, "KC_F": 0x46, "KC_G": 0x47, "KC_H": 0x48,
        "KC_I": 0x49, "KC_J": 0x4A, "KC_K": 0x4B, "KC_L": 0x4C,
        "KC_M": 0x4D, "KC_N": 0x4E, "KC_O": 0x4F, "KC_P": 0x50,
        "KC_Q": 0x51, "KC_R": 0x52, "KC_S": 0x53, "KC_T": 0x54,
        "KC_U": 0x55, "KC_V": 0x56, "KC_W": 0x57, "KC_X": 0x58,
        "KC_Y": 0x59, "KC_Z": 0x5A,
        "KC_1": 0x31, "KC_2": 0x32, "KC_3": 0x33, "KC_4": 0x34,
        "KC_5": 0x35, "KC_6": 0x36, "KC_7": 0x37, "KC_8": 0x38,
        "KC_9": 0x39, "KC_0": 0x30,
        "KC_SCLN": 0xBA, "KC_EQL": 0xBB, "KC_COMM": 0xBC,
        "KC_MINS": 0xBD, "KC_DOT": 0xBE, "KC_SLSH": 0xBF,
        "KC_GRV": 0xC0, "KC_LBRC": 0xDB, "KC_BSLS": 0xDC,
        "KC_RBRC": 0xDD, "KC_QUOT": 0xDE,
    }

    def __init__(self):
        self._cached_layout: Optional[int] = None
        self._cached_chars: dict[int, str] = {}

    def get_current_layout(self) -> int:
        """Get the keyboard layout for the current foreground window."""
        hwnd = GetForegroundWindow()
        thread_id = GetWindowThreadProcessId(hwnd, None)
        return GetKeyboardLayout(thread_id)

    def get_foreground_window_handle(self) -> int:
        """Return the current foreground window handle."""
        return int(GetForegroundWindow())

    def get_layout_name(self, hkl: Optional[int] = None) -> str:
        """Get a human-readable name for the keyboard layout."""
        if hkl is None:
            hkl = self.get_current_layout()

        # Language ID is in the low word
        lang_id = hkl & 0xFFFF

        # Common language IDs
        lang_names = {
            0x0409: "EN-US",
            0x0809: "EN-UK",
            0x0419: "RU",
            0x0422: "UK",  # Ukrainian
            0x0407: "DE",
            0x040C: "FR",
            0x0410: "IT",
            0x0C0A: "ES",
            0x0415: "PL",
        }

        return lang_names.get(lang_id, f"0x{lang_id:04X}")

    def get_caps_lock_state(self) -> bool:
        """Return whether Caps Lock is currently enabled."""
        return bool(GetKeyState(VK_CAPITAL) & 0x0001)

    def vk_to_char(
        self,
        vk_code: int,
        shift: bool = False,
        hkl: Optional[int] = None,
        caps_lock: bool = False,
    ) -> Optional[str]:
        """Convert a VK code to a character using the specified keyboard layout."""
        if hkl is None:
            hkl = self.get_current_layout()

        # Get scan code
        scan_code = MapVirtualKeyExW(vk_code, MAPVK_VK_TO_VSC, hkl)

        # Prepare key state array (256 bytes)
        key_state = (ctypes.c_ubyte * 256)()
        if shift:
            key_state[0x10] = 0x80  # VK_SHIFT
        if caps_lock:
            key_state[VK_CAPITAL] = 0x01

        # Buffer for result
        buffer = ctypes.create_unicode_buffer(5)

        # Convert to unicode
        result = ToUnicodeEx(
            vk_code,
            scan_code,
            key_state,
            buffer,
            5,
            0,
            hkl
        )

        if result > 0:
            return buffer.value[:result]
        return None

    def get_char_for_qmk(
        self,
        qmk_code: str,
        hkl: Optional[int] = None,
        caps_lock: bool = False,
    ) -> Optional[str]:
        """Get the character for a QMK keycode based on current layout.

        Returns the character that would be produced when pressing this key
        with the given keyboard layout.
        """
        # Handle shifted keys like S(KC_1) -> !
        if qmk_code.startswith("S(") and qmk_code.endswith(")"):
            inner = qmk_code[2:-1]
            vk = self.QMK_TO_VK.get(inner)
            if vk:
                return self.vk_to_char(vk, shift=True, hkl=hkl, caps_lock=caps_lock)
            return None

        vk = self.QMK_TO_VK.get(qmk_code)
        if vk:
            return self.vk_to_char(vk, shift=False, hkl=hkl, caps_lock=caps_lock)
        return None

    def build_char_map(self, hkl: Optional[int] = None, caps_lock: bool = False) -> dict[int, tuple[str, str]]:
        """Build a map of VK codes to (normal_char, shifted_char) for current layout."""
        if hkl is None:
            hkl = self.get_current_layout()

        char_map = {}
        for vk in self.PRINTABLE_VK_CODES:
            normal = self.vk_to_char(vk, shift=False, hkl=hkl, caps_lock=caps_lock)
            shifted = self.vk_to_char(vk, shift=True, hkl=hkl, caps_lock=caps_lock)
            if normal:
                char_map[vk] = (normal, shifted or normal)

        return char_map

    def has_layout_changed(self) -> bool:
        """Check if the keyboard layout has changed since last check."""
        current = self.get_current_layout()
        if current != self._cached_layout:
            self._cached_layout = current
            return True
        return False
