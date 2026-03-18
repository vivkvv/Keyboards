"""Dialogs for layer configuration and settings."""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QCheckBox,
    QPushButton,
    QColorDialog,
    QGroupBox,
    QScrollArea,
    QSpinBox,
    QWidget,
    QMessageBox,
    QFileDialog,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QHeaderView,
    QTabWidget,
    QSizePolicy,
    QFrame,
    QInputDialog,
)
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt

from ..utils import Config, LanguageSoundBinding, SoundBinding, TutorUser
from ..utils.tutor_hand_schemes import (
    TutorHandScheme,
    TutorHandSchemeSet,
    TutorKeySchemeAssignments,
    get_assigned_scheme_name,
    is_left_hand_key,
    load_tutor_hand_schemes,
    load_tutor_key_scheme_assignments,
    save_tutor_key_scheme_assignments,
)
from ..models import Keymap
from ..models.layout import Layout
from .hand_overlay import Finger
from .keyboard_widget import KeyboardWidget


class TutorSchemeAssignmentWidget(QWidget):
    """Visual editor for per-key tutor hand scheme assignments."""

    def __init__(
        self,
        layout: Layout | None,
        keymap: Keymap | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._schemes = load_tutor_hand_schemes()
        self._assignments = load_tutor_key_scheme_assignments()
        self._selected_key_index: int | None = None
        self._key_names = self._build_key_names(keymap)
        self._finger_override_combos: dict[Finger, QComboBox] = {}

        layout_root = QHBoxLayout(self)
        layout_root.setContentsMargins(0, 0, 0, 0)
        layout_root.setSpacing(12)

        self._keyboard = KeyboardWidget()
        self._keyboard.setMinimumSize(640, 320)
        self._keyboard.set_tutor_mode(True)
        self._keyboard.set_show_hold_labels(False)
        self._keyboard.set_show_finger_movement_arrows(False)
        self._keyboard.set_tutor_scheme_data(self._schemes, self._assignments)
        self._keyboard.set_hid_click_enabled(True)
        self._keyboard.key_clicked.connect(self._select_key)
        if layout:
            self._keyboard.set_layout(layout)
        if keymap:
            self._keyboard.set_keymap(keymap)
        layout_root.addWidget(self._keyboard, 1)

        form = QFormLayout()
        self._selected_label = QLabel("Click a key")
        self._selected_label.setWordWrap(True)
        self._selected_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        form.addRow("Key:", self._selected_label)

        self._hand_label = QLabel("-")
        form.addRow("Hand:", self._hand_label)

        self._scheme_combo = QComboBox()
        self._scheme_combo.setMinimumContentsLength(22)
        self._scheme_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._scheme_combo.currentIndexChanged.connect(self._scheme_changed)
        form.addRow("Scheme:", self._scheme_combo)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        form.addRow(separator)

        self._override_hint = QLabel("Finger overrides for this key")
        self._override_hint.setStyleSheet("color: #b0b0b0; font-weight: 600;")
        form.addRow(self._override_hint)

        self._override_panel = QWidget()
        self._override_form = QFormLayout(self._override_panel)
        self._override_form.setContentsMargins(0, 0, 0, 0)

        side_panel = QWidget()
        side_panel.setFixedWidth(320)
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addLayout(form)
        side_layout.addWidget(self._override_panel)
        side_layout.addStretch()
        layout_root.addWidget(side_panel, 0)
        self._override_panel.hide()

    def _build_key_names(self, keymap: Keymap | None) -> dict[int, str]:
        """Build simple base-layer labels for keys."""
        if not keymap or not keymap.layers:
            return {}
        layer0 = keymap.layers[0]
        names: dict[int, str] = {}
        for index, keycode in enumerate(layer0):
            if keycode == "KC_NO":
                continue
            label = keycode or f"Key {index}"
            if keycode.startswith("KC_"):
                label = keycode[3:]
            names[index] = label
        return names

    def _select_key(self, key_index: int) -> None:
        """Select a key in the preview keyboard."""
        self._selected_key_index = key_index
        hand = "Left" if is_left_hand_key(key_index) else "Right"
        self._hand_label.setText(hand)
        self._selected_label.setText(self._key_names.get(key_index, f"Key {key_index}"))
        self._populate_scheme_combo()
        self._populate_override_controls()
        self._refresh_preview()

    def _populate_scheme_combo(self) -> None:
        """Populate available schemes for the selected key."""
        self._scheme_combo.blockSignals(True)
        self._scheme_combo.clear()
        if self._selected_key_index is None:
            self._scheme_combo.setEnabled(False)
            self._scheme_combo.blockSignals(False)
            return

        hand = "left" if is_left_hand_key(self._selected_key_index) else "right"
        schemes = self._schemes.schemes_for_hand(hand)
        for scheme in schemes:
            self._scheme_combo.addItem(scheme.label, scheme.name)

        effective_scheme = get_assigned_scheme_name(
            self._selected_key_index,
            self._schemes,
            self._assignments,
        )
        current_index = self._scheme_combo.findData(effective_scheme)
        if current_index >= 0:
            self._scheme_combo.setCurrentIndex(current_index)
        self._scheme_combo.setEnabled(bool(schemes))
        self._scheme_combo.blockSignals(False)

    def _scheme_changed(self) -> None:
        """Assign the selected scheme to the current key."""
        if self._selected_key_index is None or self._scheme_combo.currentIndex() < 0:
            return
        scheme_name = str(self._scheme_combo.currentData())
        self._assignments.schemes[self._selected_key_index] = scheme_name
        self._populate_override_controls()
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        """Refresh keyboard preview with current key/scheme selection."""
        self._keyboard.set_tutor_scheme_data(self._schemes, self._assignments)
        self._keyboard.clear_hid_highlights()
        self._keyboard.hide_finger_hints()
        if self._selected_key_index is None:
            return
        self._keyboard.set_hid_key_active(self._selected_key_index, True)
        self._keyboard.show_finger_hint(self._selected_key_index)

    def _populate_override_controls(self) -> None:
        """Populate per-finger override controls for the selected key."""
        while self._override_form.rowCount() > 0:
            self._override_form.removeRow(0)
        self._finger_override_combos.clear()

        if self._selected_key_index is None:
            self._override_panel.hide()
            return

        hand = "left" if is_left_hand_key(self._selected_key_index) else "right"
        scheme_name = get_assigned_scheme_name(
            self._selected_key_index,
            self._schemes,
            self._assignments,
        )
        scheme = self._schemes.schemes.get(scheme_name)
        if scheme is None:
            self._override_panel.hide()
            return

        hand_keys = sorted(
            key_index for key_index in self._key_names
            if is_left_hand_key(key_index) == (hand == "left")
        )
        current_overrides = self._assignments.overrides.get(self._selected_key_index, {})

        for finger_name in sorted(scheme.home_positions.keys()):
            finger = Finger[finger_name]
            combo = QComboBox()
            combo.addItem("Default", None)
            combo.addItem("Off keyboard", -1)
            for key_index in hand_keys:
                combo.addItem(self._key_names.get(key_index, f"Key {key_index}"), key_index)

            override_value = current_overrides.get(finger_name)
            if override_value is not None:
                combo_index = combo.findData(override_value)
                if combo_index >= 0:
                    combo.setCurrentIndex(combo_index)

            combo.currentIndexChanged.connect(
                lambda _=0, finger_value=finger, combo_value=combo: self._override_changed(finger_value, combo_value)
            )
            self._finger_override_combos[finger] = combo

            label = finger_name.replace(f"{hand.upper()}_", "").title().replace("_", " ")
            self._override_form.addRow(f"{label}:", combo)

        self._override_panel.show()

    def _override_changed(self, finger: Finger, combo: QComboBox) -> None:
        """Store one finger override for the selected key."""
        if self._selected_key_index is None:
            return
        overrides = self._assignments.overrides.setdefault(self._selected_key_index, {})
        override_value = combo.currentData()
        if override_value is None:
            overrides.pop(finger.name, None)
        else:
            overrides[finger.name] = int(override_value)
        if not overrides:
            self._assignments.overrides.pop(self._selected_key_index, None)
        self._refresh_preview()

    def save(self) -> None:
        """Persist assignments to JSON."""
        save_tutor_key_scheme_assignments(self._assignments)

    def set_show_movement_arrows(self, enabled: bool) -> None:
        """Update preview arrow visibility."""
        self._keyboard.set_show_finger_movement_arrows(enabled)


class TutorUserDialog(QDialog):
    """Choose an existing tutor user or create a new one."""

    def __init__(self, users: list[TutorUser], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._users = users
        self._selected_user_id: int | None = users[0].user_id if users else None
        self.setWindowTitle("Tutor User")
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)

        info = QLabel("Choose a tutor user or create a new one.")
        layout.addWidget(info)

        form = QFormLayout()
        self._user_combo = QComboBox()
        for user in users:
            self._user_combo.addItem(user.name, user.user_id)
        self._user_combo.currentIndexChanged.connect(self._sync_selected_user)
        form.addRow("User:", self._user_combo)
        layout.addLayout(form)

        create_btn = QPushButton("New User")
        create_btn.clicked.connect(self._create_user)
        layout.addWidget(create_btn, 0, Qt.AlignmentFlag.AlignLeft)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        buttons.addWidget(ok_btn)
        layout.addLayout(buttons)

    def _sync_selected_user(self) -> None:
        """Track current combo selection."""
        self._selected_user_id = self._user_combo.currentData()

    def _create_user(self) -> None:
        """Ask main window to create a new user name."""
        name, ok = QInputDialog.getText(self, "New Tutor User", "User name:")
        if not ok:
            return
        clean_name = name.strip()
        if not clean_name:
            QMessageBox.warning(self, "User Name", "User name must not be empty.")
            return
        self.done(1000)
        self._selected_user_id = None
        self.setProperty("new_user_name", clean_name)

    def get_selected_user_id(self) -> int | None:
        """Return selected existing user id."""
        return self._selected_user_id


class CustomLayerViewDialog(QDialog):
    """Dialog for creating/editing custom layer views."""

    def __init__(
        self,
        parent: QWidget | None = None,
        num_layers: int = 7,
        name: str = "",
        selected_layers: list[int] | None = None,
        existing_names: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._num_layers = num_layers
        self._existing_names = [n.lower() for n in (existing_names or [])]
        self._original_name = name.lower()

        self.setWindowTitle("Custom Layer View" if not name else "Edit Layer View")
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)

        # Name input
        form_layout = QFormLayout()
        self._name_edit = QLineEdit(name)
        self._name_edit.setPlaceholderText("e.g., Base+Nav")
        form_layout.addRow("Name:", self._name_edit)
        layout.addLayout(form_layout)

        # Layer checkboxes
        layers_group = QGroupBox("Select Layers")
        layers_layout = QVBoxLayout(layers_group)

        self._layer_checkboxes: list[QCheckBox] = []
        for i in range(num_layers):
            cb = QCheckBox(f"Layer {i}")
            if selected_layers and i in selected_layers:
                cb.setChecked(True)
            self._layer_checkboxes.append(cb)
            layers_layout.addWidget(cb)

        layout.addWidget(layers_group)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._validate_and_accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

    def _validate_and_accept(self) -> None:
        """Validate input and accept dialog."""
        name = self._name_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "Error", "Please enter a name.")
            return

        # Check for duplicate names (excluding original name if editing)
        if name.lower() != self._original_name and name.lower() in self._existing_names:
            QMessageBox.warning(self, "Error", "A view with this name already exists.")
            return

        selected = self.get_selected_layers()
        if not selected:
            QMessageBox.warning(self, "Error", "Please select at least one layer.")
            return

        self.accept()

    def get_name(self) -> str:
        """Get the entered name."""
        return self._name_edit.text().strip()

    def get_selected_layers(self) -> list[int]:
        """Get the list of selected layer indices."""
        return [i for i, cb in enumerate(self._layer_checkboxes) if cb.isChecked()]


class ColorButton(QPushButton):
    """Button that displays and allows selecting a color."""

    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._update_style()
        self.clicked.connect(self._pick_color)
        self.setFixedSize(60, 25)

    def _update_style(self) -> None:
        """Update button style to show current color."""
        # Determine text color based on background brightness
        brightness = (
            self._color.red() * 299 +
            self._color.green() * 587 +
            self._color.blue() * 114
        ) / 1000
        text_color = "#000000" if brightness > 128 else "#ffffff"

        self.setStyleSheet(
            f"background-color: {self._color.name()}; "
            f"color: {text_color}; "
            f"border: 1px solid #5c5c5c; "
            f"border-radius: 3px;"
        )
        self.setText(self._color.name())

    def _pick_color(self) -> None:
        """Open color picker dialog."""
        color = QColorDialog.getColor(self._color, self, "Select Color")
        if color.isValid():
            self._color = color
            self._update_style()

    def get_color(self) -> str:
        """Get the current color as hex string."""
        return self._color.name()

    def set_color(self, color: str) -> None:
        """Set the current color."""
        self._color = QColor(color)
        self._update_style()


class SoundBindingDialog(QDialog):
    """Dialog to create or edit a sound binding."""

    def __init__(
        self,
        parent: QWidget | None = None,
        num_layers: int = 7,
        key_descriptions_by_layer: dict[int, list[str]] | None = None,
        layer_names: list[str] | None = None,
        binding: SoundBinding | None = None,
    ) -> None:
        super().__init__(parent)
        self._key_descriptions_by_layer = key_descriptions_by_layer or {}
        self._layer_names = layer_names or [f"Layer {index}" for index in range(num_layers)]
        self._sound_path = binding.sound_path if binding else ""

        self.setWindowTitle("Edit Sound Binding" if binding else "Add Sound Binding")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self._layer_combo = QComboBox()
        self._layer_combo.addItems(self._layer_names[:num_layers])
        self._layer_combo.setCurrentIndex(binding.layer if binding and 0 <= binding.layer < self._layer_combo.count() else 0)
        self._layer_combo.currentIndexChanged.connect(self._refresh_key_combo)
        form_layout.addRow("Layer:", self._layer_combo)

        self._key_combo = QComboBox()
        self._refresh_key_combo(binding.key_index if binding else 0)
        form_layout.addRow("Key:", self._key_combo)

        sound_row = QHBoxLayout()
        self._sound_path_label = QLineEdit(self._sound_path)
        self._sound_path_label.setReadOnly(True)
        sound_row.addWidget(self._sound_path_label)

        self._browse_btn = QPushButton("Browse...")
        self._browse_btn.clicked.connect(self._browse_sound)
        sound_row.addWidget(self._browse_btn)
        form_layout.addRow("Sound:", sound_row)

        layout.addLayout(form_layout)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._validate_and_accept)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

    def _browse_sound(self) -> None:
        """Browse for a sound file."""
        start_dir = self._sound_path if self._sound_path else str(Config.DEFAULT_CONFIG_PATH.parent)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Sound File",
            start_dir,
            "WAV Files (*.wav);;All Files (*)",
        )
        if path:
            self._sound_path = path
            self._sound_path_label.setText(path)

    def _refresh_key_combo(self, preferred_index: int | None = None) -> None:
        """Refresh key list according to the selected layer."""
        current_layer = self._layer_combo.currentIndex()
        descriptions = self._key_descriptions_by_layer.get(current_layer, [])
        self._key_combo.clear()
        self._key_combo.addItems(descriptions)
        if preferred_index is None:
            return
        if 0 <= preferred_index < self._key_combo.count():
            self._key_combo.setCurrentIndex(preferred_index)

    def _validate_and_accept(self) -> None:
        """Validate the dialog fields."""
        if self._key_combo.currentIndex() < 0:
            QMessageBox.warning(self, "Error", "Please select a key.")
            return
        if not self._sound_path:
            QMessageBox.warning(self, "Error", "Please select a sound file.")
            return
        self.accept()

    def get_binding(self) -> SoundBinding:
        """Return the configured sound binding."""
        return SoundBinding(
            layer=self._layer_combo.currentIndex(),
            key_index=self._key_combo.currentIndex(),
            sound_path=self._sound_path,
        )


class LanguageSoundBindingDialog(QDialog):
    """Dialog to create or edit a language sound binding."""

    COMMON_LANGUAGES = [
        "EN-US",
        "EN-UK",
        "RU",
        "UK",
        "DE",
        "FR",
        "IT",
        "ES",
        "PL",
    ]

    def __init__(
        self,
        parent: QWidget | None = None,
        binding: LanguageSoundBinding | None = None,
    ) -> None:
        super().__init__(parent)
        self._sound_path = binding.sound_path if binding else ""

        self.setWindowTitle("Edit Language Sound" if binding else "Add Language Sound")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self._language_combo = QComboBox()
        self._language_combo.setEditable(True)
        self._language_combo.addItems(self.COMMON_LANGUAGES)
        if binding and binding.language:
            self._language_combo.setCurrentText(binding.language)
        form_layout.addRow("Language:", self._language_combo)

        sound_row = QHBoxLayout()
        self._sound_path_label = QLineEdit(self._sound_path)
        self._sound_path_label.setReadOnly(True)
        sound_row.addWidget(self._sound_path_label)

        self._browse_btn = QPushButton("Browse...")
        self._browse_btn.clicked.connect(self._browse_sound)
        sound_row.addWidget(self._browse_btn)
        form_layout.addRow("Sound:", sound_row)

        layout.addLayout(form_layout)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._validate_and_accept)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

    def _browse_sound(self) -> None:
        """Browse for a sound file."""
        start_dir = self._sound_path if self._sound_path else str(Config.DEFAULT_CONFIG_PATH.parent)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Sound File",
            start_dir,
            "WAV Files (*.wav);;All Files (*)",
        )
        if path:
            self._sound_path = path
            self._sound_path_label.setText(path)

    def _validate_and_accept(self) -> None:
        """Validate dialog fields."""
        if not self._language_combo.currentText().strip():
            QMessageBox.warning(self, "Error", "Please enter a language.")
            return
        if not self._sound_path:
            QMessageBox.warning(self, "Error", "Please select a sound file.")
            return
        self.accept()

    def get_binding(self) -> LanguageSoundBinding:
        """Return configured language sound binding."""
        return LanguageSoundBinding(
            language=self._language_combo.currentText().strip(),
            sound_path=self._sound_path,
        )


class SettingsDialog(QDialog):
    """Dialog for application settings (colors)."""

    def __init__(
        self,
        config: Config,
        num_layers: int = 7,
        parent: QWidget | None = None,
        key_descriptions_by_layer: dict[int, list[str]] | None = None,
        layer_names: list[str] | None = None,
        layout_variant: Layout | None = None,
        keymap: Keymap | None = None,
        on_apply=None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._num_layers = num_layers
        self._key_descriptions_by_layer = key_descriptions_by_layer or {}
        self._layer_names = layer_names or [f"Layer {index}" for index in range(num_layers)]
        self._language_sound_bindings = config.get_language_sound_bindings()
        self._tutor_scheme_widget = TutorSchemeAssignmentWidget(layout_variant, keymap, self)
        self._on_apply = on_apply
        self._hid_border_style_options = {
            "Solid": "solid",
            "Dashed": "dash",
            "Dotted": "dot",
        }

        self.setWindowTitle("Settings")
        self.setMinimumWidth(700)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # Layer colors
        layer_group = QGroupBox("Layer Colors")
        layer_layout = QFormLayout(layer_group)

        self._layer_color_buttons: list[ColorButton] = []
        for i in range(num_layers):
            btn = ColorButton(config.get_layer_color(i))
            self._layer_color_buttons.append(btn)
            layer_layout.addRow(f"Layer {i}:", btn)
        layer_tab = QWidget()
        layer_tab_layout = QVBoxLayout(layer_tab)
        layer_tab_layout.addWidget(layer_group)
        layer_tab_layout.addStretch()
        tabs.addTab(layer_tab, "Layer Colors")

        # Text colors
        text_group = QGroupBox("Text Colors")
        text_layout = QFormLayout(text_group)

        self._tap_color_btn = ColorButton(config.get_tap_color())
        text_layout.addRow("Tap:", self._tap_color_btn)

        self._hold_color_btn = ColorButton(config.get_hold_color())
        text_layout.addRow("Hold:", self._hold_color_btn)

        self._label_font_scale_spin = QSpinBox()
        self._label_font_scale_spin.setRange(50, 200)
        self._label_font_scale_spin.setSingleStep(5)
        self._label_font_scale_spin.setSuffix(" %")
        self._label_font_scale_spin.setValue(config.get_label_font_scale_percent())
        text_layout.addRow("Label size:", self._label_font_scale_spin)

        self._grid_label_font_scale_spin = QSpinBox()
        self._grid_label_font_scale_spin.setRange(1, 200)
        self._grid_label_font_scale_spin.setSingleStep(5)
        self._grid_label_font_scale_spin.setSuffix(" %")
        self._grid_label_font_scale_spin.setValue(config.get_grid_label_font_scale_percent())
        text_layout.addRow("All Layers size:", self._grid_label_font_scale_spin)

        self._tutor_show_hold_labels_cb = QCheckBox("Show hold labels in tutor")
        self._tutor_show_hold_labels_cb.setChecked(config.get_tutor_show_hold_labels())
        text_layout.addRow("", self._tutor_show_hold_labels_cb)
        text_tab = QWidget()
        text_tab_layout = QVBoxLayout(text_tab)
        text_tab_layout.addWidget(text_group)
        text_tab_layout.addStretch()
        tabs.addTab(text_tab, "Text")

        interaction_group = QGroupBox("Press / Hold")
        interaction_layout = QFormLayout(interaction_group)

        self._tap_fill_color_btn = ColorButton(config.get_tap_fill_color())
        interaction_layout.addRow("Tap fill:", self._tap_fill_color_btn)

        self._hold_fill_color_btn = ColorButton(config.get_hold_fill_color())
        interaction_layout.addRow("Hold fill:", self._hold_fill_color_btn)

        self._tap_border_color_btn = ColorButton(config.get_tap_border_color())
        interaction_layout.addRow("Tap border:", self._tap_border_color_btn)

        self._hold_border_color_btn = ColorButton(config.get_hold_border_color())
        interaction_layout.addRow("Hold border:", self._hold_border_color_btn)

        self._tap_border_width_spin = QSpinBox()
        self._tap_border_width_spin.setRange(1, 8)
        self._tap_border_width_spin.setValue(config.get_tap_border_width())
        interaction_layout.addRow("Tap border width:", self._tap_border_width_spin)

        self._hold_border_width_spin = QSpinBox()
        self._hold_border_width_spin.setRange(1, 8)
        self._hold_border_width_spin.setValue(config.get_hold_border_width())
        interaction_layout.addRow("Hold border width:", self._hold_border_width_spin)

        interaction_tab = QWidget()
        interaction_tab_layout = QVBoxLayout(interaction_tab)
        interaction_tab_layout.addWidget(interaction_group)
        interaction_tab_layout.addStretch()
        tabs.addTab(interaction_tab, "Interaction")

        grid_group = QGroupBox("All Layers / Grid")
        grid_layout = QFormLayout(grid_group)

        self._active_layer_text_color_btn = ColorButton(config.get_active_layer_text_color())
        grid_layout.addRow("Active layer text:", self._active_layer_text_color_btn)

        self._grid_line_color_btn = ColorButton(config.get_grid_line_color())
        grid_layout.addRow("Grid line color:", self._grid_line_color_btn)

        self._grid_line_width_spin = QSpinBox()
        self._grid_line_width_spin.setRange(1, 6)
        self._grid_line_width_spin.setValue(config.get_grid_line_width())
        grid_layout.addRow("Grid line width:", self._grid_line_width_spin)

        self._hid_border_color_btn = ColorButton(config.get_hid_border_color())
        grid_layout.addRow("HID border color:", self._hid_border_color_btn)

        self._hid_border_width_spin = QSpinBox()
        self._hid_border_width_spin.setRange(1, 6)
        self._hid_border_width_spin.setValue(config.get_hid_border_width())
        grid_layout.addRow("HID border width:", self._hid_border_width_spin)

        self._hid_border_inset_spin = QSpinBox()
        self._hid_border_inset_spin.setRange(0, 12)
        self._hid_border_inset_spin.setValue(config.get_hid_border_inset())
        grid_layout.addRow("HID inset:", self._hid_border_inset_spin)

        self._hid_border_style_combo = QComboBox()
        for label, value in self._hid_border_style_options.items():
            self._hid_border_style_combo.addItem(label, value)
        current_hid_style = config.get_hid_border_style()
        current_hid_style_index = self._hid_border_style_combo.findData(current_hid_style)
        if current_hid_style_index >= 0:
            self._hid_border_style_combo.setCurrentIndex(current_hid_style_index)
        grid_layout.addRow("HID line style:", self._hid_border_style_combo)

        grid_tab = QWidget()
        grid_tab_layout = QVBoxLayout(grid_tab)
        grid_tab_layout.addWidget(grid_group)
        grid_tab_layout.addStretch()
        tabs.addTab(grid_tab, "All Layers")

        tutor_group = QGroupBox("Tutor Finger Colors")
        tutor_layout = QFormLayout(tutor_group)
        self._finger_color_buttons = {
            "pinky": ColorButton(config.get_finger_color("pinky")),
            "ring": ColorButton(config.get_finger_color("ring")),
            "middle": ColorButton(config.get_finger_color("middle")),
            "index": ColorButton(config.get_finger_color("index")),
            "thumb": ColorButton(config.get_finger_color("thumb")),
        }
        tutor_layout.addRow("Pinky:", self._finger_color_buttons["pinky"])
        tutor_layout.addRow("Ring:", self._finger_color_buttons["ring"])
        tutor_layout.addRow("Middle:", self._finger_color_buttons["middle"])
        tutor_layout.addRow("Index:", self._finger_color_buttons["index"])
        tutor_layout.addRow("Thumb:", self._finger_color_buttons["thumb"])

        self._tutor_click_sounds_cb = QCheckBox("Play correct/incorrect key sounds")
        self._tutor_click_sounds_cb.setChecked(config.get_tutor_click_sounds_enabled())
        tutor_layout.addRow("", self._tutor_click_sounds_cb)

        self._tutor_movement_arrows_cb = QCheckBox("Show finger movement arrows")
        self._tutor_movement_arrows_cb.setChecked(config.get_tutor_show_movement_arrows())
        self._tutor_movement_arrows_cb.toggled.connect(self._tutor_scheme_widget.set_show_movement_arrows)
        tutor_layout.addRow("", self._tutor_movement_arrows_cb)

        self._tutor_correct_sound = config.get_tutor_correct_sound()
        correct_row = QHBoxLayout()
        self._tutor_correct_sound_label = QLineEdit(self._tutor_correct_sound)
        self._tutor_correct_sound_label.setReadOnly(True)
        correct_row.addWidget(self._tutor_correct_sound_label)
        correct_btn = QPushButton("Browse...")
        correct_btn.clicked.connect(self._browse_tutor_correct_sound)
        correct_row.addWidget(correct_btn)
        tutor_layout.addRow("Correct sound:", correct_row)

        self._tutor_incorrect_sound = config.get_tutor_incorrect_sound()
        incorrect_row = QHBoxLayout()
        self._tutor_incorrect_sound_label = QLineEdit(self._tutor_incorrect_sound)
        self._tutor_incorrect_sound_label.setReadOnly(True)
        incorrect_row.addWidget(self._tutor_incorrect_sound_label)
        incorrect_btn = QPushButton("Browse...")
        incorrect_btn.clicked.connect(self._browse_tutor_incorrect_sound)
        incorrect_row.addWidget(incorrect_btn)
        tutor_layout.addRow("Incorrect sound:", incorrect_row)
        tutor_tab = QWidget()
        tutor_tab_layout = QVBoxLayout(tutor_tab)
        tutor_tab_layout.addWidget(tutor_group)
        tutor_tab_layout.addStretch()
        tabs.addTab(tutor_tab, "Tutor")

        # Physical keyboard highlight settings
        hid_group = QGroupBox("Physical Keyboard Highlight")
        hid_layout = QFormLayout(hid_group)

        self._hid_highlight_color_btn = ColorButton(config.get_hid_highlight_color())
        hid_layout.addRow("Color:", self._hid_highlight_color_btn)

        self._hid_highlight_duration_spin = QSpinBox()
        self._hid_highlight_duration_spin.setRange(0, 10000)
        self._hid_highlight_duration_spin.setSingleStep(100)
        self._hid_highlight_duration_spin.setSuffix(" ms")
        self._hid_highlight_duration_spin.setValue(config.get_hid_highlight_duration_ms())
        hid_layout.addRow("Duration:", self._hid_highlight_duration_spin)
        hid_tab = QWidget()
        hid_tab_layout = QVBoxLayout(hid_tab)
        hid_tab_layout.addWidget(hid_group)
        hid_tab_layout.addStretch()
        tabs.addTab(hid_tab, "Physical Keyboard")

        language_sound_group = QGroupBox("Language Sound Bindings")
        language_sound_layout = QVBoxLayout(language_sound_group)

        self._language_sound_table = QTableWidget(0, 2)
        self._language_sound_table.setHorizontalHeaderLabels(["Language", "Sound"])
        self._language_sound_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._language_sound_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._language_sound_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._language_sound_table.verticalHeader().setVisible(False)
        language_header = self._language_sound_table.horizontalHeader()
        language_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        language_header.setSectionResizeMode(1, QHeaderView.Stretch)
        language_sound_layout.addWidget(self._language_sound_table)

        language_sound_btn_layout = QHBoxLayout()
        self._language_sound_add_btn = QPushButton("Add")
        self._language_sound_add_btn.clicked.connect(self._add_language_sound_binding)
        language_sound_btn_layout.addWidget(self._language_sound_add_btn)

        self._language_sound_edit_btn = QPushButton("Edit")
        self._language_sound_edit_btn.clicked.connect(self._edit_language_sound_binding)
        language_sound_btn_layout.addWidget(self._language_sound_edit_btn)

        self._language_sound_delete_btn = QPushButton("Delete")
        self._language_sound_delete_btn.clicked.connect(self._delete_language_sound_binding)
        language_sound_btn_layout.addWidget(self._language_sound_delete_btn)
        language_sound_btn_layout.addStretch()
        language_sound_layout.addLayout(language_sound_btn_layout)

        self._refresh_language_sound_bindings_table()
        language_sound_tab = QWidget()
        language_sound_tab_layout = QVBoxLayout(language_sound_tab)
        language_sound_tab_layout.addWidget(language_sound_group)
        language_sound_tab_layout.addStretch()
        tabs.addTab(language_sound_tab, "Language Sounds")

        scheme_tab = QWidget()
        scheme_tab_layout = QVBoxLayout(scheme_tab)
        scheme_tab_layout.addWidget(self._tutor_scheme_widget)
        tabs.addTab(scheme_tab, "Tutor Schemes")
        self._tutor_scheme_widget.set_show_movement_arrows(config.get_tutor_show_movement_arrows())

        # Buttons
        btn_layout = QHBoxLayout()

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(reset_btn)

        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_only)
        btn_layout.addWidget(apply_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._save_and_accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

    def _reset_defaults(self) -> None:
        """Reset all colors to defaults."""
        for i, btn in enumerate(self._layer_color_buttons):
            default = Config.DEFAULT_LAYER_COLORS[i % len(Config.DEFAULT_LAYER_COLORS)]
            btn.set_color(default)

        self._tap_color_btn.set_color(Config.DEFAULT_TAP_COLOR)
        self._hold_color_btn.set_color(Config.DEFAULT_HOLD_COLOR)
        self._active_layer_text_color_btn.set_color(Config.DEFAULT_ACTIVE_LAYER_TEXT_COLOR)
        self._tutor_show_hold_labels_cb.setChecked(Config.DEFAULT_TUTOR_SHOW_HOLD_LABELS)
        self._tap_fill_color_btn.set_color(Config.DEFAULT_TAP_FILL_COLOR)
        self._hold_fill_color_btn.set_color(Config.DEFAULT_HOLD_FILL_COLOR)
        self._tap_border_color_btn.set_color(Config.DEFAULT_TAP_BORDER_COLOR)
        self._hold_border_color_btn.set_color(Config.DEFAULT_HOLD_BORDER_COLOR)
        self._tap_border_width_spin.setValue(Config.DEFAULT_TAP_BORDER_WIDTH)
        self._hold_border_width_spin.setValue(Config.DEFAULT_HOLD_BORDER_WIDTH)
        self._grid_line_color_btn.set_color(Config.DEFAULT_GRID_LINE_COLOR)
        self._grid_line_width_spin.setValue(Config.DEFAULT_GRID_LINE_WIDTH)
        self._hid_border_color_btn.set_color(Config.DEFAULT_HID_BORDER_COLOR)
        self._hid_border_width_spin.setValue(Config.DEFAULT_HID_BORDER_WIDTH)
        self._hid_border_inset_spin.setValue(Config.DEFAULT_HID_BORDER_INSET)
        hid_style_index = self._hid_border_style_combo.findData(Config.DEFAULT_HID_BORDER_STYLE)
        if hid_style_index >= 0:
            self._hid_border_style_combo.setCurrentIndex(hid_style_index)
        for name, color in Config.DEFAULT_FINGER_COLORS.items():
            self._finger_color_buttons[name].set_color(color)
        self._tutor_click_sounds_cb.setChecked(Config.DEFAULT_TUTOR_CLICK_SOUNDS_ENABLED)
        self._tutor_movement_arrows_cb.setChecked(Config.DEFAULT_TUTOR_SHOW_MOVEMENT_ARROWS)
        self._tutor_correct_sound = str(Config.DEFAULT_TUTOR_CORRECT_SOUND)
        self._tutor_correct_sound_label.setText(self._tutor_correct_sound)
        self._tutor_incorrect_sound = str(Config.DEFAULT_TUTOR_INCORRECT_SOUND)
        self._tutor_incorrect_sound_label.setText(self._tutor_incorrect_sound)
        self._hid_highlight_color_btn.set_color(Config.DEFAULT_HID_HIGHLIGHT_COLOR)
        self._hid_highlight_duration_spin.setValue(Config.DEFAULT_HID_HIGHLIGHT_DURATION_MS)
        self._language_sound_bindings = []
        self._refresh_language_sound_bindings_table()

    def _browse_tutor_correct_sound(self) -> None:
        """Browse for tutor correct-key sound."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Correct Key Sound",
            self._tutor_correct_sound or "",
            "WAV Files (*.wav);;All Files (*)",
        )
        if path:
            self._tutor_correct_sound = path
            self._tutor_correct_sound_label.setText(path)

    def _browse_tutor_incorrect_sound(self) -> None:
        """Browse for tutor incorrect-key sound."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Incorrect Key Sound",
            self._tutor_incorrect_sound or "",
            "WAV Files (*.wav);;All Files (*)",
        )
        if path:
            self._tutor_incorrect_sound = path
            self._tutor_incorrect_sound_label.setText(path)

    def _refresh_language_sound_bindings_table(self) -> None:
        """Refresh the language sound binding table."""
        self._language_sound_table.setRowCount(len(self._language_sound_bindings))
        for row, binding in enumerate(self._language_sound_bindings):
            self._language_sound_table.setItem(row, 0, QTableWidgetItem(binding.language))
            self._language_sound_table.setItem(row, 1, QTableWidgetItem(binding.sound_path))
        has_items = bool(self._language_sound_bindings)
        self._language_sound_edit_btn.setEnabled(has_items)
        self._language_sound_delete_btn.setEnabled(has_items)

    def _add_language_sound_binding(self) -> None:
        """Add a new language sound binding."""
        dialog = LanguageSoundBindingDialog(self)
        if dialog.exec():
            binding = dialog.get_binding()
            self._language_sound_bindings = [
                existing
                for existing in self._language_sound_bindings
                if existing.language.lower() != binding.language.lower()
            ]
            self._language_sound_bindings.append(binding)
            self._language_sound_bindings.sort(key=lambda item: (item.language.lower(), item.sound_path.lower()))
            self._refresh_language_sound_bindings_table()

    def _selected_language_sound_row(self) -> int:
        """Return the selected language sound binding row."""
        row = self._language_sound_table.currentRow()
        if row < 0 or row >= len(self._language_sound_bindings):
            return -1
        return row

    def _edit_language_sound_binding(self) -> None:
        """Edit the selected language sound binding."""
        row = self._selected_language_sound_row()
        if row < 0:
            return
        dialog = LanguageSoundBindingDialog(self, binding=self._language_sound_bindings[row])
        if dialog.exec():
            binding = dialog.get_binding()
            self._language_sound_bindings[row] = binding
            deduped: list[LanguageSoundBinding] = []
            for item in self._language_sound_bindings:
                deduped = [
                    existing
                    for existing in deduped
                    if existing.language.lower() != item.language.lower()
                ]
                deduped.append(item)
            self._language_sound_bindings = sorted(
                deduped,
                key=lambda item: (item.language.lower(), item.sound_path.lower()),
            )
            self._refresh_language_sound_bindings_table()

    def _delete_language_sound_binding(self) -> None:
        """Delete the selected language sound binding."""
        row = self._selected_language_sound_row()
        if row < 0:
            return
        del self._language_sound_bindings[row]
        self._refresh_language_sound_bindings_table()

    def _apply_settings(self) -> None:
        """Persist settings and notify owner."""
        for i, btn in enumerate(self._layer_color_buttons):
            self._config.set_layer_color(i, btn.get_color())

        self._config.set_tap_color(self._tap_color_btn.get_color())
        self._config.set_hold_color(self._hold_color_btn.get_color())
        self._config.set_active_layer_text_color(self._active_layer_text_color_btn.get_color())
        self._config.set_label_font_scale_percent(self._label_font_scale_spin.value())
        self._config.set_grid_label_font_scale_percent(self._grid_label_font_scale_spin.value())
        self._config.set_tap_fill_color(self._tap_fill_color_btn.get_color())
        self._config.set_hold_fill_color(self._hold_fill_color_btn.get_color())
        self._config.set_tap_border_color(self._tap_border_color_btn.get_color())
        self._config.set_hold_border_color(self._hold_border_color_btn.get_color())
        self._config.set_tap_border_width(self._tap_border_width_spin.value())
        self._config.set_hold_border_width(self._hold_border_width_spin.value())
        self._config.set_grid_line_color(self._grid_line_color_btn.get_color())
        self._config.set_grid_line_width(self._grid_line_width_spin.value())
        self._config.set_hid_border_color(self._hid_border_color_btn.get_color())
        self._config.set_hid_border_width(self._hid_border_width_spin.value())
        self._config.set_hid_border_inset(self._hid_border_inset_spin.value())
        self._config.set_hid_border_style(str(self._hid_border_style_combo.currentData()))
        self._config.set_tutor_show_hold_labels(self._tutor_show_hold_labels_cb.isChecked())
        self._config.set_tutor_show_movement_arrows(self._tutor_movement_arrows_cb.isChecked())
        for name, button in self._finger_color_buttons.items():
            self._config.set_finger_color(name, button.get_color())
        self._config.set_tutor_click_sounds_enabled(self._tutor_click_sounds_cb.isChecked())
        self._config.set_tutor_correct_sound(self._tutor_correct_sound)
        self._config.set_tutor_incorrect_sound(self._tutor_incorrect_sound)
        self._config.set_hid_highlight_color(self._hid_highlight_color_btn.get_color())
        self._config.set_hid_highlight_duration_ms(self._hid_highlight_duration_spin.value())
        self._config.set_language_sound_bindings(self._language_sound_bindings)
        self._tutor_scheme_widget.save()

        if self._on_apply is not None:
            self._on_apply()

    def _apply_only(self) -> None:
        """Apply settings without closing dialog."""
        try:
            self._apply_settings()
        except Exception as exc:
            QMessageBox.critical(self, "Settings Error", str(exc))

    def _save_and_accept(self) -> None:
        """Save settings and close dialog."""
        try:
            self._apply_settings()
        except Exception as exc:
            QMessageBox.critical(self, "Settings Error", str(exc))
            return
        self.accept()

    def get_layer_colors(self) -> list[str]:
        """Get all layer colors."""
        return [btn.get_color() for btn in self._layer_color_buttons]

    def get_tap_color(self) -> str:
        """Get tap text color."""
        return self._tap_color_btn.get_color()

    def get_hold_color(self) -> str:
        """Get hold text color."""
        return self._hold_color_btn.get_color()

    def get_tutor_show_hold_labels(self) -> bool:
        """Return whether tutor should show hold labels."""
        return self._tutor_show_hold_labels_cb.isChecked()

    def get_hid_highlight_color(self) -> str:
        """Get physical keyboard highlight color."""
        return self._hid_highlight_color_btn.get_color()

    def get_hid_highlight_duration_ms(self) -> int:
        """Get physical keyboard highlight duration."""
        return self._hid_highlight_duration_spin.value()
