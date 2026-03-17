from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

from ..models import KeyStatus


def update_key_list(app) -> None:
    app.key_list.clear()
    for key in app.keys:
        status = "✓" if key.status == KeyStatus.APPROVED else "○"
        name = key.name or f"Key #{key.id}"
        elements_str = ""
        if key.elements:
            texts = [e.content for e in key.elements if e.type == "text"]
            if texts:
                elements_str = f" [{', '.join(texts)}]"

        item = QListWidgetItem(f"{status} {name}{elements_str}")
        item.setData(Qt.ItemDataRole.UserRole, key.id)
        app.key_list.addItem(item)

    approved = sum(1 for k in app.keys if k.status == KeyStatus.APPROVED)
    app.stats_label.setText(
        f"Total: {len(app.keys)} | Approved: {approved} | Draft: {len(app.keys) - approved}"
    )


def on_item_double_clicked(app, item: QListWidgetItem) -> None:
    """Handle double-click on list item - open element editor."""
    key_id = item.data(Qt.ItemDataRole.UserRole)
    for i, key in enumerate(app.keys):
        if key.id == key_id:
            app.image_widget.select_key(i, add_to_selection=False)
            app._sync_list_selection()
            app._edit_elements()
            break


def on_selection_changed(app) -> None:
    selected = app.key_list.selectedItems()
    indices = []
    for item in selected:
        key_id = item.data(Qt.ItemDataRole.UserRole)
        for i, key in enumerate(app.keys):
            if key.id == key_id:
                indices.append(i)
                break

    app.image_widget.set_selected(indices)

    has_selection = len(indices) > 0
    app.btn_approve.setEnabled(has_selection)
    app.btn_delete.setEnabled(has_selection)
    app.btn_merge.setEnabled(len(indices) >= 2)

