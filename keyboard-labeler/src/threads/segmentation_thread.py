import numpy as np
from PySide6.QtCore import QThread, Signal

from ..sam_segmenter import SAMSegmenter


class SegmentationThread(QThread):
    """Thread for running SAM segmentation."""

    progress = Signal(str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, segmenter: SAMSegmenter, image: np.ndarray):
        super().__init__()
        self.segmenter = segmenter
        self.image = image

    def run(self):
        try:
            self.progress.emit("Setting image...")
            self.segmenter.set_image(self.image)

            self.progress.emit("Running auto-segmentation...")
            candidates = self.segmenter.auto_segment()

            self.finished.emit(candidates)
        except Exception as e:
            self.error.emit(str(e))

