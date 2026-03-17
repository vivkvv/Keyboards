"""Abstract base class for keyboard input backends."""

from abc import abstractmethod
from PySide6.QtCore import QObject, Signal


class InputBackend(QObject):
    """
    Abstract base class for keyboard input backends.

    Emits signals when keys are pressed/released.
    Allows future extension to HID, Raw Input, etc.
    """

    # Signals
    key_pressed = Signal(int, int)  # (scancode, vk_code)
    key_released = Signal(int, int)  # (scancode, vk_code)
    error_occurred = Signal(str)  # Error message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    @abstractmethod
    def start(self) -> bool:
        """Start listening for key events. Returns success."""
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """Stop listening for key events."""
        raise NotImplementedError

    @abstractmethod
    def is_running(self) -> bool:
        """Check if backend is currently active."""
        raise NotImplementedError

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Human-readable backend name for debug panel."""
        raise NotImplementedError
