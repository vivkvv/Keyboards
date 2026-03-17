from typing import List, Optional, Set, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from ..sam_segmenter import SAMSegmenter
from ..layout_sorter import (
    resolve_problematic_rows_by_neighbors,
    sort_keys_by_position,
    split_keys_into_rows,
)


def run_segmentation(app, segmentation_thread_cls) -> None:
    if app.image is None:
        return

    if app.segmenter is None:
        app.status_bar.showMessage("Loading SAM model...")
        QApplication.processEvents()
        app.segmenter = SAMSegmenter(app.checkpoint_path)

    progress = QProgressDialog("Running segmentation...", "Cancel", 0, 0, app)
    progress.setWindowModality(Qt.WindowModal)
    progress.show()

    app.seg_thread = segmentation_thread_cls(app.segmenter, app.image)
    app.seg_thread.progress.connect(lambda msg: progress.setLabelText(msg))
    app.seg_thread.finished.connect(lambda keys: on_segmentation_done(app, keys, progress))
    app.seg_thread.error.connect(lambda err: on_segmentation_error(app, err, progress))
    app.seg_thread.start()


def on_segmentation_done(app, keys, progress: QProgressDialog) -> None:
    progress.close()
    app.keys = keys
    sort_and_reindex_keys(app)
    app._update_key_list()
    app.image_widget.set_keys(app.keys)
    app.btn_recognize.setEnabled(True)
    app.btn_save_seg.setEnabled(True)
    app.status_bar.showMessage(f"Found {len(keys)} key candidates")


def on_segmentation_error(app, error: str, progress: QProgressDialog) -> None:
    progress.close()
    QMessageBox.critical(app, "Segmentation Error", error)


def sort_and_reindex_keys(app) -> None:
    """Keep deterministic order: by rows (y), then by x inside each row."""
    initial = sort_keys_by_position(app.keys)
    resolved_rows: List = []
    app.keys, unresolved_obj_ids = resolve_problematic_rows_by_neighbors(
        initial,
        resolved_rows_out=resolved_rows,
    )
    for i, key in enumerate(app.keys):
        key.id = i
    app.problematic_key_ids = {k.id for k in app.keys if id(k) in unresolved_obj_ids}
    update_row_guides(app, excluded_ids=app.problematic_key_ids, rows=resolved_rows)
    app.image_widget.set_problematic_keys(app.problematic_key_ids)


def update_row_guides(
    app,
    excluded_ids: Optional[Set[int]] = None,
    rows: Optional[List[List]] = None,
) -> None:
    """Update debug row polylines from stable (non-problematic) keys."""
    excluded = excluded_ids or set()
    source_rows = rows if rows is not None else split_keys_into_rows(app.keys)
    guides: List[List[Tuple[int, int]]] = []
    for row in source_rows:
        stable_row = [k for k in row if k.id not in excluded]
        row_sorted = sorted(stable_row, key=lambda k: k.center()[0])
        guides.append([k.center() for k in row_sorted])
    app.image_widget.set_row_guides(guides)


def on_image_clicked(app, x: int, y: int, ctrl_pressed: bool) -> None:
    if app.image is None:
        return

    key_index = app.image_widget.find_key_at_point(x, y)
    if key_index is not None:
        app.image_widget.select_key(key_index, add_to_selection=ctrl_pressed)
        app._sync_list_selection()

        selected_count = len(app.image_widget.selected_keys)
        if selected_count > 1:
            app.status_bar.showMessage(
                f"Selected {selected_count} keys. Press Enter to merge, or Del to delete."
            )
        else:
            key = app.keys[key_index]
            app.status_bar.showMessage(f"Selected key #{key.id}")
        return

    if app.segmenter is None:
        app.status_bar.showMessage("Initializing SAM for point segmentation...")
        QApplication.processEvents()
        app.segmenter = SAMSegmenter(app.checkpoint_path)
        app.segmenter.set_image(app.image)

    app.status_bar.showMessage(f"Segmenting at ({x}, {y})...")
    QApplication.processEvents()

    key = app.segmenter.segment_at_point(x, y)
    if key:
        app.keys.append(key)
        sort_and_reindex_keys(app)
        app._update_key_list()
        app.image_widget.set_keys(app.keys)
        app.btn_save_seg.setEnabled(True)
        app.status_bar.showMessage(f"Added key #{key.id}")
    else:
        app.status_bar.showMessage("No key detected at this point")


def on_image_double_clicked(app, x: int, y: int) -> None:
    key_index = app.image_widget.find_key_at_point(x, y)
    if key_index is None:
        return
    app.image_widget.select_key(key_index, add_to_selection=False)
    app._sync_list_selection()
    app._edit_elements()


def merge_selected(app) -> None:
    selected_indices = app.image_widget.selected_keys
    if len(selected_indices) < 2:
        return

    points = []
    selected_keys = []
    for idx in selected_indices:
        if idx < len(app.keys):
            key = app.keys[idx]
            points.append(key.center())
            selected_keys.append(key)

    if not points or app.segmenter is None:
        return

    app.status_bar.showMessage("Merging keys...")
    QApplication.processEvents()

    merged = app.segmenter.segment_at_points(points)
    if not merged:
        QMessageBox.warning(app, "Merge Failed", "Could not merge selected keys")
        return

    for key in selected_keys:
        app.keys.remove(key)
    app.keys.append(merged)
    sort_and_reindex_keys(app)

    app._update_key_list()
    app.image_widget.set_keys(app.keys)
    app.image_widget.selected_keys = []
    app.image_widget.update()
    app.btn_save_seg.setEnabled(len(app.keys) > 0)
    app.status_bar.showMessage(f"Merged {len(selected_keys)} keys into key #{merged.id}")


def delete_selected(app) -> None:
    selected_indices = app.image_widget.selected_keys
    if not selected_indices:
        return

    keys_to_delete = [app.keys[i] for i in selected_indices if i < len(app.keys)]
    if not keys_to_delete:
        return

    reply = QMessageBox.question(
        app,
        "Delete Keys",
        f"Delete {len(keys_to_delete)} selected key(s)?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if reply != QMessageBox.StandardButton.Yes:
        return

    for key in keys_to_delete:
        app.keys.remove(key)

    sort_and_reindex_keys(app)
    app._update_key_list()
    app.image_widget.set_keys(app.keys)
    app.image_widget.selected_keys = []
    app.image_widget.update()
    app.btn_save_seg.setEnabled(len(app.keys) > 0)
    app.status_bar.showMessage(f"Deleted {len(keys_to_delete)} keys")
