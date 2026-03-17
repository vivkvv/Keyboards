"""Main window for the reaction-diffusion keyboard simulator."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .config_io import load_scene, save_scene
from .hid_bridge import KeyboardLedBridge
from .layout_loader import load_layout
from .models import KeyCell
from .reaction_diffusion import ReactionDiffusion, RDState
from .widgets import KeyboardRDWidget


class MainWindow(QMainWindow):
    """Main GUI window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Keyboard Reaction-Diffusion")
        self.resize(1200, 720)

        self._layout_name = ""
        self._layout_path = ""
        self._cells: list[KeyCell] = []
        self._states: list[RDState] = []
        self._neighbors: list[list[int]] = []
        self._model = ReactionDiffusion()
        self._led_bridge = KeyboardLedBridge()
        self._output_to_keyboard = False
        self._frame_counter = 0

        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._tick)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        splitter = QSplitter()
        layout.addWidget(splitter)

        self._field_widget = KeyboardRDWidget()
        splitter.addWidget(self._field_widget)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([820, 340])

        self._layout_label = QLabel("Layout: not loaded")
        right_layout.addWidget(self._layout_label)

        self._load_layout_btn = QPushButton("Load Layout JSON")
        self._load_layout_btn.clicked.connect(self._load_layout)
        right_layout.addWidget(self._load_layout_btn)

        self._save_scene_btn = QPushButton("Save Scene")
        self._save_scene_btn.clicked.connect(self._save_scene)
        right_layout.addWidget(self._save_scene_btn)

        self._load_scene_btn = QPushButton("Load Scene")
        self._load_scene_btn.clicked.connect(self._load_scene)
        right_layout.addWidget(self._load_scene_btn)

        self._hid_connect_btn = QPushButton("HID Connect")
        self._hid_connect_btn.setCheckable(True)
        self._hid_connect_btn.clicked.connect(self._toggle_hid)
        right_layout.addWidget(self._hid_connect_btn)

        self._output_cb = QCheckBox("Output to keyboard")
        self._output_cb.setEnabled(False)
        self._output_cb.toggled.connect(self._toggle_keyboard_output)
        right_layout.addWidget(self._output_cb)

        form = QFormLayout()
        right_layout.addLayout(form)

        self._radius_spin = QDoubleSpinBox()
        self._radius_spin.setRange(0.5, 5.0)
        self._radius_spin.setSingleStep(0.1)
        self._radius_spin.setDecimals(2)
        self._radius_spin.setValue(self._model.neighbor_radius)
        self._radius_spin.valueChanged.connect(self._on_radius_changed)
        form.addRow("Neighbor radius:", self._radius_spin)

        self._wrap_cb = QCheckBox("Toroidal wrap")
        self._wrap_cb.setChecked(self._model.wrap)
        self._wrap_cb.toggled.connect(self._on_wrap_toggled)
        form.addRow("Wrap mode:", self._wrap_cb)

        self._diff_a_spin = QDoubleSpinBox()
        self._diff_a_spin.setRange(0.0, 1.0)
        self._diff_a_spin.setSingleStep(0.01)
        self._diff_a_spin.setDecimals(3)
        self._diff_a_spin.setValue(self._model.diffusion_a)
        self._diff_a_spin.valueChanged.connect(self._on_diff_a_changed)
        form.addRow("Diffusion A:", self._diff_a_spin)

        self._diff_b_spin = QDoubleSpinBox()
        self._diff_b_spin.setRange(0.0, 1.0)
        self._diff_b_spin.setSingleStep(0.01)
        self._diff_b_spin.setDecimals(3)
        self._diff_b_spin.setValue(self._model.diffusion_b)
        self._diff_b_spin.valueChanged.connect(self._on_diff_b_changed)
        form.addRow("Diffusion B:", self._diff_b_spin)

        self._feed_spin = QDoubleSpinBox()
        self._feed_spin.setRange(0.0, 0.2)
        self._feed_spin.setSingleStep(0.001)
        self._feed_spin.setDecimals(4)
        self._feed_spin.setValue(self._model.feed)
        self._feed_spin.valueChanged.connect(self._on_feed_changed)
        form.addRow("Feed:", self._feed_spin)

        self._kill_spin = QDoubleSpinBox()
        self._kill_spin.setRange(0.0, 0.2)
        self._kill_spin.setSingleStep(0.001)
        self._kill_spin.setDecimals(4)
        self._kill_spin.setValue(self._model.kill)
        self._kill_spin.valueChanged.connect(self._on_kill_changed)
        form.addRow("Kill:", self._kill_spin)

        self._dt_spin = QDoubleSpinBox()
        self._dt_spin.setRange(0.1, 2.0)
        self._dt_spin.setSingleStep(0.05)
        self._dt_spin.setDecimals(2)
        self._dt_spin.setValue(self._model.dt)
        self._dt_spin.valueChanged.connect(self._on_dt_changed)
        form.addRow("Model dt:", self._dt_spin)

        self._noise_spin = QDoubleSpinBox()
        self._noise_spin.setRange(0.0, 0.2)
        self._noise_spin.setSingleStep(0.002)
        self._noise_spin.setDecimals(3)
        self._noise_spin.setValue(self._model.noise_rate)
        self._noise_spin.valueChanged.connect(self._on_noise_changed)
        form.addRow("Noise rate:", self._noise_spin)

        self._interval_spin = QDoubleSpinBox()
        self._interval_spin.setRange(20.0, 1000.0)
        self._interval_spin.setSingleStep(10.0)
        self._interval_spin.setDecimals(0)
        self._interval_spin.setValue(float(self._timer.interval()))
        self._interval_spin.valueChanged.connect(self._on_interval_changed)
        form.addRow("Step interval ms:", self._interval_spin)

        row = QHBoxLayout()
        right_layout.addLayout(row)
        self._randomize_btn = QPushButton("Randomize")
        self._randomize_btn.clicked.connect(self._randomize_states)
        row.addWidget(self._randomize_btn)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._clear_states)
        row.addWidget(self._clear_btn)

        row2 = QHBoxLayout()
        right_layout.addLayout(row2)
        self._start_btn = QPushButton("Start")
        self._start_btn.clicked.connect(self._toggle_running)
        row2.addWidget(self._start_btn)
        self._step_btn = QPushButton("Step")
        self._step_btn.clicked.connect(self._step_once)
        row2.addWidget(self._step_btn)

        self._status_label = QLabel("Ready")
        right_layout.addWidget(self._status_label)
        right_layout.addStretch()

        default_layout = Path(__file__).resolve().parents[2] / "charybdis_nano_40_visual_layout.json"
        if default_layout.exists():
            self._load_layout_from_path(default_layout)
            self._randomize_states()

    def _load_layout(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load Layout JSON", str(Path(self._layout_path).parent) if self._layout_path else "", "JSON Files (*.json);;All Files (*)")
        if path:
            self._load_layout_from_path(Path(path))
            self._randomize_states()

    def _load_layout_from_path(self, path: Path) -> None:
        self._layout_name, self._cells = load_layout(path)
        self._layout_path = str(path)
        self._neighbors = self._model.build_neighbors(self._cells)
        self._layout_label.setText(f"Layout: {self._layout_name}")

    def _save_scene(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Scene", str(Path(self._layout_path).with_suffix(".rd.json")) if self._layout_path else "", "JSON Files (*.json);;All Files (*)")
        if not path:
            return
        save_scene(
            path,
            self._layout_path,
            self._states,
            self._model.neighbor_radius,
            self._model.wrap,
            self._model.diffusion_a,
            self._model.diffusion_b,
            self._model.feed,
            self._model.kill,
            self._model.dt,
            self._model.noise_rate,
        )
        self._status_label.setText(f"Saved scene: {Path(path).name}")

    def _load_scene(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load Scene", str(Path(self._layout_path).parent) if self._layout_path else "", "JSON Files (*.json);;All Files (*)")
        if not path:
            return
        layout_path, states, radius, wrap, diff_a, diff_b, feed, kill, dt, noise_rate = load_scene(path)
        if layout_path and Path(layout_path).exists():
            self._load_layout_from_path(Path(layout_path))
        if radius is not None:
            self._model.neighbor_radius = radius
            self._radius_spin.setValue(radius)
        if wrap is not None:
            self._model.wrap = wrap
            self._wrap_cb.setChecked(wrap)
        if diff_a is not None:
            self._model.diffusion_a = diff_a
            self._diff_a_spin.setValue(diff_a)
        if diff_b is not None:
            self._model.diffusion_b = diff_b
            self._diff_b_spin.setValue(diff_b)
        if feed is not None:
            self._model.feed = feed
            self._feed_spin.setValue(feed)
        if kill is not None:
            self._model.kill = kill
            self._kill_spin.setValue(kill)
        if dt is not None:
            self._model.dt = dt
            self._dt_spin.setValue(dt)
        if noise_rate is not None:
            self._model.noise_rate = noise_rate
            self._noise_spin.setValue(noise_rate)
        self._neighbors = self._model.build_neighbors(self._cells)
        self._states = states[:len(self._cells)] + [(1.0, 0.0)] * max(0, len(self._cells) - len(states))
        self._refresh_view()
        self._status_label.setText(f"Loaded scene: {Path(path).name}")

    def _randomize_states(self) -> None:
        self._states = self._model.random_states(len(self._cells))
        self._refresh_view()

    def _clear_states(self) -> None:
        self._states = self._model.clear_states(len(self._cells))
        self._refresh_view()

    def _toggle_running(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._start_btn.setText("Start")
            self._status_label.setText("Paused")
        else:
            self._timer.start()
            self._start_btn.setText("Pause")
            self._status_label.setText("Running")

    def _toggle_hid(self, checked: bool) -> None:
        if checked:
            if self._led_bridge.connect():
                self._hid_connect_btn.setText("HID Connected")
                self._output_cb.setEnabled(True)
                self._status_label.setText("HID connected")
            else:
                self._hid_connect_btn.setChecked(False)
                reason = self._led_bridge.get_last_error() or "unknown error"
                self._status_label.setText(f"HID connection failed: {reason}")
        else:
            self._output_cb.setChecked(False)
            self._output_cb.setEnabled(False)
            self._led_bridge.disconnect()
            self._hid_connect_btn.setText("HID Connect")
            self._status_label.setText("HID disconnected")

    def _toggle_keyboard_output(self, checked: bool) -> None:
        self._output_to_keyboard = checked
        if checked and self._led_bridge.is_connected():
            self._push_colors_to_keyboard()

    def _step_once(self) -> None:
        self._tick()
        self._status_label.setText("Stepped once")

    def _on_radius_changed(self, value: float) -> None:
        self._model.neighbor_radius = value
        self._neighbors = self._model.build_neighbors(self._cells)

    def _on_wrap_toggled(self, checked: bool) -> None:
        self._model.wrap = checked
        self._neighbors = self._model.build_neighbors(self._cells)

    def _on_diff_a_changed(self, value: float) -> None:
        self._model.diffusion_a = value

    def _on_diff_b_changed(self, value: float) -> None:
        self._model.diffusion_b = value

    def _on_feed_changed(self, value: float) -> None:
        self._model.feed = value

    def _on_kill_changed(self, value: float) -> None:
        self._model.kill = value

    def _on_dt_changed(self, value: float) -> None:
        self._model.dt = value

    def _on_noise_changed(self, value: float) -> None:
        self._model.noise_rate = value

    def _on_interval_changed(self, value: float) -> None:
        self._timer.setInterval(int(value))

    def _tick(self) -> None:
        self._states = self._model.step(self._states, self._neighbors)
        self._refresh_view()
        if self._output_to_keyboard:
            self._frame_counter += 1
            if self._frame_counter % 2 == 0:
                self._push_colors_to_keyboard()

    def _refresh_view(self) -> None:
        self._field_widget.set_scene(self._layout_name, self._cells, self._states)
        if self._output_to_keyboard and self._led_bridge.is_connected():
            self._push_colors_to_keyboard()

    def _push_colors_to_keyboard(self) -> None:
        if self._cells:
            self._led_bridge.push_colors(self._cells, self._field_widget.get_cell_colors())

    def closeEvent(self, event) -> None:
        self._timer.stop()
        self._led_bridge.disconnect()
        super().closeEvent(event)


def run() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
