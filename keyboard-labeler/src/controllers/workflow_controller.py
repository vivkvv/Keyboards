import json
import os

import cv2
from PySide6.QtWidgets import QFileDialog, QMessageBox

from ..models import KeyboardLayout
from ..services.layout_io import build_layout_payload, build_segmentation_payload, parse_segmentation_keys


def _relative_or_absolute_image_ref(image_path: str, json_path: str) -> str:
    try:
        return os.path.relpath(image_path, os.path.dirname(json_path))
    except ValueError:
        return os.path.abspath(image_path)


def _resolve_layout_image_path(image_ref: str, json_path: str) -> str:
    if not image_ref:
        return ""
    if os.path.isabs(image_ref):
        return image_ref

    json_dir = os.path.dirname(json_path)
    candidates = [
        os.path.normpath(os.path.join(json_dir, image_ref)),
        os.path.normpath(os.path.join(json_dir, os.path.basename(image_ref))),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return candidates[0]


def save_segmentation(app) -> None:
    if not app.image_path or not app.keys:
        return

    base = os.path.splitext(os.path.basename(app.image_path))[0]
    default_path = os.path.join(os.path.dirname(app.image_path), "..", "keyboards", f"{base}_segmentation.json")
    path, _ = QFileDialog.getSaveFileName(app, "Save Segmentation", default_path, "JSON files (*.json)")
    if not path:
        return

    os.makedirs(os.path.dirname(path), exist_ok=True)
    app._sort_and_reindex_keys()
    payload = build_segmentation_payload(app.image_path, app.image.shape[1], app.image.shape[0], app.keys)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    app.status_bar.showMessage(f"Segmentation saved: {path}")


def load_segmentation(app) -> None:
    if app.image is None:
        QMessageBox.information(app, "Load Segmentation", "Load image first.")
        return

    path, _ = QFileDialog.getOpenFileName(app, "Load Segmentation", "keyboards", "JSON files (*.json)")
    if not path:
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        QMessageBox.critical(app, "Load Error", f"Cannot load segmentation: {e}")
        return

    app.keys = parse_segmentation_keys(data)
    app._sort_and_reindex_keys()
    app._update_key_list()
    app.image_widget.set_keys(app.keys)
    app.btn_recognize.setEnabled(len(app.keys) > 0)
    app.btn_save_seg.setEnabled(len(app.keys) > 0)
    app.status_bar.showMessage(f"Loaded segmentation: {len(app.keys)} keys from {os.path.basename(path)}")


def save_layout_json(app) -> None:
    if not app.image_path:
        return

    base = os.path.splitext(os.path.basename(app.image_path))[0]
    default_path = os.path.join(os.path.dirname(app.image_path), "..", "keyboards", f"{base}.json")
    path, _ = QFileDialog.getSaveFileName(app, "Save Recognition JSON", default_path, "JSON files (*.json)")
    if not path:
        return

    os.makedirs(os.path.dirname(path), exist_ok=True)
    app._sort_and_reindex_keys()

    payload = build_layout_payload(app.image_path, app.image.shape[1], app.image.shape[0], app.keys)
    payload["image"] = _relative_or_absolute_image_ref(app.image_path, path)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    app.status_bar.showMessage(f"Recognition JSON saved: {path}")


def load_layout_json(app) -> None:
    path, _ = QFileDialog.getOpenFileName(app, "Load Recognition JSON", "keyboards", "JSON files (*.json)")
    if not path:
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        layout = KeyboardLayout.from_dict(data)
    except Exception as e:
        QMessageBox.critical(app, "Load Error", f"Cannot load recognition JSON: {e}")
        return

    image_ref = layout.image_path
    image_path = _resolve_layout_image_path(image_ref, path)
    image = cv2.imread(image_path) if image_path else None
    if image is None:
        QMessageBox.critical(
            app,
            "Load Error",
            "Project JSON loaded, but the source image could not be opened.\n\n"
            f"JSON file: {path}\n"
            f"Image reference: {image_ref}\n"
            f"Resolved path: {image_path}",
        )
        return

    app.image = image
    app.image_path = image_path
    app.keys = layout.keys
    app.problematic_key_ids = set()

    app._sort_and_reindex_keys()
    app._update_key_list()

    app.image_widget.set_image(app.image)
    app.image_widget.set_keys(app.keys)
    app.image_widget.set_row_guides([])
    app.image_widget.set_problematic_keys(set())
    app.image_widget.set_selected([])

    app.btn_segment.setEnabled(True)
    app.btn_load_seg.setEnabled(True)
    app.btn_save_seg.setEnabled(len(app.keys) > 0)
    app.btn_load_json.setEnabled(True)
    app.btn_save.setEnabled(True)
    app.btn_recognize.setEnabled(len(app.keys) > 0)
    app.stats_label.setText(f"Image: {app.image.shape[1]}x{app.image.shape[0]}")
    app.status_bar.showMessage(f"Loaded recognition JSON: {os.path.basename(path)}")
