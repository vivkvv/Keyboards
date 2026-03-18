"""Main application window."""

from pathlib import Path
import re

from PySide6.QtWidgets import (
    QDialog,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QToolBar,
    QToolButton,
    QComboBox,
    QCheckBox,
    QLabel,
    QFileDialog,
    QMessageBox,
    QSplitter,
    QMenu,
    QStyle,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap

from ..utils import (
    Config,
    LayerViewConfig,
    SoundPlayer,
    TutorStatsDatabase,
    TutorUser,
    load_tutor_hand_schemes,
    load_tutor_key_scheme_assignments,
)

from ..models import Keymap
from ..models.layout import Layout
from ..parsers import KeymapParser, LayoutParser
from ..input import WindowsHookBackend, ScancodeMapper, KeyboardLayoutDetector, HID_AVAILABLE
if HID_AVAILABLE:
    from ..input import (
        KeyboardHID,
        VendorKeyEventType,
        get_keyboard_hid,
    )
from .keyboard_widget import KeyboardWidget
from .debug_panel import DebugPanel
from .dialogs import CustomLayerViewDialog, SettingsDialog, TutorUserDialog
from .hand_overlay import Finger
from .tutor_stats_window import TutorStatsWindow
from .tutor_overlay import TutorOverlayWindow
from .keyboard_overlay import KeyboardOverlayWindow


BASTARDKB_LAYER_NAMES = {
    0: "Base",
    1: "Function",
    2: "Navigation",
    3: "Media",
    4: "Pointer",
    5: "Numeral",
    6: "Symbols",
}


class MainWindow(QMainWindow):
    """
    Main application window.

    Layout:
    - Toolbar with load buttons, layer selector, hook toggle
    - Central keyboard visualization
    - Bottom debug panel (collapsible)
    """

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("QMK Keyboard Visualizer")
        self.setMinimumSize(800, 600)

        # Data
        self._keymap: Keymap | None = None
        self._layout: Layout | None = None
        self._scancode_mapper: ScancodeMapper | None = None

        # Input backend
        self._input_backend = WindowsHookBackend(self)

        # Track currently pressed keys (by vk_code) to handle auto-repeat
        self._pressed_keys: set[int] = set()
        self._pressed_key_indices: set[int] = set()
        self._pressed_physical_key_indices: set[int] = set()
        self._pressed_hid_key_indices: set[int] = set()

        # Keyboard layout detector
        self._layout_detector = KeyboardLayoutDetector()
        self._os_layout_mode = False
        self._current_layout_hkl: int | None = None
        self._tracked_layout_hwnd: int | None = None
        self._caps_lock_on = self._layout_detector.get_caps_lock_state()
        self._sound_player = SoundPlayer()
        self._stats_db = TutorStatsDatabase()
        self._language_sound_bindings: dict[str, str] = {}
        self._tutor_hand_schemes = load_tutor_hand_schemes()
        self._tutor_key_scheme_assignments = load_tutor_key_scheme_assignments()
        self._tutor_user: TutorUser | None = None
        self._tutor_course_id = "en"
        self._invalid_recent_keymaps: set[str] = set()
        self._invalid_recent_layouts: set[str] = set()
        self._warning_recent_keymaps: set[str] = set()
        self._warning_recent_layouts: set[str] = set()

        # Tutor overlay window (created on demand)
        self._tutor_overlay: TutorOverlayWindow | None = None
        self._keyboard_overlay: KeyboardOverlayWindow | None = None
        self._tutor_stats_window: TutorStatsWindow | None = None

        # HID controller for RGB control
        self._hid_controller: "KeyboardHID | None" = None
        self._hid_click_enabled = False
        self._last_polled_layer: int | None = None
        self._last_hid_key_event_counter: int | None = None

        # Parsers
        self._keymap_parser = KeymapParser()
        self._layout_parser = LayoutParser()

        # Configuration
        self._config = Config()
        self._tutor_course_id = self._config.get_last_tutor_course_id()
        self._invalid_recent_keymaps = self._config.get_invalid_recent_keymaps()
        self._invalid_recent_layouts = self._config.get_invalid_recent_layouts()
        self._warning_recent_keymaps = self._config.get_warning_recent_keymaps()
        self._warning_recent_layouts = self._config.get_warning_recent_layouts()

        # Layer views (built-in + custom)
        self._layer_views: list[LayerViewConfig] = []

        # Timer for checking layout changes
        self._layout_check_timer = QTimer(self)
        self._layout_check_timer.setInterval(500)  # Check every 500ms
        self._layout_check_timer.timeout.connect(self._check_layout_change)

        # Timer for polling the actual active layer from the keyboard
        self._hid_layer_poll_timer = QTimer(self)
        self._hid_layer_poll_timer.setInterval(30)
        self._hid_layer_poll_timer.timeout.connect(self._poll_hid_layer)

        # Timer for polling firmware-level key events used for HID contours.
        self._hid_key_event_poll_timer = QTimer(self)
        self._hid_key_event_poll_timer.setInterval(20)
        self._hid_key_event_poll_timer.timeout.connect(self._poll_hid_key_event)

        # UI setup
        self._setup_ui()
        self._setup_connections()

        # Auto-load last session
        self._load_last_session()
        self._reload_language_sound_bindings()
        self._refresh_layout_tracking_timer()

    def _setup_ui(self) -> None:
        """Setup the UI components."""
        self._setup_menu_bar()

        # Central widget with splitter
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(splitter)

        # Keyboard widget
        self._keyboard_widget = KeyboardWidget()
        self._keyboard_widget.set_tutor_scheme_data(
            self._tutor_hand_schemes,
            self._tutor_key_scheme_assignments,
        )
        splitter.addWidget(self._keyboard_widget)

        # Debug panel
        self._debug_panel = DebugPanel()
        self._keyboard_widget.set_debug_log_callback(self._debug_panel.log)
        splitter.addWidget(self._debug_panel)

        # Set splitter sizes (keyboard takes more space)
        splitter.setSizes([400, 150])

        # Toolbar
        self._setup_toolbar()

        # Log startup
        self._debug_panel.log("Application started")
        self._debug_panel.log(f"Input backend: {self._input_backend.backend_name}")

    def _icon(self, standard_icon: QStyle.StandardPixmap) -> QIcon:
        """Return a standard Qt icon from the current style."""
        return self.style().standardIcon(standard_icon)

    def _make_toolbar_button(
        self,
        text: str,
        icon: QStyle.StandardPixmap,
        *,
        checkable: bool = False,
        tooltip: str = "",
        compact: bool = False,
    ) -> QToolButton:
        """Create a uniform toolbar button."""
        button = QToolButton(self)
        button.setText(text)
        button.setIcon(self._icon(icon))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setCheckable(checkable)
        if compact:
            button.setProperty("compactToggle", True)
        if tooltip:
            button.setToolTip(tooltip)
        return button

    def _setup_menu_bar(self) -> None:
        """Build the main menu bar."""
        menu_bar = self.menuBar()
        self._file_menu = menu_bar.addMenu("&File")
        self._file_keymap_menu = self._file_menu.addMenu(self._icon(QStyle.StandardPixmap.SP_DialogOpenButton), "Keymap")
        self._file_layout_menu = self._file_menu.addMenu(self._icon(QStyle.StandardPixmap.SP_DialogOpenButton), "Geometry")
        self._file_menu.addSeparator()
        self._settings_action = self._file_menu.addAction(
            self._icon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
            "Settings...",
        )
        self._file_menu.addSeparator()
        self._exit_action = self._file_menu.addAction(
            self._icon(QStyle.StandardPixmap.SP_DialogCloseButton),
            "Exit",
        )

        self._view_menu = menu_bar.addMenu("&View")
        self._layer_view_menu = self._view_menu.addMenu("Layer")
        self._view_menu.addSeparator()
        self._language_action = self._view_menu.addAction("Track Layout")
        self._language_action.setCheckable(True)
        self._always_on_top_action = self._view_menu.addAction("Pin on Top")
        self._always_on_top_action.setCheckable(True)
        self._overlay_action = self._view_menu.addAction(
            self._icon(QStyle.StandardPixmap.SP_ComputerIcon),
            "Overlay",
        )

        self._tools_menu = menu_bar.addMenu("&Tools")
        self._hook_action = self._tools_menu.addAction(
            self._icon(QStyle.StandardPixmap.SP_MediaPlay),
            "Hook",
        )
        self._hook_action.setCheckable(True)
        self._tools_menu.addSeparator()
        self._add_view_action = self._tools_menu.addAction(
            self._icon(QStyle.StandardPixmap.SP_FileDialogNewFolder),
            "Add Layer View...",
        )
        self._edit_view_action = self._tools_menu.addAction(
            self._icon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
            "Edit Layer View...",
        )

        self._tutor_menu = menu_bar.addMenu("&Tutor")
        self._tutor_action = self._tutor_menu.addAction(
            self._icon(QStyle.StandardPixmap.SP_ArrowForward),
            "Tutor",
        )
        self._tutor_stats_action = self._tutor_menu.addAction(
            self._icon(QStyle.StandardPixmap.SP_FileDialogInfoView),
            "Statistics",
        )

        if HID_AVAILABLE:
            self._tools_menu.addSeparator()
            self._hid_connect_action = self._tools_menu.addAction("HID")
            self._hid_connect_action.setCheckable(True)
            self._hid_click_action = self._tools_menu.addAction("RGB")
            self._hid_click_action.setCheckable(True)
            self._hid_click_action.setEnabled(False)
        else:
            self._hid_connect_action = None
            self._hid_click_action = None

        self._help_menu = menu_bar.addMenu("&Help")
        self._about_action = self._help_menu.addAction(
            self._icon(QStyle.StandardPixmap.SP_FileDialogInfoView),
            "About",
        )

    def _setup_toolbar(self) -> None:
        """Setup the main toolbars in two rows."""
        toolbar_top = QToolBar("Main Top")
        toolbar_top.setObjectName("main_toolbar_top")
        toolbar_top.setMovable(False)
        self.addToolBar(toolbar_top)

        self._keymap_menu = QMenu(self)
        self._load_keymap_btn = self._make_toolbar_button(
            "Keymap",
            QStyle.StandardPixmap.SP_DialogOpenButton,
            tooltip="Load VIA keymap JSON file",
        )
        self._load_keymap_btn.setMenu(self._keymap_menu)
        self._load_keymap_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar_top.addWidget(self._load_keymap_btn)

        self._layout_menu = QMenu(self)
        self._load_layout_btn = self._make_toolbar_button(
            "Geometry",
            QStyle.StandardPixmap.SP_DialogOpenButton,
            tooltip="Load keyboard geometry JSON file",
        )
        self._load_layout_btn.setMenu(self._layout_menu)
        self._load_layout_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar_top.addWidget(self._load_layout_btn)

        toolbar_top.addSeparator()

        toolbar_top.addWidget(QLabel("Layer:"))
        self._layer_combo = QComboBox()
        self._layer_combo.setMinimumWidth(140)
        self._layer_combo.setEnabled(False)
        toolbar_top.addWidget(self._layer_combo)

        self._add_view_btn = self._make_toolbar_button(
            "+",
            QStyle.StandardPixmap.SP_FileDialogNewFolder,
            tooltip="Add custom layer view",
        )
        self._add_view_btn.setEnabled(False)
        toolbar_top.addWidget(self._add_view_btn)

        self._edit_view_btn = self._make_toolbar_button(
            "Edit",
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
            tooltip="Edit or delete custom layer view",
        )
        self._edit_view_btn.setEnabled(False)
        toolbar_top.addWidget(self._edit_view_btn)

        toolbar_top.addSeparator()

        self._always_on_top_cb = self._make_toolbar_button(
            "Pin",
            QStyle.StandardPixmap.SP_TitleBarShadeButton,
            checkable=True,
            compact=True,
            tooltip="Keep the window above other windows",
        )
        toolbar_top.addWidget(self._always_on_top_cb)

        self.addToolBarBreak()

        toolbar_bottom = QToolBar("Main Bottom")
        toolbar_bottom.setObjectName("main_toolbar_bottom")
        toolbar_bottom.setMovable(False)
        self.addToolBar(toolbar_bottom)

        self._hook_btn = self._make_toolbar_button(
            "Hook",
            QStyle.StandardPixmap.SP_MediaPlay,
            checkable=True,
            tooltip="Start or stop keyboard input capture",
        )
        toolbar_bottom.addWidget(self._hook_btn)

        toolbar_bottom.addSeparator()

        self._os_layout_cb = QCheckBox("Track Layout")
        self._os_layout_cb.setToolTip("Track changes of the current Windows input language")
        toolbar_bottom.addWidget(self._os_layout_cb)

        self._layout_label = QLabel("")
        self._layout_label.setMinimumWidth(64)
        toolbar_bottom.addWidget(self._layout_label)

        toolbar_bottom.addSeparator()

        self._keyboard_overlay_btn = self._make_toolbar_button(
            "",
            QStyle.StandardPixmap.SP_ComputerIcon,
            tooltip="Open transparent keyboard overlay",
        )
        self._keyboard_overlay_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        toolbar_bottom.addWidget(self._keyboard_overlay_btn)

        self._tutor_overlay_btn = self._make_toolbar_button(
            "",
            QStyle.StandardPixmap.SP_ArrowForward,
            tooltip="Open typing lesson window",
        )
        self._tutor_overlay_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        toolbar_bottom.addWidget(self._tutor_overlay_btn)

        self._tutor_stats_btn = self._make_toolbar_button(
            "",
            QStyle.StandardPixmap.SP_FileDialogInfoView,
            tooltip="Open tutor statistics",
        )
        self._tutor_stats_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        toolbar_bottom.addWidget(self._tutor_stats_btn)

        self._settings_btn = self._make_toolbar_button(
            "",
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
            tooltip="Open settings",
        )
        self._settings_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        toolbar_bottom.addWidget(self._settings_btn)

        if HID_AVAILABLE:
            toolbar_bottom.addSeparator()
            self._hid_connect_btn = self._make_toolbar_button(
                "HID",
                QStyle.StandardPixmap.SP_DriveNetIcon,
                checkable=True,
                tooltip="Connect to keyboard via HID for RGB control",
            )
            toolbar_bottom.addWidget(self._hid_connect_btn)

            self._hid_click_cb = self._make_toolbar_button(
                "RGB",
                QStyle.StandardPixmap.SP_DialogApplyButton,
                checkable=True,
                compact=True,
                tooltip="Click keys to highlight them on physical keyboard",
            )
            self._hid_click_cb.setEnabled(False)
            toolbar_bottom.addWidget(self._hid_click_cb)

        self._update_recent_menus()

    def _setup_connections(self) -> None:
        """Setup signal/slot connections."""
        # Toolbar buttons
        self._hook_btn.toggled.connect(self._toggle_hook)
        self._always_on_top_cb.toggled.connect(self._toggle_always_on_top)
        self._os_layout_cb.toggled.connect(self._toggle_os_layout)
        # Combo boxes
        self._layer_combo.currentIndexChanged.connect(self._on_layer_view_changed)

        # Layer view buttons
        self._add_view_btn.clicked.connect(self._add_custom_view)
        self._edit_view_btn.clicked.connect(self._edit_custom_view)
        self._settings_btn.clicked.connect(self._open_settings)

        self._keyboard_overlay_btn.clicked.connect(self._open_keyboard_overlay)
        self._tutor_overlay_btn.clicked.connect(self._open_tutor_overlay)
        self._tutor_stats_btn.clicked.connect(self._open_tutor_stats)

        # Input backend signals
        self._input_backend.key_pressed.connect(self._on_key_pressed)
        self._input_backend.key_released.connect(self._on_key_released)
        self._input_backend.error_occurred.connect(self._on_input_error)

        # HID controls (only if available)
        if HID_AVAILABLE:
            self._hid_connect_btn.toggled.connect(self._toggle_hid_connection)
            self._hid_click_cb.toggled.connect(self._toggle_hid_click)

        # Menu actions
        self._settings_action.triggered.connect(self._open_settings)
        self._exit_action.triggered.connect(self.close)
        self._language_action.setCheckable(True)
        self._language_action.toggled.connect(self._os_layout_cb.setChecked)
        self._os_layout_cb.toggled.connect(self._language_action.setChecked)
        self._always_on_top_action.toggled.connect(self._always_on_top_cb.setChecked)
        self._always_on_top_cb.toggled.connect(self._always_on_top_action.setChecked)
        self._hook_action.toggled.connect(self._hook_btn.setChecked)
        self._hook_btn.toggled.connect(self._hook_action.setChecked)
        self._add_view_action.triggered.connect(self._add_custom_view)
        self._edit_view_action.triggered.connect(self._edit_custom_view)
        self._overlay_action.triggered.connect(self._open_keyboard_overlay)
        self._tutor_action.triggered.connect(self._open_tutor_overlay)
        self._tutor_stats_action.triggered.connect(self._open_tutor_stats)
        self._about_action.triggered.connect(self._open_about_dialog)
        if HID_AVAILABLE and self._hid_connect_action is not None and self._hid_click_action is not None:
            self._hid_connect_action.toggled.connect(self._hid_connect_btn.setChecked)
            self._hid_connect_btn.toggled.connect(self._hid_connect_action.setChecked)
            self._hid_click_action.toggled.connect(self._hid_click_cb.setChecked)
            self._hid_click_cb.toggled.connect(self._hid_click_action.setChecked)

    def _update_hid_button_state(self, connected: bool) -> None:
        """Update HID connect button text and styling."""
        if not HID_AVAILABLE:
            return
        if connected:
            self._hid_connect_btn.setText("HID Connected")
            self._hid_connect_btn.setIcon(self._icon(QStyle.StandardPixmap.SP_DialogApplyButton))
            self._hid_connect_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self._hid_connect_btn.setStyleSheet(
                "QToolButton { background-color: #2e7d32; color: white; font-weight: 600; border-color: #2e7d32; }"
            )
        else:
            self._hid_connect_btn.setText("HID")
            self._hid_connect_btn.setIcon(self._icon(QStyle.StandardPixmap.SP_DriveNetIcon))
            self._hid_connect_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self._hid_connect_btn.setStyleSheet("")

    def _make_status_icon(self, color: str) -> QIcon:
        """Create a small colored dot icon for menus."""
        pixmap = QPixmap(10, 10)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(1, 1, 8, 8)
        painter.end()
        return QIcon(pixmap)

    def _add_recent_file_action(
        self,
        menu: QMenu,
        path: str,
        current_path: str | None,
        loader,
        invalid_paths: set[str],
        warning_paths: set[str],
    ) -> None:
        """Add one recent file action with clear state markers."""
        file_path = Path(path)
        exists = file_path.exists()
        name = file_path.name

        if path in invalid_paths:
            name = f"{name} [invalid]"
        elif path in warning_paths:
            name = f"{name} [warning]"
        elif not exists:
            name = f"{name} [missing]"

        action = menu.addAction(name)
        if path in invalid_paths:
            action.setIcon(self._make_status_icon("#f44336"))
        elif path in warning_paths:
            action.setIcon(self._make_status_icon("#42a5f5"))
        elif not exists:
            action.setIcon(self._make_status_icon("#f44336"))
        elif path == current_path:
            action.setIcon(self._make_status_icon("#4caf50"))

        if path == current_path:
            action.setCheckable(True)
            action.setChecked(True)
            font = action.font()
            font.setBold(True)
            action.setFont(font)

        action.triggered.connect(lambda checked=False, p=path: loader(p))

    def _load_keymap_file(self, file_path: str) -> None:
        """Load a keymap JSON file from path."""
        if not Path(file_path).exists():
            self._debug_panel.log_error(f"Keymap file not found: {file_path}")
            QMessageBox.critical(self, "Error", f"Keymap file not found:\n{file_path}")
            self._update_recent_menus()
            return

        try:
            keymap = self._keymap_parser.parse_file(file_path)
            if keymap.layer_count <= 0 or keymap.key_count <= 0:
                raise ValueError(
                    f"File does not look like a valid keymap: layers={keymap.layer_count}, keys={keymap.key_count}"
                )
            self._keymap = keymap
            self._invalid_recent_keymaps.discard(file_path)
            self._config.set_invalid_recent_keymaps(self._invalid_recent_keymaps)
            self._warning_recent_keymaps.discard(file_path)
            self._config.set_warning_recent_keymaps(self._warning_recent_keymaps)
            self._debug_panel.log_success(
                f"Loaded keymap: {self._keymap.name} "
                f"({self._keymap.layer_count} layers, {self._keymap.key_count} keys)"
            )

            # Rebuild layer views
            self._rebuild_layer_views()

            # Apply colors from config
            self._apply_colors()

            # Apply to keyboard widget
            self._keyboard_widget.set_keymap(self._keymap)

            # Rebuild scancode mapper
            self._rebuild_scancode_mapper()

            # Validate against layout if loaded
            has_warning = self._validate_data()
            if has_warning:
                self._warning_recent_keymaps.add(file_path)
            else:
                self._warning_recent_keymaps.discard(file_path)
            self._config.set_warning_recent_keymaps(self._warning_recent_keymaps)

            # Save to config
            self._config.add_recent_keymap(file_path)
            self._config.set_last_keymap(file_path)
            self._update_recent_menus()

        except Exception as e:
            self._invalid_recent_keymaps.add(file_path)
            self._config.set_invalid_recent_keymaps(self._invalid_recent_keymaps)
            self._debug_panel.log_error(f"Failed to load keymap: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load keymap:\n{e}")
            self._update_recent_menus()

    def _load_layout_file(self, file_path: str) -> None:
        """Load a layout JSON file from path."""
        if not Path(file_path).exists():
            self._debug_panel.log_error(f"Geometry file not found: {file_path}")
            QMessageBox.critical(self, "Error", f"Geometry file not found:\n{file_path}")
            self._update_recent_menus()
            return

        try:
            layout = self._layout_parser.parse_file(file_path)
            if layout.key_count <= 0:
                raise ValueError(
                    f"File does not look like a valid geometry: keys={layout.key_count}"
                )
            self._layout = layout
            self._invalid_recent_layouts.discard(file_path)
            self._config.set_invalid_recent_layouts(self._invalid_recent_layouts)
            self._warning_recent_layouts.discard(file_path)
            self._config.set_warning_recent_layouts(self._warning_recent_layouts)
            self._debug_panel.log_success(
                f"Loaded geometry: {self._layout.name} "
                f"({self._layout.key_count} keys)"
            )
            self._keyboard_widget.set_layout(self._layout)

            # Validate against keymap if loaded
            has_warning = self._validate_data()
            if has_warning:
                self._warning_recent_layouts.add(file_path)
            else:
                self._warning_recent_layouts.discard(file_path)
            self._config.set_warning_recent_layouts(self._warning_recent_layouts)

            # Save to config
            self._config.add_recent_layout(file_path)
            self._config.set_last_layout(file_path)
            self._update_recent_menus()

        except Exception as e:
            self._invalid_recent_layouts.add(file_path)
            self._config.set_invalid_recent_layouts(self._invalid_recent_layouts)
            self._debug_panel.log_error(f"Failed to load layout: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load layout:\n{e}")
            self._update_recent_menus()

    def _on_layer_view_changed(self, index: int) -> None:
        """Handle layer view selection change."""
        if index < 0 or index >= len(self._layer_views):
            return

        view = self._layer_views[index]
        self._update_layer_combo_current_style()
        self._refresh_layer_view_menu()

        # Update edit button state (only enabled for custom views)
        self._edit_view_btn.setEnabled(not view.is_builtin)
        self._edit_view_action.setEnabled(not view.is_builtin)

        # Apply view to keyboard widget
        if len(view.layers) == 1:
            self._keyboard_widget.set_layer(view.layers[0])
            self._debug_panel.log(f"Switched to {view.name}")
        else:
            self._keyboard_widget.set_layers(view.layers)
            layers_str = ", ".join(str(l) for l in view.layers)
            self._debug_panel.log(f"Switched to {view.name} (layers: {layers_str})")

    def _toggle_hook(self, checked: bool) -> None:
        """Toggle the keyboard hook."""
        if checked:
            if self._input_backend.start():
                self._hook_btn.setText("Stop Hook")
                self._hook_btn.setIcon(self._icon(QStyle.StandardPixmap.SP_MediaStop))
                self._hook_action.setText("Stop Hook")
                self._hook_action.setIcon(self._icon(QStyle.StandardPixmap.SP_MediaStop))
                self._debug_panel.log_success("Keyboard hook started")
            else:
                self._hook_btn.setChecked(False)
                self._debug_panel.log_error("Failed to start keyboard hook")
        else:
            self._input_backend.stop()
            self._hook_btn.setText("Start Hook")
            self._hook_btn.setIcon(self._icon(QStyle.StandardPixmap.SP_MediaPlay))
            self._hook_action.setText("Start Hook")
            self._hook_action.setIcon(self._icon(QStyle.StandardPixmap.SP_MediaPlay))
            self._keyboard_widget.clear_all_highlights()
            self._pressed_keys.clear()
            self._debug_panel.log("Keyboard hook stopped")

    def _toggle_always_on_top(self, checked: bool) -> None:
        """Toggle always on top window flag."""
        was_maximized = self.isMaximized()
        geometry = self.geometry()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        if was_maximized:
            self.showMaximized()
        else:
            self.show()
            self.setGeometry(geometry)
        self.raise_()
        self.activateWindow()

    def _open_keyboard_overlay(self) -> None:
        """Open a transparent keyboard-only overlay."""
        if self._keyboard_overlay is None or not self._keyboard_overlay.isVisible():
            self._keyboard_overlay = KeyboardOverlayWindow()
            if self._layout:
                self._keyboard_overlay.set_layout(self._layout)
            if self._keymap:
                self._keyboard_overlay.set_keymap(self._keymap)
                self._keyboard_overlay.set_layer(self._get_displayed_layer())
            self._keyboard_overlay.set_keyboard_view_state(
                self._keyboard_widget.size(),
                self._keyboard_widget.transform(),
            )
            self._keyboard_overlay.set_show_hold_labels(self._config.get_tutor_show_hold_labels())
            self._current_layout_hkl = self._layout_detector.get_current_layout()
            self._keyboard_overlay.set_os_layout_mode(
                self._os_layout_mode,
                self._layout_detector if self._os_layout_mode else None,
                self._current_layout_hkl if self._os_layout_mode else None,
            )
            self._keyboard_overlay.set_caps_lock_mode(self._caps_lock_on)
            self._apply_colors()
            if not self._layout_check_timer.isActive():
                self._layout_check_timer.start()
            self._keyboard_overlay.closed.connect(self._on_keyboard_overlay_closed)
            self._keyboard_overlay.show()
            self._debug_panel.log("Keyboard overlay opened")
            self.hide()
        else:
            self._keyboard_overlay.raise_()
            self._keyboard_overlay.activateWindow()

    def _open_tutor_overlay(self) -> None:
        """Open the typing tutor overlay."""
        if not self._ensure_tutor_user_selected():
            return
        if self._tutor_overlay is None or not self._tutor_overlay.isVisible():
            # Create new tutor overlay
            self._tutor_overlay = TutorOverlayWindow()

            # Copy current layout and keymap
            if self._layout:
                self._tutor_overlay.set_layout(self._layout)
            if self._keymap:
                self._tutor_overlay.set_keymap(self._keymap)
                self._tutor_overlay.set_layer(self._get_displayed_layer())

            self._tutor_overlay.set_keyboard_view_state(
                self._keyboard_widget.size(),
                self._keyboard_widget.transform(),
            )
            self._tutor_overlay.set_show_hold_labels(self._config.get_tutor_show_hold_labels())
            self._tutor_overlay.set_show_finger_movement_arrows(
                self._config.get_tutor_show_movement_arrows()
            )
            self._tutor_overlay.set_finger_palette(self._build_finger_palette())
            self._tutor_overlay.set_tutor_scheme_data(
                self._tutor_hand_schemes,
                self._tutor_key_scheme_assignments,
            )
            self._tutor_overlay.set_click_sounds(
                self._config.get_tutor_click_sounds_enabled(),
                self._config.get_tutor_correct_sound(),
                self._config.get_tutor_incorrect_sound(),
            )
            self._tutor_overlay.set_stats_context(self._stats_db, self._tutor_user)
            self._tutor_overlay.set_course(self._tutor_course_id)

            # Always enable OS layout mode for tutor (so keys show correct characters)
            self._current_layout_hkl = self._layout_detector.get_current_layout()
            self._tutor_overlay.set_os_layout_mode(
                True,
                self._layout_detector,
                self._current_layout_hkl
            )
            self._tutor_overlay.set_caps_lock_mode(self._caps_lock_on)

            # Start layout check timer to detect layout changes
            if not self._layout_check_timer.isActive():
                self._layout_check_timer.start()

            # Connect close signal
            self._tutor_overlay.closed.connect(self._on_tutor_overlay_closed)
            self._tutor_overlay.stats_requested.connect(self._open_tutor_stats)
            self._tutor_overlay.course_changed.connect(self._on_tutor_course_changed)

            self._tutor_overlay.show()
            user_name = self._tutor_user.name if self._tutor_user else "Unknown"
            self._debug_panel.log(f"Tutor overlay opened for user: {user_name}")

            # Hide main window
            self.hide()
        else:
            self._tutor_overlay.raise_()
            self._tutor_overlay.activateWindow()

    def _on_tutor_course_changed(self, course_id: str) -> None:
        """Persist the selected tutor course and sync related windows."""
        self._tutor_course_id = (course_id or 'en').strip().lower()
        self._config.set_last_tutor_course_id(self._tutor_course_id)
        if self._tutor_stats_window and self._tutor_stats_window.isVisible():
            self._tutor_stats_window.set_current_course(self._tutor_course_id)
        self._debug_panel.log(f"Tutor course selected: {self._tutor_course_id}")

    def _open_tutor_stats(self) -> None:
        """Open tutor statistics window."""
        stats_parent = None
        overlay_mode = bool(
            (self._tutor_overlay and self._tutor_overlay.isVisible())
            or bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        )
        if self._tutor_stats_window is None or not self._tutor_stats_window.isVisible():
            self._tutor_stats_window = TutorStatsWindow(
                self._stats_db,
                self._tutor_user,
                self._tutor_course_id,
                stats_parent,
            )
            self._tutor_stats_window.set_overlay_mode(overlay_mode)
            self._tutor_stats_window.set_current_course(self._tutor_course_id)
            self._tutor_stats_window.show()
            self._tutor_stats_window.raise_()
            self._tutor_stats_window.activateWindow()
            self._debug_panel.log("Tutor statistics opened")
        else:
            self._tutor_stats_window.setParent(stats_parent)
            self._tutor_stats_window.set_overlay_mode(overlay_mode)
            self._tutor_stats_window.set_current_course(self._tutor_course_id)
            self._tutor_stats_window.refresh()
            self._tutor_stats_window.show()
            self._tutor_stats_window.raise_()
            self._tutor_stats_window.activateWindow()

    def _open_about_dialog(self) -> None:
        """Show an About dialog with the keyboard photo."""
        dialog = QDialog(self)
        dialog.setWindowTitle("About QMK Keyboard Visualizer")
        dialog.setModal(True)
        dialog.resize(720, 420)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_path = Path(__file__).resolve().parents[1] / "resources" / "images" / "charybdis_nano_photo.jpg"
        pixmap = QPixmap(str(image_path))
        if not pixmap.isNull():
            image_label.setPixmap(
                pixmap.scaled(
                    dialog.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        layout.addWidget(image_label)

        overlay = QWidget(image_label)
        overlay.setGeometry(420, 18, 282, 210)
        overlay.setStyleSheet(
            "background-color: rgba(20, 20, 20, 155);"
            "border: 1px solid rgba(255, 255, 255, 35);"
            "border-radius: 10px;"
        )

        info_layout = QVBoxLayout(overlay)
        info_layout.setContentsMargins(18, 18, 18, 18)
        info_layout.setSpacing(10)

        title = QLabel("QMK Keyboard Visualizer")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        info_layout.addWidget(title)

        subtitle = QLabel(
            "Visualizer, tutor, HID integration and statistics for the Charybdis Nano."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #cfc8b8;")
        info_layout.addWidget(subtitle)

        details = QLabel(
            "This application renders bindings and geometry, tracks active layers, "
            "controls per-key RGB over HID, and provides a tutor with lesson progress "
            "and per-symbol statistics."
        )
        details.setWordWrap(True)
        details.setStyleSheet("color: #e8e3d8;")
        info_layout.addWidget(details)
        info_layout.addStretch(1)

        close_btn = self._make_toolbar_button(
            "OK",
            QStyle.StandardPixmap.SP_DialogApplyButton,
            tooltip="Close About dialog",
        )
        close_btn.clicked.connect(dialog.accept)
        info_layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    def _on_keyboard_overlay_closed(self) -> None:
        """Handle keyboard overlay closed."""
        self._keyboard_overlay = None
        self._debug_panel.log("Keyboard overlay closed")
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def _on_tutor_overlay_closed(self) -> None:
        """Handle tutor overlay closed."""
        self._tutor_overlay = None
        self._debug_panel.log("Tutor overlay closed")
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def _toggle_os_layout(self, checked: bool) -> None:
        """Enable or disable tracking of OS keyboard layout changes."""
        self._os_layout_mode = checked
        if checked:
            # Establish a baseline and immediately apply the current language.
            self._tracked_layout_hwnd = self._layout_detector.get_foreground_window_handle()
            self._current_layout_hkl = self._layout_detector.get_current_layout()
            self._caps_lock_on = self._layout_detector.get_caps_lock_state()
            self._update_layout_label()
            self._apply_os_layout_to_views()
            self._debug_panel.log(f"Language tracking enabled: {self._layout_detector.get_layout_name()}")
        else:
            self._layout_label.setText("")
            self._debug_panel.log("Language tracking disabled")

        self._refresh_layout_tracking_timer()

    def _check_layout_change(self) -> None:
        """Check if keyboard layout has changed."""
        if not self._should_track_layout_changes():
            return

        current_hwnd = self._layout_detector.get_foreground_window_handle()
        new_hkl = self._layout_detector.get_current_layout()
        first_observation = self._tracked_layout_hwnd is None
        window_changed = current_hwnd != self._tracked_layout_hwnd
        layout_changed = new_hkl != self._current_layout_hkl

        if first_observation or window_changed:
            self._tracked_layout_hwnd = current_hwnd
            self._current_layout_hkl = new_hkl
            self._debug_panel.log(f"Language baseline: {self._layout_detector.get_layout_name(self._current_layout_hkl)}")
            self._apply_os_layout_to_views()
        elif layout_changed:
            self._current_layout_hkl = new_hkl
            language_name = self._layout_detector.get_layout_name(self._current_layout_hkl)
            self._debug_panel.log(f"Language changed: {language_name}")
            self._apply_os_layout_to_views()
            self._play_language_change_sound(language_name)

        new_caps_lock = self._layout_detector.get_caps_lock_state()
        if new_caps_lock != self._caps_lock_on:
            self._caps_lock_on = new_caps_lock
            self._debug_panel.log(f"Caps Lock: {self._caps_lock_on}")

            if self._os_layout_mode:
                self._keyboard_widget.set_caps_lock_mode(self._caps_lock_on)

            if self._tutor_overlay and self._tutor_overlay.isVisible():
                self._tutor_overlay.set_caps_lock_mode(self._caps_lock_on)

    def _update_layout_label(self) -> None:
        """Update the layout indicator label."""
        name = self._layout_detector.get_layout_name()
        self._layout_label.setText(f"[{name}]")

    # VK codes for Shift keys
    VK_SHIFT = 0x10
    VK_LSHIFT = 0xA0
    VK_RSHIFT = 0xA1

    def _is_shift_key(self, vk_code: int) -> bool:
        """Check if the VK code is a Shift key."""
        return vk_code in (self.VK_SHIFT, self.VK_LSHIFT, self.VK_RSHIFT)

    def _update_shift_mode(self) -> None:
        """Update keyboard widget shift mode based on pressed keys."""
        shift_pressed = any(
            self._is_shift_key(vk) for vk in self._pressed_keys
        )
        self._debug_panel.log(f"Shift mode: {shift_pressed}")
        self._keyboard_widget.set_shift_mode(shift_pressed)
        self._caps_lock_on = self._layout_detector.get_caps_lock_state()
        if self._os_layout_mode:
            self._keyboard_widget.set_caps_lock_mode(self._caps_lock_on)
        if self._tutor_overlay and self._tutor_overlay.isVisible():
            self._tutor_overlay.set_caps_lock_mode(self._caps_lock_on)

    def _get_highlight_layer_for_press(self) -> int:
        """Return which layer should be highlighted for a new key press."""
        return self._last_polled_layer if self._last_polled_layer is not None else self._get_displayed_layer()

    def _get_current_view_layers(self) -> list[int]:
        """Return layers currently shown in the combobox-selected view."""
        index = self._layer_combo.currentIndex()
        if 0 <= index < len(self._layer_views):
            return list(self._layer_views[index].layers)
        return [0]

    def _keycode_matches_event(self, raw_keycode: str, qmk_code: str) -> bool:
        """Return whether a raw QMK keycode could have produced the pressed key event."""
        if not raw_keycode or not qmk_code:
            return False
        tokens = [token for token in re.split(r"[^A-Z0-9_]+", raw_keycode.upper()) if token]
        return qmk_code.upper() in tokens

    def _extract_layer_target(self, raw_keycode: str) -> int | None:
        """Extract target layer from common QMK layer-switch keycodes."""
        if not raw_keycode:
            return None
        match = re.match(r"^(?:LT|MO|LM|TG|TT|OSL|TO|DF)\((\d+)", raw_keycode.upper())
        if not match:
            return None
        return int(match.group(1))

    def _resolve_pressed_layer_for_key(self, key_index: int | None, qmk_code: str | None) -> int:
        """Resolve which layer cell should represent the currently pressed key."""
        view_layers = self._get_current_view_layers()
        fallback_layer = self._get_highlight_layer_for_press()
        if key_index is None or not self._keymap:
            return fallback_layer

        matching_layers: list[int] = []
        for layer_index in view_layers:
            if layer_index >= self._keymap.layer_count:
                continue
            layer = self._keymap.layers[layer_index]
            if key_index >= len(layer):
                continue
            raw_keycode = layer[key_index]
            if qmk_code and self._keycode_matches_event(raw_keycode, qmk_code):
                matching_layers.append(layer_index)

        if self._last_polled_layer is not None and self._last_polled_layer in matching_layers:
            return self._last_polled_layer
        if matching_layers:
            return matching_layers[0]
        if fallback_layer in view_layers:
            return fallback_layer
        return view_layers[0] if view_layers else 0

    def _resolve_pressed_layer_for_hid_key(self, key_index: int) -> int:
        """Resolve which layer cell should represent a HID-only key event."""
        view_layers = self._get_current_view_layers()
        fallback_layer = self._get_highlight_layer_for_press()
        if not self._keymap:
            return fallback_layer

        layer_switch_matches: list[int] = []
        concrete_matches: list[int] = []
        for layer_index in view_layers:
            if layer_index >= self._keymap.layer_count:
                continue
            layer = self._keymap.layers[layer_index]
            if key_index >= len(layer):
                continue
            raw_keycode = layer[key_index]
            if not raw_keycode or raw_keycode in ("KC_TRNS", "_______", "XXXXXXX", "KC_NO"):
                continue
            concrete_matches.append(layer_index)
            target_layer = self._extract_layer_target(raw_keycode)
            if target_layer is not None and target_layer == self._last_polled_layer:
                layer_switch_matches.append(layer_index)

        if layer_switch_matches:
            return layer_switch_matches[0]
        if fallback_layer in concrete_matches:
            return fallback_layer
        if concrete_matches:
            return concrete_matches[0]
        if fallback_layer in view_layers:
            return fallback_layer
        return view_layers[0] if view_layers else 0

    def _on_key_pressed(self, scancode: int, vk_code: int) -> None:
        """Handle key press event from input backend."""
        # Skip auto-repeat events
        if vk_code in self._pressed_keys:
            return

        self._pressed_keys.add(vk_code)

        # Update shift mode if Shift was pressed
        if self._is_shift_key(vk_code):
            self._update_shift_mode()

        qmk_code = None
        key_index = None
        physical_key_index = None
        is_hold = False

        if self._scancode_mapper:
            qmk_code = self._scancode_mapper.vk_to_qmk(vk_code)
            key_index = self._scancode_mapper.vk_to_key_index(vk_code)
            physical_key_index = self._scancode_mapper.scancode_to_key_index(scancode)
            is_hold = self._scancode_mapper.is_hold_action(vk_code)

        if key_index is not None:
            self._pressed_key_indices.add(key_index)
        if physical_key_index is not None:
            self._pressed_physical_key_indices.add(physical_key_index)

        if is_hold:
            self._debug_panel.log(
                f"HOLD PRESS: sc=0x{scancode:02X} vk=0x{vk_code:02X} qmk={qmk_code} "
                f"key_index={key_index} physical_key_index={physical_key_index}"
            )

        highlight_layer = self._resolve_pressed_layer_for_key(key_index, qmk_code)
        if key_index is not None:
            self._debug_panel.log(
                f"PRESS highlight resolve: key_index={key_index} qmk={qmk_code} "
                f"view_layers={self._get_current_view_layers()} last_polled={self._last_polled_layer} "
                f"displayed={self._get_displayed_layer()} resolved={highlight_layer}"
            )
        if key_index is not None:
            self._keyboard_widget.highlight_key(
                key_index,
                True,
                hold_mode=is_hold,
                active_layer=highlight_layer,
            )

        # Send character to tutor overlay if open
        if self._keyboard_overlay and self._keyboard_overlay.isVisible() and key_index is not None:
            self._keyboard_overlay.highlight_key(
                key_index,
                True,
                hold_mode=is_hold,
                active_layer=highlight_layer,
            )

        if self._tutor_overlay and self._tutor_overlay.isVisible():
            if self._handle_tutor_navigation_chord(physical_key_index):
                return
            char = self._vk_to_char(vk_code)
            if char and not self._is_tutor_navigation_chord_active():
                self._tutor_overlay.handle_keypress(char, key_index)

    def _is_tutor_navigation_chord_active(self) -> bool:
        """Return whether tutor lesson navigation mode is currently held."""
        if not self._scancode_mapper:
            return False
        space_index = self._scancode_mapper.qmk_to_index.get("KC_SPC")
        if space_index is None:
            return False
        active = (
            space_index in self._pressed_physical_key_indices
            or space_index in self._pressed_hid_key_indices
        )
        return active

    def _handle_tutor_navigation_chord(self, key_index: int | None) -> bool:
        """Handle tutor lesson navigation when Space is held."""
        if key_index is None or not self._tutor_overlay or not self._tutor_overlay.isVisible():
            return False
        if not self._is_tutor_navigation_chord_active():
            return False

        if key_index == 4:
            self._tutor_overlay.navigate_previous_lesson()
            return True
        if key_index == 9:
            self._tutor_overlay.restart_current_lesson()
            return True
        if key_index == 14:
            self._tutor_overlay.navigate_next_lesson()
            return True

        return key_index in self._pressed_key_indices

    def _handle_tutor_navigation_hid(self, key_index: int) -> bool:
        """Handle tutor lesson navigation from firmware-level key indices."""
        if not self._tutor_overlay or not self._tutor_overlay.isVisible():
            return False
        if not self._is_tutor_navigation_chord_active():
            return False

        if key_index == 4:
            self._tutor_overlay.navigate_previous_lesson()
            self._debug_panel.log("Tutor nav: previous lesson (HID idx=4)")
            return True
        if key_index == 9:
            self._tutor_overlay.restart_current_lesson()
            self._debug_panel.log("Tutor nav: restart lesson (HID idx=9)")
            return True
        if key_index == 14:
            self._tutor_overlay.navigate_next_lesson()
            self._debug_panel.log("Tutor nav: next lesson (HID idx=14)")
            return True

        return False

    def _vk_to_char(self, vk_code: int) -> str | None:
        """Convert VK code to character using current keyboard layout."""
        # Use layout detector if available
        if self._layout_detector:
            shift_pressed = any(self._is_shift_key(vk) for vk in self._pressed_keys)
            char = self._layout_detector.vk_to_char(
                vk_code,
                shift=shift_pressed,
                caps_lock=self._caps_lock_on,
            )
            if char:
                return char

        # Fallback: basic ASCII for letters
        if 0x41 <= vk_code <= 0x5A:  # A-Z
            shift_pressed = any(self._is_shift_key(vk) for vk in self._pressed_keys)
            char = chr(vk_code)
            uppercase = shift_pressed ^ self._caps_lock_on
            return char if uppercase else char.lower()

        # Space
        if vk_code == 0x20:
            return " "

        return None

    def _on_key_released(self, scancode: int, vk_code: int) -> None:
        """Handle key release event from input backend."""
        was_shift = self._is_shift_key(vk_code)

        self._pressed_keys.discard(vk_code)

        # Update shift mode if Shift was released
        if was_shift:
            self._update_shift_mode()

        qmk_code = None
        key_index = None
        physical_key_index = None

        if self._scancode_mapper:
            qmk_code = self._scancode_mapper.vk_to_qmk(vk_code)
            key_index = self._scancode_mapper.vk_to_key_index(vk_code)
            physical_key_index = self._scancode_mapper.scancode_to_key_index(scancode)

        if key_index is not None:
            self._pressed_key_indices.discard(key_index)
        if physical_key_index is not None:
            self._pressed_physical_key_indices.discard(physical_key_index)

        if qmk_code and qmk_code.startswith(("KC_L", "KC_R")):
            self._debug_panel.log(
                f"RELEASE: sc=0x{scancode:02X} vk=0x{vk_code:02X} qmk={qmk_code} key_index={key_index}"
            )

        if key_index is not None:
            self._keyboard_widget.highlight_key(key_index, False)
            if self._keyboard_overlay and self._keyboard_overlay.isVisible():
                self._keyboard_overlay.highlight_key(key_index, False)

    def _poll_hid_key_event(self) -> None:
        """Poll the latest firmware-level key event and reflect it as a contour."""
        if not self._hid_controller or not self._hid_controller.is_connected():
            return

        try:
            event = self._hid_controller.get_last_key_event()
        except Exception as exc:
            self._debug_panel.log_error(f"HID key event polling error: {exc}")
            return

        if event is None:
            return
        if self._last_hid_key_event_counter == event.counter:
            return

        self._last_hid_key_event_counter = event.counter
        if event.key_index == 0xFF:
            return

        if event.event_type == VendorKeyEventType.DOWN:
            self._pressed_hid_key_indices.add(event.key_index)
            highlight_layer = self._resolve_pressed_layer_for_hid_key(event.key_index)
            self._keyboard_widget.highlight_key(
                event.key_index,
                True,
                hold_mode=True,
                active_layer=highlight_layer,
            )
            self._keyboard_widget.set_hid_key_active(event.key_index, True)
            if self._keyboard_overlay and self._keyboard_overlay.isVisible():
                self._keyboard_overlay.highlight_key(
                    event.key_index,
                    True,
                    hold_mode=True,
                    active_layer=highlight_layer,
                )
                self._keyboard_overlay.set_hid_key_active(event.key_index, True)
            self._handle_tutor_navigation_hid(event.key_index)
            self._debug_panel.log(
                f"HID key down: counter={event.counter} idx={event.key_index} "
                f"pressed_hid={sorted(self._pressed_hid_key_indices)} "
                f"resolved_layer={highlight_layer}"
            )
        elif event.event_type == VendorKeyEventType.UP:
            self._pressed_hid_key_indices.discard(event.key_index)
            self._keyboard_widget.highlight_key(event.key_index, False)
            self._keyboard_widget.set_hid_key_active(event.key_index, False)
            if self._keyboard_overlay and self._keyboard_overlay.isVisible():
                self._keyboard_overlay.highlight_key(event.key_index, False)
                self._keyboard_overlay.set_hid_key_active(event.key_index, False)
            self._debug_panel.log(
                f"HID key up: counter={event.counter} idx={event.key_index} "
                f"pressed_hid={sorted(self._pressed_hid_key_indices)}"
            )

    def _on_input_error(self, message: str) -> None:
        """Handle error from input backend."""
        self._debug_panel.log_error(message)
        self._hook_btn.setChecked(False)
        self._hook_btn.setText("Start Hook")
        self._hook_btn.setIcon(self._icon(QStyle.StandardPixmap.SP_MediaPlay))
        self._hook_action.setText("Start Hook")
        self._hook_action.setIcon(self._icon(QStyle.StandardPixmap.SP_MediaPlay))

    def _rebuild_scancode_mapper(self) -> None:
        """Rebuild the scancode mapper with current keymap."""
        if self._keymap:
            self._scancode_mapper = ScancodeMapper(self._keymap, base_layer=0)
            self._debug_panel.log(
                f"Built scancode mapper with {len(self._scancode_mapper.qmk_to_index)} mappings"
            )

    def _validate_data(self) -> bool:
        """Validate that keymap and layout are compatible."""
        if not self._keymap or not self._layout:
            return False

        keymap_keys = self._keymap.key_count
        layout_keys = self._layout.key_count

        if keymap_keys != layout_keys:
            msg = (
                f"Warning: Key count mismatch!\n\n"
                f"Keymap has {keymap_keys} keys\n"
                f"Layout has {layout_keys} keys\n\n"
                f"Some keys may not display correctly."
            )
            self._debug_panel.log_error(f"Key count mismatch: keymap={keymap_keys}, layout={layout_keys}")
            QMessageBox.warning(self, "Warning", msg)
            return True
        else:
            self._debug_panel.log(f"Validation passed: {keymap_keys} keys match")
            return False

    def _update_recent_menus(self) -> None:
        """Update the recent files dropdown menus."""
        self._populate_recent_file_menu(
            self._keymap_menu,
            self._config.get_recent_keymaps(),
            self._config.get_last_keymap(),
            self._load_keymap_file,
            self._invalid_recent_keymaps,
            self._warning_recent_keymaps,
            self._browse_keymap,
        )
        self._populate_recent_file_menu(
            self._file_keymap_menu,
            self._config.get_recent_keymaps(),
            self._config.get_last_keymap(),
            self._load_keymap_file,
            self._invalid_recent_keymaps,
            self._warning_recent_keymaps,
            self._browse_keymap,
        )
        self._populate_recent_file_menu(
            self._layout_menu,
            self._config.get_recent_layouts(),
            self._config.get_last_layout(),
            self._load_layout_file,
            self._invalid_recent_layouts,
            self._warning_recent_layouts,
            self._browse_layout,
        )
        self._populate_recent_file_menu(
            self._file_layout_menu,
            self._config.get_recent_layouts(),
            self._config.get_last_layout(),
            self._load_layout_file,
            self._invalid_recent_layouts,
            self._warning_recent_layouts,
            self._browse_layout,
        )

    def _populate_recent_file_menu(
        self,
        menu: QMenu,
        recent_paths: list[str],
        current_path: str | None,
        loader,
        invalid_paths: set[str],
        warning_paths: set[str],
        browse_handler,
    ) -> None:
        """Populate one recent-file menu."""
        menu.clear()
        browse_action = menu.addAction("Browse...")
        browse_action.triggered.connect(browse_handler)

        if recent_paths:
            menu.addSeparator()
            for path in recent_paths:
                self._add_recent_file_action(
                    menu,
                    path,
                    current_path,
                    loader,
                    invalid_paths,
                    warning_paths,
                )

    def _browse_keymap(self) -> None:
        """Open file dialog to browse for keymap."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Keymap JSON",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if file_path:
            self._load_keymap_file(file_path)

    def _browse_layout(self) -> None:
        """Open file dialog to browse for layout."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Geometry JSON",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if file_path:
            self._load_layout_file(file_path)

    def _rebuild_layer_views(self) -> None:
        """Rebuild layer views list (built-in + custom)."""
        self._layer_views.clear()

        if not self._keymap:
            self._layer_combo.clear()
            self._layer_combo.setEnabled(False)
            self._add_view_btn.setEnabled(False)
            self._edit_view_btn.setEnabled(False)
            self._add_view_action.setEnabled(False)
            self._edit_view_action.setEnabled(False)
            self._refresh_layer_view_menu()
            return

        num_layers = self._keymap.layer_count
        named_layers = BASTARDKB_LAYER_NAMES if num_layers == len(BASTARDKB_LAYER_NAMES) else {}

        # Add single-layer views
        for i in range(num_layers):
            layer_name = str(i)
            if i in named_layers:
                layer_name = f"{layer_name} ({named_layers[i]})"
            self._layer_views.append(
                LayerViewConfig(name=layer_name, layers=[i], is_builtin=True)
            )

        # Add "All Layers" view
        self._layer_views.append(
            LayerViewConfig(
                name="All Layers",
                layers=list(range(num_layers)),
                is_builtin=True
            )
        )

        # Add custom views from config
        for custom_view in self._config.get_custom_views():
            # Filter to valid layer indices
            valid_layers = [l for l in custom_view.layers if l < num_layers]
            if valid_layers:
                self._layer_views.append(
                    LayerViewConfig(
                        name=custom_view.name,
                        layers=valid_layers,
                        is_builtin=False
                    )
                )

        # Update combobox
        self._layer_combo.clear()
        self._layer_combo.addItems([v.name for v in self._layer_views])
        self._apply_layer_combo_item_colors()
        self._layer_combo.setEnabled(True)
        self._layer_combo.setCurrentIndex(0)
        self._add_view_btn.setEnabled(True)
        self._add_view_action.setEnabled(True)
        self._refresh_layer_view_menu()

    def _layer_view_background_color(self, view: LayerViewConfig) -> QColor:
        """Return background color for a layer view item."""
        if len(view.layers) == 1:
            return QColor(self._config.get_layer_color(view.layers[0]))
        return QColor("#3a3a3a")

    def _apply_layer_combo_item_colors(self) -> None:
        """Color dropdown items by layer while leaving text color unchanged."""
        for index, view in enumerate(self._layer_views):
            self._layer_combo.setItemData(
                index,
                self._layer_view_background_color(view),
                Qt.ItemDataRole.BackgroundRole,
            )

    def _update_layer_combo_current_style(self) -> None:
        """Tint the current combobox field to match the selected layer/view."""
        index = self._layer_combo.currentIndex()
        if 0 <= index < len(self._layer_views):
            color = self._layer_view_background_color(self._layer_views[index]).name()
            self._layer_combo.setStyleSheet(f"QComboBox {{ background-color: {color}; }}")
        else:
            self._layer_combo.setStyleSheet("")

    def _refresh_layer_view_menu(self) -> None:
        """Update the Layer menu to match the combobox."""
        self._layer_view_menu.clear()
        if not self._layer_views:
            placeholder = self._layer_view_menu.addAction("No layers available")
            placeholder.setEnabled(False)
            return

        current_index = self._layer_combo.currentIndex()
        for index, view in enumerate(self._layer_views):
            action = self._layer_view_menu.addAction(view.name)
            action.setCheckable(True)
            action.setChecked(index == current_index)
            action.triggered.connect(
                lambda checked=False, target=index: self._layer_combo.setCurrentIndex(target)
            )

    def _reload_language_sound_bindings(self) -> None:
        """Reload language sound bindings from config."""
        self._language_sound_bindings = {
            binding.language.upper(): binding.sound_path
            for binding in self._config.get_language_sound_bindings()
        }

    def _ensure_tutor_user_selected(self) -> bool:
        """Always ask for tutor user before opening tutor."""
        while True:
            users = self._stats_db.list_users()
            dialog = TutorUserDialog(users, self)
            result = dialog.exec()
            if result == QDialog.DialogCode.Accepted:
                user_id = dialog.get_selected_user_id()
                if user_id is None:
                    return False
                user = self._stats_db.get_user(user_id)
                if user is None:
                    QMessageBox.warning(self, "Tutor User", "Selected user no longer exists.")
                    continue
                self._stats_db.touch_user(user.user_id)
                self._tutor_user = user
                self._config.set_last_tutor_user_id(user.user_id)
                if self._tutor_stats_window and self._tutor_stats_window.isVisible():
                    self._tutor_stats_window.set_current_user(user)
                self._debug_panel.log(f"Tutor user selected: {user.name}")
                return True
            if result == 1000:
                new_user_name = str(dialog.property("new_user_name") or "").strip()
                if not new_user_name:
                    continue
                try:
                    user = self._stats_db.create_user(new_user_name)
                except Exception as exc:
                    QMessageBox.warning(self, "Tutor User", str(exc))
                    continue
                self._stats_db.touch_user(user.user_id)
                self._tutor_user = user
                self._config.set_last_tutor_user_id(user.user_id)
                if self._tutor_stats_window and self._tutor_stats_window.isVisible():
                    self._tutor_stats_window.set_current_user(user)
                self._debug_panel.log(f"Tutor user created: {user.name}")
                return True
            return False

    def _get_layer_display_names(self, num_layers: int) -> list[str]:
        """Build display names for layer selectors and settings."""
        named_layers = BASTARDKB_LAYER_NAMES if num_layers == len(BASTARDKB_LAYER_NAMES) else {}
        names: list[str] = []
        for index in range(num_layers):
            name = str(index)
            if index in named_layers:
                name = f"{name} ({named_layers[index]})"
            names.append(name)
        return names

    def _build_key_descriptions_by_layer(self) -> dict[int, list[str]]:
        """Build per-layer key descriptions for settings."""
        if not self._keymap:
            return {}

        return {
            layer_index: self._keyboard_widget.get_key_descriptions_for_layer(layer_index)
            for layer_index in range(self._keymap.layer_count)
        }

    def _should_track_layout_changes(self) -> bool:
        """Return whether system language polling should be active."""
        tutor_open = bool(self._tutor_overlay and self._tutor_overlay.isVisible())
        return self._os_layout_mode or tutor_open or bool(self._language_sound_bindings)

    def _refresh_layout_tracking_timer(self) -> None:
        """Start or stop language polling as needed."""
        if self._should_track_layout_changes():
            if not self._layout_check_timer.isActive():
                self._layout_check_timer.start()
        else:
            if self._layout_check_timer.isActive():
                self._layout_check_timer.stop()
            self._tracked_layout_hwnd = None

    def _play_language_change_sound(self, language_name: str) -> None:
        """Play the configured sound for a language change."""
        sound_path = self._language_sound_bindings.get(language_name.upper())
        if sound_path:
            self._sound_player.play_file(sound_path)

    def _apply_os_layout_to_views(self) -> None:
        """Apply the current system language to the relevant views."""
        if self._os_layout_mode:
            self._update_layout_label()
            self._keyboard_widget.set_os_layout_mode(
                True,
                self._layout_detector,
                self._current_layout_hkl
            )
            self._keyboard_widget.set_caps_lock_mode(self._caps_lock_on)
        if self._keyboard_overlay and self._keyboard_overlay.isVisible():
            self._keyboard_overlay.set_os_layout_mode(
                self._os_layout_mode,
                self._layout_detector if self._os_layout_mode else None,
                self._current_layout_hkl if self._os_layout_mode else None,
            )
            self._keyboard_overlay.set_caps_lock_mode(self._caps_lock_on)
        if self._tutor_overlay and self._tutor_overlay.isVisible():
            self._tutor_overlay.set_os_layout_mode(
                True,
                self._layout_detector,
                self._current_layout_hkl
            )
            self._tutor_overlay.set_caps_lock_mode(self._caps_lock_on)

    def _apply_colors(self) -> None:
        """Apply color settings to keyboard widget."""
        if not self._keymap:
            return

        num_layers = self._keymap.layer_count
        colors = [self._config.get_layer_color(i) for i in range(num_layers)]
        self._keyboard_widget.set_layer_colors(colors)
        self._keyboard_widget.set_text_colors(
            self._config.get_tap_color(),
            self._config.get_hold_color()
        )
        self._keyboard_widget.set_visual_style(
            active_layer_text_color=self._config.get_active_layer_text_color(),
            tap_fill_color=self._config.get_tap_fill_color(),
            hold_fill_color=self._config.get_hold_fill_color(),
            tap_border_color=self._config.get_tap_border_color(),
            hold_border_color=self._config.get_hold_border_color(),
            hid_border_color=self._config.get_hid_border_color(),
            grid_line_color=self._config.get_grid_line_color(),
            tap_border_width=self._config.get_tap_border_width(),
            hold_border_width=self._config.get_hold_border_width(),
            hid_border_width=self._config.get_hid_border_width(),
            grid_line_width=self._config.get_grid_line_width(),
            hid_border_inset=self._config.get_hid_border_inset(),
            hid_border_style=self._config.get_hid_border_style(),
        )
        self._keyboard_widget.set_font_scales(
            self._config.get_label_font_scale_percent() / 100.0,
            self._config.get_grid_label_font_scale_percent() / 100.0,
        )
        self._keyboard_widget.set_finger_palette(self._build_finger_palette())
        if self._keyboard_overlay and self._keyboard_overlay.isVisible():
            self._keyboard_overlay.set_layer_colors(colors)
            self._keyboard_overlay.set_text_colors(
                self._config.get_tap_color(),
                self._config.get_hold_color(),
            )
            self._keyboard_overlay.set_visual_style(
                active_layer_text_color=self._config.get_active_layer_text_color(),
                tap_fill_color=self._config.get_tap_fill_color(),
                hold_fill_color=self._config.get_hold_fill_color(),
                tap_border_color=self._config.get_tap_border_color(),
                hold_border_color=self._config.get_hold_border_color(),
                hid_border_color=self._config.get_hid_border_color(),
                grid_line_color=self._config.get_grid_line_color(),
                tap_border_width=self._config.get_tap_border_width(),
                hold_border_width=self._config.get_hold_border_width(),
                hid_border_width=self._config.get_hid_border_width(),
                grid_line_width=self._config.get_grid_line_width(),
                hid_border_inset=self._config.get_hid_border_inset(),
                hid_border_style=self._config.get_hid_border_style(),
            )
            self._keyboard_overlay.set_font_scales(
                self._config.get_label_font_scale_percent() / 100.0,
                self._config.get_grid_label_font_scale_percent() / 100.0,
            )

    def _apply_hid_settings(self) -> None:
        """Apply saved HID highlight settings to the connected HID controller."""
        if not self._hid_controller:
            return

        color = QColor(self._config.get_hid_highlight_color())
        self._hid_controller.set_default_highlight_color(
            (color.red(), color.green(), color.blue())
        )
        self._hid_controller.set_default_highlight_duration_ms(
            self._config.get_hid_highlight_duration_ms()
        )

    def _build_finger_palette(self) -> dict[Finger, QColor]:
        """Build mirrored finger palette from config."""
        pinky = QColor(self._config.get_finger_color("pinky"))
        ring = QColor(self._config.get_finger_color("ring"))
        middle = QColor(self._config.get_finger_color("middle"))
        index = QColor(self._config.get_finger_color("index"))
        thumb = QColor(self._config.get_finger_color("thumb"))
        return {
            Finger.LEFT_PINKY: pinky,
            Finger.RIGHT_PINKY: pinky,
            Finger.LEFT_RING: ring,
            Finger.RIGHT_RING: ring,
            Finger.LEFT_MIDDLE: middle,
            Finger.RIGHT_MIDDLE: middle,
            Finger.LEFT_INDEX: index,
            Finger.RIGHT_INDEX: index,
            Finger.LEFT_THUMB: thumb,
            Finger.RIGHT_THUMB: thumb,
        }

    def _get_displayed_layer(self) -> int:
        """Return the currently displayed single layer."""
        index = self._layer_combo.currentIndex()
        if 0 <= index < len(self._layer_views):
            view = self._layer_views[index]
            if len(view.layers) == 1:
                return view.layers[0]
        return 0

    def _find_builtin_layer_view_index(self, layer_index: int) -> int | None:
        """Find the built-in combobox entry for a specific layer."""
        for index, view in enumerate(self._layer_views):
            if view.is_builtin and view.layers == [layer_index]:
                return index
        return None

    def _apply_active_layer(self, layer_index: int) -> None:
        """Record a hardware-reported active layer without changing the selected view."""
        self._keyboard_widget.set_observed_active_layer(layer_index)
        if self._keyboard_overlay and self._keyboard_overlay.isVisible():
            self._keyboard_overlay.set_observed_active_layer(layer_index)
        self._debug_panel.log(
            f"Apply active layer: requested={layer_index} last_polled={self._last_polled_layer} "
            f"displayed_before={self._get_displayed_layer()}"
        )
        self._debug_panel.log(
            f"HID active layer observed: {layer_index} (display view unchanged)"
        )

    def _poll_hid_layer(self) -> None:
        """Poll the keyboard for its current highest active layer."""
        if not self._hid_controller or not self._hid_controller.is_connected() or not self._keymap:
            return

        try:
            layer_index = self._hid_controller.get_highest_layer()
        except Exception as exc:
            self._debug_panel.log_error(f"HID layer polling error: {exc}")
            self._hid_layer_poll_timer.stop()
            return

        if layer_index is None or layer_index >= self._keymap.layer_count:
            self._debug_panel.log(
                f"HID layer poll ignored: layer_index={layer_index} layer_count={self._keymap.layer_count}"
            )
            return

        if layer_index != self._last_polled_layer:
            self._debug_panel.log(
                f"HID layer polled: layer_index={layer_index} last_polled={self._last_polled_layer} "
                f"pressed_phys={sorted(self._pressed_physical_key_indices)} "
                f"pressed_hid={sorted(self._pressed_hid_key_indices)}"
            )
            self._last_polled_layer = layer_index
            self._apply_active_layer(layer_index)

    def _add_custom_view(self) -> None:
        """Open dialog to add a custom layer view."""
        if not self._keymap:
            return

        existing_names = [v.name for v in self._layer_views]

        dialog = CustomLayerViewDialog(
            self,
            num_layers=self._keymap.layer_count,
            existing_names=existing_names
        )

        if dialog.exec():
            name = dialog.get_name()
            layers = dialog.get_selected_layers()

            if self._config.add_custom_view(name, layers):
                self._debug_panel.log_success(f"Created custom view: {name}")
                self._rebuild_layer_views()

                # Select the new view
                for i, v in enumerate(self._layer_views):
                    if v.name == name:
                        self._layer_combo.setCurrentIndex(i)
                        break

    def _edit_custom_view(self) -> None:
        """Open dialog to edit or delete the current custom view."""
        if not self._keymap:
            return

        index = self._layer_combo.currentIndex()
        if index < 0 or index >= len(self._layer_views):
            return

        view = self._layer_views[index]
        if view.is_builtin:
            return

        # Show context menu with Edit and Delete options
        menu = QMenu(self)
        edit_action = menu.addAction("Edit")
        delete_action = menu.addAction("Delete")

        action = menu.exec(self._edit_view_btn.mapToGlobal(
            self._edit_view_btn.rect().bottomLeft()
        ))

        if action == edit_action:
            existing_names = [v.name for v in self._layer_views if v.name != view.name]

            dialog = CustomLayerViewDialog(
                self,
                num_layers=self._keymap.layer_count,
                name=view.name,
                selected_layers=view.layers,
                existing_names=existing_names
            )

            if dialog.exec():
                new_name = dialog.get_name()
                new_layers = dialog.get_selected_layers()

                if self._config.update_custom_view(view.name, new_name, new_layers):
                    self._debug_panel.log_success(f"Updated custom view: {new_name}")
                    self._rebuild_layer_views()

                    # Select the updated view
                    for i, v in enumerate(self._layer_views):
                        if v.name == new_name:
                            self._layer_combo.setCurrentIndex(i)
                            break

        elif action == delete_action:
            reply = QMessageBox.question(
                self,
                "Delete View",
                f"Delete custom view '{view.name}'?",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                if self._config.delete_custom_view(view.name):
                    self._debug_panel.log(f"Deleted custom view: {view.name}")
                    self._rebuild_layer_views()

    def _open_settings(self) -> None:
        """Open settings dialog."""
        num_layers = self._keymap.layer_count if self._keymap else 7

        dialog = SettingsDialog(
            self._config,
            num_layers,
            self,
            key_descriptions_by_layer=self._build_key_descriptions_by_layer(),
            layer_names=self._get_layer_display_names(num_layers),
            layout_variant=self._layout,
            keymap=self._keymap,
            on_apply=self._apply_settings_changes,
        )

        if dialog.exec():
            self._apply_settings_changes()

    def _apply_settings_changes(self) -> None:
        """Apply already-saved settings to the live UI."""
        self._apply_colors()
        self._apply_hid_settings()
        self._reload_language_sound_bindings()
        self._tutor_key_scheme_assignments = load_tutor_key_scheme_assignments()
        self._keyboard_widget.set_tutor_scheme_data(
            self._tutor_hand_schemes,
            self._tutor_key_scheme_assignments,
        )
        self._refresh_layout_tracking_timer()
        if self._tutor_overlay and self._tutor_overlay.isVisible():
            self._tutor_overlay.set_show_hold_labels(self._config.get_tutor_show_hold_labels())
            self._tutor_overlay.set_show_finger_movement_arrows(
                self._config.get_tutor_show_movement_arrows()
            )
            self._tutor_overlay.set_finger_palette(self._build_finger_palette())
            self._tutor_overlay.set_tutor_scheme_data(
                self._tutor_hand_schemes,
                self._tutor_key_scheme_assignments,
            )
            self._tutor_overlay.set_click_sounds(
                self._config.get_tutor_click_sounds_enabled(),
                self._config.get_tutor_correct_sound(),
                self._config.get_tutor_incorrect_sound(),
            )
        self._keyboard_widget.set_show_finger_movement_arrows(
            self._config.get_tutor_show_movement_arrows()
        )
        if self._layer_views:
            self._on_layer_view_changed(self._layer_combo.currentIndex())
        self._debug_panel.log("Settings updated")

    def _load_last_session(self) -> None:
        """Load the last session's configuration."""
        # Load keymap
        last_keymap = self._config.get_last_keymap()
        if last_keymap and Path(last_keymap).exists():
            self._load_keymap_file(last_keymap)

        # Load layout
        last_layout = self._config.get_last_layout()
        if last_layout and Path(last_layout).exists():
            self._load_layout_file(last_layout)

        # Restore layer view selection
        last_view = self._config.get_last_layer_view()
        if self._layer_views:
            for i, v in enumerate(self._layer_views):
                if v.name == last_view:
                    self._layer_combo.setCurrentIndex(i)
                    break

        # Restore UI state
        if self._config.get_always_on_top():
            self._always_on_top_cb.blockSignals(True)
            self._always_on_top_cb.setChecked(True)
            self._always_on_top_cb.blockSignals(False)
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        if self._config.get_language_enabled():
            self._os_layout_cb.setChecked(True)

        # Auto-start hook if it was enabled
        if self._config.get_hook_enabled():
            self._hook_btn.setChecked(True)

        if HID_AVAILABLE and self._config.get_hid_connected():
            self._hid_connect_btn.setChecked(True)
        self._refresh_layout_tracking_timer()

    def _save_session(self) -> None:
        """Save current session state to config."""
        # Save layer view
        index = self._layer_combo.currentIndex()
        if 0 <= index < len(self._layer_views):
            self._config.set_last_layer_view(self._layer_views[index].name)

        # Save UI state
        self._config.set_always_on_top(self._always_on_top_cb.isChecked())
        self._config.set_language_enabled(self._os_layout_cb.isChecked())
        self._config.set_hook_enabled(self._hook_btn.isChecked())
        if HID_AVAILABLE:
            self._config.set_hid_connected(self._hid_connect_btn.isChecked())
            self._config.set_hid_click_enabled(self._hid_click_cb.isChecked())

    def _toggle_hid_connection(self, checked: bool) -> None:
        """Toggle HID keyboard connection."""
        if not HID_AVAILABLE:
            return

        if checked:
            # Try to connect
            try:
                self._hid_controller = get_keyboard_hid()
                if self._hid_controller and self._hid_controller.connect():
                    self._apply_hid_settings()
                    self._last_polled_layer = None
                    self._keyboard_widget.set_observed_active_layer(None)
                    self._last_hid_key_event_counter = None
                    self._pressed_hid_key_indices.clear()
                    self._hid_layer_poll_timer.start()
                    self._hid_key_event_poll_timer.start()
                    self._debug_panel.log("HID layer polling started")
                    device_info = self._hid_controller.get_device_info()
                    if device_info:
                        self._debug_panel.log_success(
                            f"HID connected: {device_info.product} "
                            f"(VID:{device_info.vendor_id:04X}, PID:{device_info.product_id:04X})"
                        )
                    else:
                        self._debug_panel.log_success("HID connected to keyboard")
                    self._update_hid_button_state(True)
                    self._hid_click_cb.setEnabled(True)
                    if self._hid_click_action is not None:
                        self._hid_click_action.setEnabled(True)
                    self._keyboard_widget.set_hid_controller(self._hid_controller)
                    self._config.set_hid_connected(True)
                    if self._config.get_hid_click_enabled():
                        self._hid_click_cb.setChecked(True)
                else:
                    self._debug_panel.log_error("Failed to connect to HID keyboard")
                    self._update_hid_button_state(False)
                    self._config.set_hid_connected(False)
                    self._hid_connect_btn.setChecked(False)
                    if self._hid_click_action is not None:
                        self._hid_click_action.setEnabled(False)
            except Exception as e:
                self._debug_panel.log_error(f"HID connection error: {e}")
                self._update_hid_button_state(False)
                self._config.set_hid_connected(False)
                self._hid_connect_btn.setChecked(False)
                if self._hid_click_action is not None:
                    self._hid_click_action.setEnabled(False)
        else:
            # Disconnect
            if self._hid_controller:
                self._hid_controller.disconnect()
                self._hid_controller = None
            self._hid_layer_poll_timer.stop()
            self._hid_key_event_poll_timer.stop()
            self._last_polled_layer = None
            self._keyboard_widget.set_observed_active_layer(None)
            self._last_hid_key_event_counter = None
            self._pressed_hid_key_indices.clear()
            self._debug_panel.log("HID layer polling stopped")
            self._update_hid_button_state(False)
            self._hid_click_cb.setChecked(False)
            self._hid_click_cb.setEnabled(False)
            if self._hid_click_action is not None:
                self._hid_click_action.setChecked(False)
                self._hid_click_action.setEnabled(False)
            self._keyboard_widget.set_hid_controller(None)
            self._keyboard_widget.clear_hid_highlights()
            self._debug_panel.log("HID disconnected")
            self._config.set_hid_connected(False)

    def _toggle_hid_click(self, checked: bool) -> None:
        """Toggle HID click mode for RGB highlighting."""
        self._hid_click_enabled = checked
        self._keyboard_widget.set_hid_click_enabled(checked)
        self._config.set_hid_click_enabled(checked)
        if checked:
            self._debug_panel.log("HID click mode enabled - click keys to highlight on keyboard")
        else:
            self._debug_panel.log("HID click mode disabled")

    def closeEvent(self, event) -> None:
        """Handle window close - cleanup resources and save session."""
        self._save_session()
        if self._input_backend.is_running():
            self._input_backend.stop()
        # Disconnect HID if connected
        self._hid_layer_poll_timer.stop()
        self._hid_key_event_poll_timer.stop()
        self._pressed_hid_key_indices.clear()
        if self._hid_controller:
            self._hid_controller.disconnect()
        event.accept()
