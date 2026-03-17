from .main_window import MainWindow
from .keyboard_widget import KeyboardWidget
from .key_item import KeyItem
from .debug_panel import DebugPanel
from .dialogs import CustomLayerViewDialog, SettingsDialog
from .hand_overlay import HandGraphics, FingerLine, Finger, FINGER_COLORS, get_finger_color
from .tutor_overlay import TutorOverlayWindow
from .keyboard_overlay import KeyboardOverlayWindow
from .typing_lesson import TypingTextWidget, TypingStatsWidget, ErrorMode

__all__ = [
    "MainWindow",
    "KeyboardWidget",
    "KeyItem",
    "DebugPanel",
    "CustomLayerViewDialog",
    "SettingsDialog",
    "HandGraphics",
    "FingerLine",
    "Finger",
    "FINGER_COLORS",
    "get_finger_color",
    "TutorOverlayWindow",
    "KeyboardOverlayWindow",
    "TypingTextWidget",
    "TypingStatsWidget",
    "ErrorMode",
]
