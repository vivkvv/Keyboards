# QMK Keyboard Visualizer

Desktop utility for visualizing a QMK keyboard layout, tracking key presses, showing current OS input language labels, using HID-based keyboard feedback, and running tutor-style overlays.

## Main Features

- load a QMK/VIA keymap JSON
- load a keyboard geometry JSON
- highlight pressed keys from the Windows hook backend
- show OS-layout-aware legends on keys
- optional HID connection for active-layer polling and physical keyboard highlight control
- tutor overlay and transparent keyboard overlay
- field simulator for keyboard-cell experiments

## Project Layout

- `visualizer.py` - main application entry point
- `field_sim.py` - field simulator entry point
- `keyboard_visualizer/` - main application package
- `field_sim/` - field simulator package
- `data/` - local example geometry and bindings

## Requirements

- Windows
- Python 3.10
- optional: a compatible HID-enabled keyboard firmware for RGB / layer features

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run

Main visualizer:

```bash
python visualizer.py
```

Field simulator:

```bash
python field_sim.py
```

## Local Environment Note

For this project on this machine, use the `keyboard-visualizer` Conda environment:

```bash
C:\Users\VovkVV\.conda\envs\keyboard-visualizer\python.exe visualizer.py
```

For quick file checks:

```bash
C:\Users\VovkVV\.conda\envs\keyboard-visualizer\python.exe -m py_compile keyboard_visualizer\ui\tutor_overlay.py
```

## Typical Files

Current local examples in `data/`:

- `charybdis_nano_bindings.json` - key bindings / keymap data
- `charybdis_nano_geometry_from_photo.json` - keyboard geometry used by the visualizer

For `field_sim`, a visual-layout-format file is also included:

- `charybdis_nano_40_visual_layout.json`

## Notes

- `config.ini` stores local recent-file and UI state and is not intended to be committed.
- Paths in `config.ini` are stored relative to the config location when possible.
- Tutor hand schemes are stored in:
  - `keyboard_visualizer/resources/tutor_hand_schemes.json`
  - `keyboard_visualizer/resources/tutor_key_scheme_assignments.json`
