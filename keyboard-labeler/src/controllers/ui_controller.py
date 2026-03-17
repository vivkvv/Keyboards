from PySide6.QtCore import Qt


def sync_list_selection(app) -> None:
    """Sync list selection with image widget selection."""
    app.key_list.blockSignals(True)
    app.key_list.clearSelection()
    last_selected_item = None
    for idx in app.image_widget.selected_keys:
        if idx < len(app.keys):
            key_id = app.keys[idx].id
            for i in range(app.key_list.count()):
                item = app.key_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == key_id:
                    item.setSelected(True)
                    last_selected_item = item
                    break
    app.key_list.blockSignals(False)

    if last_selected_item:
        app.key_list.scrollToItem(last_selected_item)

    update_button_states(app)


def update_button_states(app) -> None:
    """Update button enabled states based on selection."""
    selected_count = len(app.image_widget.selected_keys)
    app.btn_approve.setEnabled(selected_count > 0)
    app.btn_edit_elements.setEnabled(selected_count == 1)
    app.btn_delete.setEnabled(selected_count > 0)
    app.btn_merge.setEnabled(selected_count >= 2)


def select_next_key(app, backward: bool = False) -> None:
    """Select next/previous key and keep list/image selection in sync."""
    if not app.keys:
        return

    if app.image_widget.selected_keys:
        current_idx = app.image_widget.selected_keys[-1]
    else:
        current_idx = 0 if backward else -1

    if backward:
        next_idx = (current_idx - 1) % len(app.keys)
    else:
        next_idx = (current_idx + 1) % len(app.keys)

    app.image_widget.select_key(next_idx, add_to_selection=False)
    sync_list_selection(app)
    app.status_bar.showMessage(f"Selected key #{app.keys[next_idx].id}")


def set_display_mode(app, mode: str) -> None:
    """Set display mode and update button states."""
    app.image_widget.set_display_mode(mode)
    app.btn_show_all.setChecked(mode == "all")
    app.btn_show_selected.setChecked(mode == "selected")
    app.btn_show_none.setChecked(mode == "none")


def on_show_rows_toggled(app, checked: bool) -> None:
    """Toggle row guide visibility in image widget."""
    if hasattr(app, "image_widget") and app.image_widget is not None:
        app.image_widget.set_show_row_guides(checked)


def handle_key_press(app, event) -> bool:
    """Handle key navigation/actions. Return True if handled."""
    if event.key() == Qt.Key.Key_Tab:
        if app.keys:
            backward = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            app._select_next_key(backward=backward)
            event.accept()
            return True
        return False

    if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
        if len(app.image_widget.selected_keys) >= 2:
            app._merge_selected()
        return True

    if event.key() == Qt.Key.Key_Delete:
        if len(app.image_widget.selected_keys) > 0:
            app._delete_selected()
        return True

    if event.key() == Qt.Key.Key_Escape:
        app.image_widget.selected_keys = []
        app.image_widget.update()
        app._sync_list_selection()
        app.status_bar.showMessage("Selection cleared")
        return True

    return False

