"""PySide6 application for keyboard key labeling."""
import cv2
import numpy as np
import json
import os
from typing import List, Optional, Set, Tuple
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLabel, QFileDialog,
    QMessageBox, QProgressDialog, QInputDialog, QSplitter,
    QStatusBar, QCheckBox
)
from PySide6.QtCore import Qt, QFile
from PySide6.QtGui import QShortcut, QKeySequence

from .models import KeyCandidate, KeyStatus
from .sam_segmenter import SAMSegmenter
from .controllers.element_editor_controller import edit_elements
from .widgets.image_widget import ImageWidget
from .controllers.recognition_controller import run_recognition
from .controllers.key_ops_controller import (
    delete_selected,
    merge_selected,
    on_image_clicked,
    on_image_double_clicked,
    on_segmentation_done,
    on_segmentation_error,
    run_segmentation,
    sort_and_reindex_keys,
    update_row_guides,
)
from .controllers.workflow_controller import (
    load_layout_json,
    load_segmentation,
    save_layout_json,
    save_segmentation,
)
from .controllers.list_controller import on_item_double_clicked, on_selection_changed, update_key_list
from .threads.segmentation_thread import SegmentationThread
from .controllers.ui_controller import (
    handle_key_press,
    on_show_rows_toggled,
    select_next_key,
    set_display_mode,
    sync_list_selection,
    update_button_states,
)


class KeyLabelerApp(QMainWindow):
    """Main application window."""

    def __init__(self, checkpoint_path: str):
        super().__init__()
        self.checkpoint_path = checkpoint_path
        self.segmenter: Optional[SAMSegmenter] = None
        self.image: Optional[np.ndarray] = None
        self.image_path: Optional[str] = None
        self.keys: List[KeyCandidate] = []
        self.problematic_key_ids: Set[int] = set()

        self._init_ui()

    def _init_ui(self):
        if not self._init_ui_from_designer():
            raise RuntimeError("Failed to load UI from ui/main_window.ui")

    def _init_ui_from_designer(self) -> bool:
        ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "main_window.ui")
        if not os.path.exists(ui_path):
            return False
        try:
            from PySide6.QtUiTools import QUiLoader
        except Exception:
            return False

        ui_file = QFile(ui_path)
        if not ui_file.open(QFile.ReadOnly):
            return False

        try:
            root = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if root is None:
            return False

        self.setWindowTitle("Keyboard Key Labeler")
        self.setMinimumSize(1200, 800)
        self.setCentralWidget(root)

        self.key_list = root.findChild(QListWidget, "key_list")
        self.stats_label = root.findChild(QLabel, "stats_label")
        self.btn_load = root.findChild(QPushButton, "btn_load")
        self.btn_segment = root.findChild(QPushButton, "btn_segment")
        self.btn_load_seg = root.findChild(QPushButton, "btn_load_seg")
        self.btn_save_seg = root.findChild(QPushButton, "btn_save_seg")
        self.btn_approve = root.findChild(QPushButton, "btn_approve")
        self.btn_merge = root.findChild(QPushButton, "btn_merge")
        self.btn_delete = root.findChild(QPushButton, "btn_delete")
        self.chk_rec_new = root.findChild(QCheckBox, "chk_rec_new")
        self.chk_rec_legacy = root.findChild(QCheckBox, "chk_rec_legacy")
        self.chk_rec_trocr = root.findChild(QCheckBox, "chk_rec_trocr")
        self.chk_rec_shapes = root.findChild(QCheckBox, "chk_rec_shapes")
        self.btn_recognize = root.findChild(QPushButton, "btn_recognize")
        self.btn_edit_elements = root.findChild(QPushButton, "btn_edit_elements")
        self.btn_load_json = root.findChild(QPushButton, "btn_load_json")
        self.btn_save = root.findChild(QPushButton, "btn_save")
        self.btn_show_all = root.findChild(QPushButton, "btn_show_all")
        self.btn_show_selected = root.findChild(QPushButton, "btn_show_selected")
        self.btn_show_none = root.findChild(QPushButton, "btn_show_none")
        self.chk_show_rows = root.findChild(QCheckBox, "chk_show_rows")
        self.chk_show_recognized = root.findChild(QCheckBox, "chk_show_recognized")
        self.chk_hide_original = root.findChild(QCheckBox, "chk_hide_original")
        image_host = root.findChild(QWidget, "image_host")
        splitter = root.findChild(QSplitter, "main_splitter")

        required = [
            self.key_list, self.stats_label, self.btn_load, self.btn_segment, self.btn_load_seg, self.btn_save_seg,
            self.btn_approve, self.btn_merge, self.btn_delete, self.chk_rec_new, self.chk_rec_legacy, self.chk_rec_trocr,
            self.chk_rec_shapes, self.btn_recognize, self.btn_edit_elements, self.btn_load_json, self.btn_save,
            self.btn_show_all, self.btn_show_selected, self.btn_show_none, self.chk_show_rows,
            self.chk_show_recognized, self.chk_hide_original, image_host, splitter,
        ]
        if any(w is None for w in required):
            return False

        self.key_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.key_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.btn_load.clicked.connect(self._load_image)
        self.btn_segment.clicked.connect(self._run_segmentation)
        self.btn_load_seg.clicked.connect(self._load_segmentation)
        self.btn_save_seg.clicked.connect(self._save_segmentation)
        self.btn_approve.clicked.connect(self._approve_selected)
        self.btn_merge.clicked.connect(self._merge_selected)
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_recognize.clicked.connect(self._run_recognition)
        self.btn_edit_elements.clicked.connect(self._edit_elements)
        self.btn_load_json.clicked.connect(self._load_json)
        self.btn_save.clicked.connect(self._save_json)
        self.btn_show_all.clicked.connect(lambda: self._set_display_mode("all"))
        self.btn_show_selected.clicked.connect(lambda: self._set_display_mode("selected"))
        self.btn_show_none.clicked.connect(lambda: self._set_display_mode("none"))
        self.chk_show_rows.toggled.connect(self._on_show_rows_toggled)

        image_host_layout = QVBoxLayout(image_host)
        image_host_layout.setContentsMargins(0, 0, 0, 0)
        self.image_widget = ImageWidget()
        self.image_widget.clicked.connect(self._on_image_clicked)
        self.image_widget.double_clicked.connect(self._on_image_double_clicked)
        self.image_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.chk_show_recognized.toggled.connect(self.image_widget.set_show_recognized_labels)
        self.chk_hide_original.toggled.connect(self.image_widget.set_hide_original_labels)
        image_host_layout.addWidget(self.image_widget)

        splitter.setSizes([300, 900])

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Load an image to start.")

        self._key_nav_shortcuts = []
        self._install_key_nav_shortcuts(self.image_widget)
        self._install_key_nav_shortcuts(self.key_list)
        return True

    def _set_display_mode(self, mode: str):
        set_display_mode(self, mode)

    def _install_key_nav_shortcuts(self, widget: QWidget):
        next_sc = QShortcut(QKeySequence("Tab"), widget)
        next_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        next_sc.activated.connect(lambda: self._select_next_key(backward=False))
        prev_sc = QShortcut(QKeySequence("Shift+Tab"), widget)
        prev_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        prev_sc.activated.connect(lambda: self._select_next_key(backward=True))
        self._key_nav_shortcuts.extend([next_sc, prev_sc])

    def _on_show_rows_toggled(self, checked: bool):
        on_show_rows_toggled(self, checked)

    def _load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Keyboard Image",
            "assets",
            "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return

        self.image = cv2.imread(path)
        if self.image is None:
            QMessageBox.critical(self, "Error", f"Cannot load image: {path}")
            return

        self.image_path = path
        self.keys = []
        self._update_key_list()

        self.image_widget.set_image(self.image)
        self.image_widget.set_keys([])
        self.image_widget.set_row_guides([])
        self.image_widget.set_problematic_keys(set())

        self.btn_segment.setEnabled(True)
        self.btn_load_seg.setEnabled(True)
        self.btn_save_seg.setEnabled(False)
        self.btn_load_json.setEnabled(True)
        self.btn_save.setEnabled(True)
        self.stats_label.setText(f"Image: {self.image.shape[1]}x{self.image.shape[0]}")
        self.status_bar.showMessage(f"Loaded: {path}")

    def _run_segmentation(self):
        run_segmentation(self, SegmentationThread)

    def _on_segmentation_done(self, keys: List[KeyCandidate], progress: QProgressDialog):
        on_segmentation_done(self, keys, progress)

    def _on_segmentation_error(self, error: str, progress: QProgressDialog):
        on_segmentation_error(self, error, progress)

    def _sort_and_reindex_keys(self):
        sort_and_reindex_keys(self)

    def _update_row_guides(self, excluded_ids: Optional[Set[int]] = None, rows: Optional[List[List[KeyCandidate]]] = None):
        update_row_guides(self, excluded_ids=excluded_ids, rows=rows)

    def _update_key_list(self):
        update_key_list(self)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        on_item_double_clicked(self, item)

    def _on_selection_changed(self):
        on_selection_changed(self)

    def _on_image_clicked(self, x: int, y: int, ctrl_pressed: bool):
        on_image_clicked(self, x, y, ctrl_pressed)

    def _on_image_double_clicked(self, x: int, y: int):
        on_image_double_clicked(self, x, y)

    def _sync_list_selection(self):
        sync_list_selection(self)

    def _update_button_states(self):
        update_button_states(self)

    def keyPressEvent(self, event):
        if not handle_key_press(self, event):
            super().keyPressEvent(event)

    def _select_next_key(self, backward: bool = False):
        select_next_key(self, backward=backward)

    def _approve_selected(self):
        selected = self.key_list.selectedItems()
        for item in selected:
            key_id = item.data(Qt.ItemDataRole.UserRole)
            for key in self.keys:
                if key.id == key_id:
                    name, ok = QInputDialog.getText(
                        self, "Key Name",
                        f"Enter name for key #{key.id}:",
                        text=key.name or ""
                    )
                    if ok:
                        key.name = name
                        key.status = KeyStatus.APPROVED
                    break

        self._update_key_list()
        self.image_widget.update()

    def _edit_elements(self):
        edit_elements(self)

    def _merge_selected(self):
        merge_selected(self)

    def _delete_selected(self):
        delete_selected(self)

    def _run_recognition(self):
        run_recognition(self)





    def _save_segmentation(self):
        save_segmentation(self)

    def _load_segmentation(self):
        load_segmentation(self)

    def _load_json(self):
        load_layout_json(self)

    def _save_json(self):
        save_layout_json(self)
