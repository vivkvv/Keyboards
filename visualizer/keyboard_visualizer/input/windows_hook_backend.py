"""Windows low-level keyboard hook implementation."""

import ctypes
from ctypes import wintypes, CFUNCTYPE, POINTER, Structure, c_int, c_void_p
import threading
import time

from PySide6.QtCore import QObject

from .input_backend import InputBackend


# Windows types
LRESULT = ctypes.c_longlong
ULONG_PTR = ctypes.c_ulonglong


class KBDLLHOOKSTRUCT(Structure):
    """Windows KBDLLHOOKSTRUCT for low-level keyboard hook."""

    _fields_ = [
        ("vkCode", wintypes.DWORD),  # Virtual key code
        ("scanCode", wintypes.DWORD),  # Hardware scan code
        ("flags", wintypes.DWORD),  # Key flags (extended, injected, etc.)
        ("time", wintypes.DWORD),  # Timestamp
        ("dwExtraInfo", ULONG_PTR),  # Extra info
    ]


# Hook callback type
HOOKPROC = CFUNCTYPE(LRESULT, c_int, wintypes.WPARAM, POINTER(KBDLLHOOKSTRUCT))

# Windows API functions
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

SetWindowsHookExW = user32.SetWindowsHookExW
SetWindowsHookExW.argtypes = [c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
SetWindowsHookExW.restype = wintypes.HHOOK

UnhookWindowsHookEx = user32.UnhookWindowsHookEx
UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
UnhookWindowsHookEx.restype = wintypes.BOOL

CallNextHookEx = user32.CallNextHookEx
CallNextHookEx.argtypes = [wintypes.HHOOK, c_int, wintypes.WPARAM, c_void_p]
CallNextHookEx.restype = LRESULT

GetMessageW = user32.GetMessageW
GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
GetMessageW.restype = wintypes.BOOL

PostThreadMessageW = user32.PostThreadMessageW
PostThreadMessageW.argtypes = [
    wintypes.DWORD,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
PostThreadMessageW.restype = wintypes.BOOL

GetCurrentThreadId = kernel32.GetCurrentThreadId
GetCurrentThreadId.argtypes = []
GetCurrentThreadId.restype = wintypes.DWORD


class WindowsHookBackend(InputBackend):
    """
    Windows low-level keyboard hook implementation.

    Uses WH_KEYBOARD_LL to capture all keyboard events system-wide.
    Runs message pump in separate thread to avoid blocking Qt event loop.
    """

    # Windows API constants
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_SYSKEYDOWN = 0x0104
    WM_SYSKEYUP = 0x0105
    WM_QUIT = 0x0012

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hook_handle: wintypes.HHOOK | None = None
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._running = False

        # Must keep reference to callback to prevent garbage collection
        self._hook_proc = HOOKPROC(self._low_level_handler)

    @property
    def backend_name(self) -> str:
        return "Windows Low-Level Hook"

    def is_running(self) -> bool:
        return self._running

    def start(self) -> bool:
        """Install keyboard hook in background thread."""
        if self._running:
            return True

        self._running = True
        self._thread = threading.Thread(target=self._message_loop, daemon=True)
        self._thread.start()

        # Wait briefly for hook to be installed
        time.sleep(0.1)

        return self._hook_handle is not None

    def stop(self) -> None:
        """Uninstall hook and stop message pump thread."""
        if not self._running:
            return

        self._running = False

        # Post quit message to thread's message queue
        if self._thread_id:
            PostThreadMessageW(self._thread_id, self.WM_QUIT, 0, 0)

        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _message_loop(self) -> None:
        """Run message pump in background thread."""
        self._thread_id = GetCurrentThreadId()

        # Install hook
        self._hook_handle = SetWindowsHookExW(
            self.WH_KEYBOARD_LL,
            self._hook_proc,
            None,  # No module handle needed for LL hooks
            0,  # Thread ID 0 = all threads
        )

        if not self._hook_handle:
            self.error_occurred.emit("Failed to install keyboard hook")
            return

        # Message pump
        msg = wintypes.MSG()
        while self._running:
            result = GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result <= 0:
                break

        # Cleanup
        if self._hook_handle:
            UnhookWindowsHookEx(self._hook_handle)
            self._hook_handle = None

    def _low_level_handler(
        self,
        nCode: int,
        wParam: wintypes.WPARAM,
        lParam: POINTER(KBDLLHOOKSTRUCT),
    ) -> LRESULT:
        """Low-level keyboard hook callback."""
        if nCode >= 0 and lParam:
            kb = lParam.contents
            scancode = kb.scanCode
            vk_code = kb.vkCode

            # Emit appropriate signal based on event type
            if wParam in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
                self.key_pressed.emit(scancode, vk_code)
            elif wParam in (self.WM_KEYUP, self.WM_SYSKEYUP):
                self.key_released.emit(scancode, vk_code)

        return CallNextHookEx(None, nCode, wParam, ctypes.cast(lParam, c_void_p))
