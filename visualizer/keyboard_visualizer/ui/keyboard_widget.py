"""Keyboard visualization widget."""

from typing import Optional, TYPE_CHECKING

from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QWidget, QGraphicsLineItem, QGraphicsPolygonItem
from PySide6.QtGui import QColor, QResizeEvent, QPen, QBrush, QPolygonF
from PySide6.QtCore import Qt, QTimer, Signal, QPointF

from ..models import KeyGeometry, KeyDefinition, Keymap
from ..models.layout import Layout
from ..parsers import QMKKeycodeParser, KeyLabels
from .key_item import KeyItem
from .hand_overlay import (
    Finger,
    get_finger_color,
    CHARYBDIS_NANO_FINGER_MAP,
    CHARYBDIS_NANO_HOME_POSITION_MAP,
)
from ..utils.tutor_hand_schemes import (
    TutorKeySchemeAssignments,
    TutorHandSchemeSet,
    get_assigned_scheme_name,
    get_default_scheme_name,
    is_left_hand_key,
)

if TYPE_CHECKING:
    from ..input.keyboard_layout import KeyboardLayoutDetector
    from ..input.keyboard_hid import KeyboardHID


class KeyboardWidget(QGraphicsView):
    """
    Custom widget for rendering the keyboard using QGraphicsScene.

    Features:
    - Automatic scaling to fit widget size
    - Key press/release highlighting
    - Single-layer and multi-layer display modes
    - Hover tooltips showing full keycode
    - HID RGB control when clicking keys
    """

    # Signal emitted when a key is clicked (for HID control)
    key_clicked = Signal(int)  # key_index

    # Pixels per key unit (1u)
    DEFAULT_SCALE = 60.0

    # Minimum time a key stays highlighted (ms)
    MIN_HIGHLIGHT_MS = 100

    # Time before switching to hold mode (ms) - mimics QMK tapping term
    TAPPING_TERM_MS = 200

    # Default layer colors
    DEFAULT_LAYER_COLORS = [
        "#4fc3f7",  # Layer 0 - light blue
        "#81c784",  # Layer 1 - green
        "#ffb74d",  # Layer 2 - orange
        "#ba68c8",  # Layer 3 - purple
        "#e57373",  # Layer 4 - red
        "#64b5f6",  # Layer 5 - blue
        "#fff176",  # Layer 6 - yellow
        "#4db6ac",  # Layer 7 - teal
        "#f06292",  # Layer 8 - pink
        "#aed581",  # Layer 9 - light green
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._scene = QGraphicsScene()
        self.setScene(self._scene)

        # Background
        self._scene.setBackgroundBrush(QColor("#1e1e1e"))

        # Key items indexed by their position
        self._key_items: dict[int, KeyItem] = {}

        # Current scale factor
        self._scale = self.DEFAULT_SCALE

        # Data
        self._layout: Layout | None = None
        self._keymap: Keymap | None = None

        # Display mode: single layer index or list of layer indices
        self._display_layers: list[int] = [0]

        # Layer colors (can be customized)
        self._layer_colors: list[str] = self.DEFAULT_LAYER_COLORS.copy()

        # Text colors
        self._tap_color = QColor("#ffffff")
        self._hold_color = QColor("#ffb74d")

        # Parser for keycodes
        self._parser = QMKKeycodeParser()

        # Key definitions (combined keymap + layout)
        self._key_definitions: list[KeyDefinition] = []

        # Timers for minimum highlight duration
        self._highlight_timers: dict[int, QTimer] = {}

        # Timers for detecting hold (tapping term)
        self._hold_timers: dict[int, QTimer] = {}

        # Key indices that have hold functionality (MT/LT)
        self._tap_hold_keys: set[int] = set()

        # OS keyboard layout mode
        self._os_layout_mode = False
        self._layout_detector: Optional["KeyboardLayoutDetector"] = None
        self._layout_hkl: Optional[int] = None

        # Hide empty keys (KC_NO) option
        self._hide_empty_keys = True

        # Shift mode - when True, show shifted characters
        self._shift_mode = False
        self._caps_lock_mode = False
        self._show_hold_labels = True

        # HID controller for RGB control
        self._hid_controller: Optional["KeyboardHID"] = None
        self._hid_click_enabled = False

        # Tutor mode - shows hands and finger hints
        self._tutor_mode = False
        self._finger_map: dict[int, Finger] = CHARYBDIS_NANO_FINGER_MAP.copy()
        self._finger_home_map: dict[Finger, int] = CHARYBDIS_NANO_HOME_POSITION_MAP.copy()
        self._finger_palette: dict[Finger, QColor] = {
            finger: get_finger_color(finger) for finger in Finger
        }
        self._tutor_hand_schemes: TutorHandSchemeSet | None = None
        self._tutor_key_scheme_assignments = TutorKeySchemeAssignments(schemes={}, overrides={})
        self._highlighted_key_index: Optional[int] = None
        self._show_finger_movement_arrows = False
        self._finger_motion_items: list[QGraphicsLineItem | QGraphicsPolygonItem] = []
        self._tutor_feedback_timers: dict[int, QTimer] = {}
        self._debug_log_callback = None

        # View settings
        from PySide6.QtGui import QPainter
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        # Fix rendering artifacts - use full viewport updates
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

        # Optional transform lock, used when another view should mirror this one.
        self._transform_locked = False
        self._locked_transform = None

    def set_layout(self, layout: Layout) -> None:
        """Set the keyboard layout and create key items."""
        self._layout = layout
        self._rebuild_keys()

    def set_keymap(self, keymap: Keymap) -> None:
        """Set the keymap and update key labels."""
        self._keymap = keymap
        self._rebuild_key_definitions()
        self._update_labels()

    def set_layer(self, layer_index: int) -> None:
        """Switch to displaying a single layer."""
        self._display_layers = [layer_index]
        self._update_labels()

    def set_layers(self, layer_indices: list[int]) -> None:
        """Set multiple layers to display (grid mode)."""
        self._display_layers = layer_indices if layer_indices else [0]
        self._update_labels()

    def set_layer_colors(self, colors: list[str]) -> None:
        """Set custom layer colors."""
        self._layer_colors = colors

    def set_text_colors(self, tap_color: str, hold_color: str) -> None:
        """Set text colors for tap and hold."""
        self._tap_color = QColor(tap_color)
        self._hold_color = QColor(hold_color)
        # Update existing key items
        for item in self._key_items.values():
            item.set_text_colors(self._tap_color, self._hold_color)

    def set_show_hold_labels(self, enabled: bool) -> None:
        """Show or hide hold labels such as LT/MT overlays."""
        self._show_hold_labels = enabled
        self._update_labels()

    def set_os_layout_mode(
        self,
        enabled: bool,
        layout_detector: Optional["KeyboardLayoutDetector"] = None,
        hkl: Optional[int] = None
    ) -> None:
        """Enable or disable OS keyboard layout mode.

        When enabled, key labels show characters based on the current OS
        keyboard layout instead of QMK keycode names.
        """
        self._os_layout_mode = enabled
        self._layout_detector = layout_detector
        self._layout_hkl = hkl
        # Rebuild labels with new mode
        self._rebuild_key_definitions()
        self._update_labels()

    def highlight_key(self, key_index: int, pressed: bool, hold_mode: bool = False) -> None:
        """Highlight/unhighlight a key by index with minimum duration.

        Args:
            key_index: Index of the key to highlight
            pressed: Whether key is pressed (True) or released (False)
            hold_mode: True if this is a hold action (modifier sent), False for tap
        """
        if key_index not in self._key_items:
            return

        if pressed:
            # Cancel any pending release timer
            if key_index in self._highlight_timers:
                self._highlight_timers[key_index].stop()
                del self._highlight_timers[key_index]

            # Start with tap mode (blue), unless already known to be hold
            self._key_items[key_index].set_pressed(True, hold_mode)

            # If not already in hold mode and key has hold functionality, start timer
            if not hold_mode and key_index in self._tap_hold_keys:
                # Cancel existing hold timer if any
                if key_index in self._hold_timers:
                    self._hold_timers[key_index].stop()

                # Start new hold timer
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(lambda idx=key_index: self._switch_to_hold_mode(idx))
                self._hold_timers[key_index] = timer
                timer.start(self.TAPPING_TERM_MS)
        else:
            # Cancel hold timer on release
            if key_index in self._hold_timers:
                self._hold_timers[key_index].stop()
                del self._hold_timers[key_index]

            # Delay the release to ensure minimum visibility
            if key_index not in self._highlight_timers:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(lambda idx=key_index: self._do_release(idx))
                self._highlight_timers[key_index] = timer
            self._highlight_timers[key_index].start(self.MIN_HIGHLIGHT_MS)

    def _switch_to_hold_mode(self, key_index: int) -> None:
        """Switch a pressed key to hold mode (orange) after tapping term."""
        self._debug_log(f"KeyboardWidget.switch_to_hold_mode idx={key_index}")
        if key_index in self._key_items:
            item = self._key_items[key_index]
            if item._pressed:  # Only if still pressed
                item.set_pressed(True, hold_mode=True)
        if key_index in self._hold_timers:
            del self._hold_timers[key_index]

    def _do_release(self, key_index: int) -> None:
        """Actually release the key highlight after timer."""
        if key_index in self._key_items:
            self._key_items[key_index].set_pressed(False)
        if key_index in self._highlight_timers:
            del self._highlight_timers[key_index]

    def clear_all_highlights(self) -> None:
        """Clear all key highlights."""
        # Stop all pending release timers
        for timer in self._highlight_timers.values():
            timer.stop()
        self._highlight_timers.clear()
        # Stop all pending hold timers
        for timer in self._hold_timers.values():
            timer.stop()
        self._hold_timers.clear()
        # Clear all highlights
        for item in self._key_items.values():
            item.set_pressed(False)
            item.set_hid_active(False)
            item.set_tutor_feedback(None)
        for timer in self._tutor_feedback_timers.values():
            timer.stop()
        self._tutor_feedback_timers.clear()

    def set_hid_key_active(self, key_index: int, active: bool) -> None:
        """Show or hide a firmware/HID contour on one key."""
        if key_index not in self._key_items:
            return
        self._key_items[key_index].set_hid_active(active)

    def set_debug_log_callback(self, callback) -> None:
        """Register a debug log callback used for key/hold tracing."""
        self._debug_log_callback = callback

    def _debug_log(self, message: str) -> None:
        if self._debug_log_callback is not None:
            self._debug_log_callback(message)

    def clear_hid_highlights(self) -> None:
        """Clear all firmware/HID contours without touching normal highlights."""
        for item in self._key_items.values():
            item.set_hid_active(False)

    def show_tutor_key_feedback(self, key_index: int, correct: bool, duration_ms: int = 220) -> None:
        """Flash a tutor key with success/error feedback."""
        if key_index not in self._key_items:
            return

        if key_index in self._tutor_feedback_timers:
            self._tutor_feedback_timers[key_index].stop()

        self._key_items[key_index].set_tutor_feedback("correct" if correct else "error")

        timer = self._tutor_feedback_timers.get(key_index)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda idx=key_index: self._clear_tutor_key_feedback(idx))
            self._tutor_feedback_timers[key_index] = timer
        timer.start(duration_ms)

    def _clear_tutor_key_feedback(self, key_index: int) -> None:
        """Clear transient tutor feedback from one key."""
        if key_index in self._key_items:
            self._key_items[key_index].set_tutor_feedback(None)
        if key_index in self._tutor_feedback_timers:
            del self._tutor_feedback_timers[key_index]

    def _rebuild_keys(self) -> None:
        """Rebuild all key items from layout."""
        # Clear existing
        self._scene.clear()
        self._key_items.clear()

        if not self._layout:
            return

        # Create key items (skip fake/placeholder keys)
        for index, key_geo in enumerate(self._layout.keys):
            if key_geo.fake:
                continue  # Skip placeholder keys (KC_NO positions)
            item = KeyItem(index, key_geo, self._scale)
            self._scene.addItem(item)
            self._key_items[index] = item

        # Update click callbacks if HID mode is enabled
        self._update_click_callbacks()

        # Fit view to scene
        self._fit_to_view()

        # Rebuild definitions if we have a keymap
        if self._keymap:
            self._rebuild_key_definitions()
            self._update_labels()

    def _rebuild_key_definitions(self) -> None:
        """Rebuild key definitions combining layout and keymap."""
        self._key_definitions.clear()
        self._tap_hold_keys.clear()

        if not self._layout or not self._keymap:
            return

        for index, key_geo in enumerate(self._layout.keys):
            keycodes = []
            parsed_labels = []
            has_hold = False

            for layer in self._keymap.layers:
                if index < len(layer):
                    keycode = layer[index]
                    keycodes.append(keycode)
                    # Use layout-aware parsing if OS layout mode is enabled
                    if self._os_layout_mode and self._layout_detector:
                        labels = self._parser.parse_with_layout(
                            keycode, self._layout_detector, self._layout_hkl,
                            shift=self._shift_mode,
                            caps_lock=self._caps_lock_mode,
                        )
                    else:
                        labels = self._parser.parse_full(keycode)
                    parsed_labels.append(labels)
                    # Check if this key has hold functionality
                    if labels.hold:
                        has_hold = True
                else:
                    keycodes.append("")
                    from ..parsers import KeyLabels
                    parsed_labels.append(KeyLabels(tap="", hold="", raw=""))

            # Track keys with hold functionality (MT/LT)
            if has_hold:
                self._tap_hold_keys.add(index)

            definition = KeyDefinition(
                index=index,
                geometry=key_geo,
                keycodes=keycodes,
                parsed_labels=parsed_labels,
            )
            self._key_definitions.append(definition)

        # Hide empty keys if option is enabled
        self._update_empty_keys_visibility()

    def set_hide_empty_keys(self, hide: bool) -> None:
        """Set whether to hide keys that are KC_NO on all layers."""
        self._hide_empty_keys = hide
        self._update_empty_keys_visibility()

    def set_shift_mode(self, shift_pressed: bool) -> None:
        """Set shift mode - when enabled, show shifted characters on keys.

        Args:
            shift_pressed: True if Shift is currently held
        """
        if self._shift_mode != shift_pressed:
            self._shift_mode = shift_pressed
            # Only update if OS layout mode is enabled (otherwise we use QMK labels)
            if self._os_layout_mode:
                self._rebuild_key_definitions()
                self._update_labels()

    def set_caps_lock_mode(self, caps_lock_on: bool) -> None:
        """Set Caps Lock mode for OS-layout-aware labels."""
        if self._caps_lock_mode != caps_lock_on:
            self._caps_lock_mode = caps_lock_on
            if self._os_layout_mode:
                self._rebuild_key_definitions()
                self._update_labels()

    def _update_empty_keys_visibility(self) -> None:
        """Update visibility of empty (KC_NO) keys."""
        if not self._key_definitions:
            return

        for defn in self._key_definitions:
            if defn.index not in self._key_items:
                continue

            item = self._key_items[defn.index]

            if self._hide_empty_keys:
                # Check if key is KC_NO on all layers
                is_empty = all(
                    kc in ("KC_NO", "") for kc in defn.keycodes
                )
                item.setVisible(not is_empty)
            else:
                item.setVisible(True)

        # Refresh the view
        self._fit_to_view()

    def _update_labels(self) -> None:
        """Update all key labels for current display mode."""
        is_multi_layer = len(self._display_layers) > 1

        for defn in self._key_definitions:
            if defn.index not in self._key_items:
                continue

            item = self._key_items[defn.index]

            # Set text colors
            item.set_text_colors(self._tap_color, self._hold_color)

            if is_multi_layer:
                # Multi-layer grid mode
                layer_data = []
                for layer_idx in self._display_layers:
                    labels = self._display_label(defn.get_labels(layer_idx))
                    if labels:
                        color_idx = layer_idx % len(self._layer_colors)
                        bg_color = QColor(self._layer_colors[color_idx])
                        layer_data.append((layer_idx, labels, bg_color))

                item.set_multi_layer_labels(layer_data)
            else:
                # Single-layer mode
                layer_idx = self._display_layers[0]
                labels = self._display_label(defn.get_labels(layer_idx))
                if labels:
                    item.set_labels(labels)

    def _display_label(self, labels: KeyLabels | None) -> KeyLabels | None:
        """Return labels adjusted for current display options."""
        if labels is None or self._show_hold_labels:
            return labels
        return KeyLabels(tap=labels.tap, hold="", raw=labels.raw)

    def _fit_to_view(self) -> None:
        """Fit the scene to the view with some padding."""
        if self._transform_locked and self._locked_transform is not None:
            self.setTransform(self._locked_transform)
            return

        if self._scene.items():
            # Add some padding
            rect = self._scene.itemsBoundingRect()
            rect.adjust(-20, -20, 20, 20)
            self.fitInView(rect, Qt.KeepAspectRatio)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Handle resize to maintain fit."""
        super().resizeEvent(event)
        self._fit_to_view()

    def lock_transform(self) -> None:
        """Freeze current transform."""
        self._locked_transform = self.transform()
        self._transform_locked = True

    def unlock_transform(self) -> None:
        """Allow view to fit itself again."""
        self._transform_locked = False
        self._locked_transform = None
        self._fit_to_view()

    def set_locked_transform(self, transform) -> None:
        """Lock the view to an externally provided transform."""
        self._locked_transform = transform
        self._transform_locked = True
        self.setTransform(transform)

    def set_hid_controller(self, hid_controller: Optional["KeyboardHID"]) -> None:
        """Set the HID controller for RGB control."""
        self._hid_controller = hid_controller

    def set_hid_click_enabled(self, enabled: bool) -> None:
        """Enable or disable HID click mode.

        When enabled, clicking on a key will send RGB command to physical keyboard.
        """
        self._hid_click_enabled = enabled
        self._update_click_callbacks()

    def _update_click_callbacks(self) -> None:
        """Update click callbacks on all key items."""
        callback = self._on_key_clicked if self._hid_click_enabled else None
        for item in self._key_items.values():
            item.set_click_callback(callback)

    def _on_key_clicked(self, key_index: int) -> None:
        """Handle key click for HID highlighting."""
        # Emit signal for external handlers
        self.key_clicked.emit(key_index)

        # Send to HID controller if connected
        if self._hid_controller and self._hid_controller.is_connected():
            self._hid_controller.highlight_key(key_index)

    def get_key_count(self) -> int:
        """Return the number of keys in the layout."""
        return len(self._key_items)

    def get_key_descriptions_for_layer(self, layer_index: int) -> list[str]:
        """Return human-readable key descriptions for a specific layer."""
        descriptions: list[str] = []
        for defn in self._key_definitions:
            labels = defn.get_labels(layer_index)
            if labels:
                label = labels.tap or labels.raw or "Unassigned"
            else:
                keycode = defn.get_keycode(layer_index)
                label = keycode or "Unassigned"
            descriptions.append(f"{defn.index}: {label}")
        return descriptions

    # ============== Tutor Mode ==============

    def set_tutor_mode(self, enabled: bool) -> None:
        """Enable or disable typing tutor mode.

        When enabled:
        - Shows hand silhouettes below the keyboard
        - Highlights keys with finger colors
        - Can draw lines from fingers to target keys
        """
        if self._tutor_mode == enabled:
            return

        self._tutor_mode = enabled

        if enabled:
            self._highlighted_key_index = None
        else:
            self._highlighted_key_index = None

        # Update key colors based on mode
        self._update_key_finger_colors()

    def set_finger_map(self, finger_map: dict[int, Finger]) -> None:
        """Set custom finger-to-key mapping."""
        self._finger_map = finger_map
        if self._tutor_mode:
            self._update_key_finger_colors()

    def set_finger_home_map(self, finger_home_map: dict[Finger, int]) -> None:
        """Set home/rest positions for tutor finger indicators."""
        self._finger_home_map = finger_home_map
        if self._tutor_mode:
            self._update_key_finger_colors()

    def set_finger_palette(self, palette: dict[Finger, QColor]) -> None:
        """Set tutor finger colors."""
        self._finger_palette = palette
        if self._tutor_mode:
            self._update_key_finger_colors()

    def set_tutor_scheme_data(
        self,
        schemes: TutorHandSchemeSet | None,
        assignments: TutorKeySchemeAssignments,
    ) -> None:
        """Set tutor home-position schemes and per-key assignments."""
        self._tutor_hand_schemes = schemes
        self._tutor_key_scheme_assignments = assignments
        if self._tutor_mode:
            self._update_key_finger_colors()

    def _update_key_finger_colors(self) -> None:
        """Update key colors based on finger assignments."""
        active_finger = self._resolve_active_finger(self._highlighted_key_index)
        indicators: dict[int, tuple[QColor, bool]] = {}
        self._clear_finger_motion_items()
        if self._tutor_mode:
            for finger, home_key_index in self._get_effective_home_positions().items():
                if home_key_index not in self._key_items:
                    continue
                color = self._finger_palette.get(finger, get_finger_color(finger))
                is_active = finger == active_finger
                target_key_index = (
                    self._highlighted_key_index
                    if is_active and self._highlighted_key_index in self._key_items
                    else home_key_index
                )
                existing = indicators.get(target_key_index)
                # If two fingers land on one key in preview, keep the active one visible.
                if existing is None or is_active or not existing[1]:
                    indicators[target_key_index] = (color, is_active)

        for key_index, item in self._key_items.items():
            indicator = indicators.get(key_index)
            if indicator is None:
                item.set_finger_color(None)
                item.set_finger_indicator_active(False)
            else:
                color, active = indicator
                item.set_finger_color(color)
                item.set_finger_indicator_active(active)
        self._update_finger_motion_arrows(active_finger)

    def show_finger_hint(self, key_index: int) -> None:
        """Show which finger should press a specific key."""
        if not self._tutor_mode:
            return
        self._highlighted_key_index = key_index if key_index in self._key_items else None
        self._update_key_finger_colors()

    def hide_finger_hints(self) -> None:
        """Hide the active finger hint."""
        self._highlighted_key_index = None
        self._update_key_finger_colors()

    def set_show_finger_movement_arrows(self, enabled: bool) -> None:
        """Enable or disable tutor movement arrows."""
        if self._show_finger_movement_arrows != enabled:
            self._show_finger_movement_arrows = enabled
            self._update_key_finger_colors()

    def _get_key_center(self, key_index: int):
        """Return scene center of a key if available."""
        item = self._key_items.get(key_index)
        if item is None:
            return None
        return item.mapToScene(item.rect().center())

    def _get_scheme_home_positions(self, scheme_name: str) -> dict[Finger, int]:
        """Return home positions for a configured tutor scheme."""
        if not self._tutor_hand_schemes:
            return {}
        scheme = self._tutor_hand_schemes.schemes.get(scheme_name)
        if not scheme:
            return {}
        home_positions: dict[Finger, int] = {}
        for finger_name, key_index in scheme.home_positions.items():
            try:
                home_positions[Finger[finger_name]] = key_index
            except KeyError:
                continue
        return home_positions

    def _get_effective_home_positions(self) -> dict[Finger, int]:
        """Return the combined left/right home positions for current tutor state."""
        if not self._tutor_hand_schemes:
            return self._finger_home_map.copy()

        left_scheme_name = get_default_scheme_name(self._tutor_hand_schemes, "left")
        right_scheme_name = get_default_scheme_name(self._tutor_hand_schemes, "right")

        if self._highlighted_key_index is not None:
            if is_left_hand_key(self._highlighted_key_index):
                left_scheme_name = get_assigned_scheme_name(
                    self._highlighted_key_index,
                    self._tutor_hand_schemes,
                    self._tutor_key_scheme_assignments,
                )
            else:
                right_scheme_name = get_assigned_scheme_name(
                    self._highlighted_key_index,
                    self._tutor_hand_schemes,
                    self._tutor_key_scheme_assignments,
                )

        combined: dict[Finger, int] = {}
        combined.update(self._get_scheme_home_positions(left_scheme_name))
        combined.update(self._get_scheme_home_positions(right_scheme_name))
        if self._highlighted_key_index is not None:
            raw_overrides = self._tutor_key_scheme_assignments.overrides.get(self._highlighted_key_index, {})
            for finger_name, key_index in raw_overrides.items():
                try:
                    combined[Finger[finger_name]] = key_index
                except KeyError:
                    continue
        return combined

    def _resolve_active_finger(self, key_index: Optional[int]) -> Optional[Finger]:
        """Resolve which finger should be shown as active for the target key."""
        if key_index is None:
            return None

        effective_positions = self._get_effective_home_positions()

        # If a finger is already placed on the target key by the current scheme/override,
        # that finger should be treated as the pressing finger.
        for finger, home_key_index in effective_positions.items():
            if home_key_index == key_index:
                return finger

        mapped_finger = self._finger_map.get(key_index)
        if not self._tutor_hand_schemes:
            return mapped_finger

        scheme_name = get_assigned_scheme_name(
            key_index,
            self._tutor_hand_schemes,
            self._tutor_key_scheme_assignments,
        )
        candidate_map = self._get_scheme_home_positions(scheme_name)
        if not candidate_map:
            return mapped_finger

        target_center = self._get_key_center(key_index)
        if target_center is None:
            return next(iter(candidate_map.keys()), None)

        best_finger: Optional[Finger] = None
        best_distance: float | None = None
        for finger, home_key_index in candidate_map.items():
            home_center = self._get_key_center(home_key_index)
            if home_center is None:
                continue
            dx = target_center.x() - home_center.x()
            dy = target_center.y() - home_center.y()
            distance = dx * dx + dy * dy
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_finger = finger

        return best_finger or next(iter(candidate_map.keys()), None)

    def _clear_finger_motion_items(self) -> None:
        """Remove any existing finger motion arrows from the scene."""
        while self._finger_motion_items:
            item = self._finger_motion_items.pop()
            self._scene.removeItem(item)

    def _update_finger_motion_arrows(self, active_finger: Optional[Finger]) -> None:
        """Draw movement arrows for all fingers that moved from scheme home positions."""
        if (
            not self._tutor_mode
            or not self._show_finger_movement_arrows
            or self._highlighted_key_index is None
        ):
            return

        left_scheme_name = get_default_scheme_name(self._tutor_hand_schemes, "left") if self._tutor_hand_schemes else ""
        right_scheme_name = get_default_scheme_name(self._tutor_hand_schemes, "right") if self._tutor_hand_schemes else ""
        if self._highlighted_key_index is not None and self._tutor_hand_schemes:
            if is_left_hand_key(self._highlighted_key_index):
                left_scheme_name = get_assigned_scheme_name(
                    self._highlighted_key_index,
                    self._tutor_hand_schemes,
                    self._tutor_key_scheme_assignments,
                )
            else:
                right_scheme_name = get_assigned_scheme_name(
                    self._highlighted_key_index,
                    self._tutor_hand_schemes,
                    self._tutor_key_scheme_assignments,
                )

        base_positions: dict[Finger, int] = {}
        base_positions.update(self._get_scheme_home_positions(left_scheme_name))
        base_positions.update(self._get_scheme_home_positions(right_scheme_name))

        display_positions = self._get_effective_home_positions()
        if active_finger is not None and self._highlighted_key_index in self._key_items:
            display_positions = display_positions.copy()
            display_positions[active_finger] = self._highlighted_key_index

        for finger, start_key_index in base_positions.items():
            end_key_index = display_positions.get(finger)
            if end_key_index is None or start_key_index == end_key_index:
                continue
            self._add_finger_motion_arrow(finger, start_key_index, end_key_index)

    def _add_finger_motion_arrow(self, finger: Finger, start_key_index: int, end_key_index: int) -> None:
        """Draw one arrow from a finger's base position to its current position."""
        start = self._get_key_center(start_key_index)
        end = self._get_key_center(end_key_index)
        if start is None or end is None:
            return

        color = self._finger_palette.get(finger, get_finger_color(finger))
        arrow_color = QColor(color)
        arrow_color = arrow_color.lighter(135)
        arrow_color.setAlpha(120)
        pen = QPen(arrow_color, 1.5)
        pen.setStyle(Qt.PenStyle.DashLine)

        line = QGraphicsLineItem(start.x(), start.y(), end.x(), end.y())
        line.setPen(pen)
        line.setZValue(20)
        self._scene.addItem(line)
        self._finger_motion_items.append(line)

        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = (dx * dx + dy * dy) ** 0.5
        if length < 1:
            return

        ux = dx / length
        uy = dy / length
        arrow_len = 10.0
        arrow_width = 5.5
        tip = QPointF(end.x(), end.y())
        base = QPointF(end.x() - ux * arrow_len, end.y() - uy * arrow_len)
        left = QPointF(base.x() - uy * arrow_width, base.y() + ux * arrow_width)
        right = QPointF(base.x() + uy * arrow_width, base.y() - ux * arrow_width)
        head = QGraphicsPolygonItem(QPolygonF([tip, left, right]))
        head.setPen(pen)
        head_fill = QColor(arrow_color)
        head_fill.setAlpha(90)
        head.setBrush(QBrush(head_fill))
        head.setZValue(21)
        self._scene.addItem(head)
        self._finger_motion_items.append(head)

    def is_tutor_mode(self) -> bool:
        """Return whether tutor mode is enabled."""
        return self._tutor_mode

    def set_transparent_background(self, transparent: bool = True) -> None:
        """Set whether the scene background should be transparent.

        Args:
            transparent: If True, background is fully transparent.
                        If False, background is opaque dark color.
        """
        if transparent:
            self._scene.setBackgroundBrush(Qt.transparent)
            self.setStyleSheet("background: transparent;")
            self.viewport().setAutoFillBackground(False)
            self.setFrameShape(self.Shape.NoFrame)
        else:
            self._scene.setBackgroundBrush(QColor("#1e1e1e"))
            self.setStyleSheet("")
            self.viewport().setAutoFillBackground(True)
