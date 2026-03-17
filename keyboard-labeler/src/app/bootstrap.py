from typing import Optional

import cv2
from PySide6.QtWidgets import QApplication

from ..key_labeler_app import KeyLabelerApp


def run_app(checkpoint_path: str, image_path: Optional[str] = None):
    """Run the application."""
    app = QApplication([])
    app.setStyle("Fusion")
    window = KeyLabelerApp(checkpoint_path)

    if image_path:
        window.image = cv2.imread(image_path)
        window.image_path = image_path
        window.image_widget.set_image(window.image)
        window.btn_segment.setEnabled(True)
        window.btn_load_seg.setEnabled(True)
        window.btn_save.setEnabled(True)

    window.show()
    return app.exec()

