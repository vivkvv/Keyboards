"""Dialog for editing key elements (text, icons, their positions)."""
import cv2
import numpy as np
import os
import math
import traceback
from datetime import datetime
from typing import List, Optional, Tuple
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QComboBox, QGroupBox, QSpinBox,
    QDoubleSpinBox, QMessageBox, QWidget, QSplitter, QFormLayout, QFileDialog, QCheckBox,
    QGridLayout, QApplication, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QFile
from PySide6.QtGui import (
    QImage, QPixmap, QPainter, QColor, QPen, QBrush, QMouseEvent, QFont, QPolygonF
)

from .models import KeyCandidate, KeyElement
from .key_ocr_pipeline import KeyOCRPipeline

# Global OCR models (lazy loaded)
_easyocr_reader = None
_trocr_model = None
_trocr_processor = None

def get_ocr_reader():
    """Get or create EasyOCR reader (lazy initialization)."""
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            import easyocr
            # CPU mode is slower but much more stable in long-running PySide sessions.
            _easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        except ImportError:
            print("EasyOCR not available")
            return None
    return _easyocr_reader

def get_trocr():
    """Get or create TrOCR model (lazy initialization)."""
    global _trocr_model, _trocr_processor
    if _trocr_model is None:
        try:
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel
            print("Loading TrOCR model...")
            _trocr_processor = TrOCRProcessor.from_pretrained('microsoft/trocr-base-printed')
            _trocr_model = VisionEncoderDecoderModel.from_pretrained('microsoft/trocr-base-printed')
            print("TrOCR loaded successfully")
        except ImportError:
            print("TrOCR not available (pip install transformers)")
            return None, None
        except Exception as e:
            print(f"TrOCR loading error: {e}")
            return None, None
    return _trocr_processor, _trocr_model

def recognize_with_trocr(image: np.ndarray) -> str:
    """Recognize text in image using TrOCR (good for single characters)."""
    processor, model = get_trocr()
    if processor is None or model is None:
        return ""

    try:
        from PIL import Image as PILImage
        # Convert BGR to RGB
        if len(image.shape) == 3:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)

        pil_img = PILImage.fromarray(rgb)
        pixel_values = processor(images=pil_img, return_tensors="pt").pixel_values
        generated_ids = model.generate(pixel_values)
        text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return text.strip()
    except Exception as e:
        print(f"TrOCR recognition error: {e}")
        return ""


class KeyImageWidget(QWidget):
    """Widget to display key image with element bboxes."""

    element_selected = Signal(int)  # element index
    bbox_changed = Signal(int, list)  # element index, new bbox
    text_transform_changed = Signal(int, float, float, float)  # index, offset_x, offset_y, angle_deg

    def __init__(self):
        super().__init__()
        self.image: Optional[QPixmap] = None
        self.elements: List[KeyElement] = []
        self.selected_index: int = -1
        self.focus_element: Optional[KeyElement] = None
        self.setMinimumSize(300, 300)

        # For bbox editing
        self.dragging = False
        self.drag_mode = None  # "move", "resize_tl", "resize_br", etc.
        self.drag_start = None
        self.drag_bbox_start = None
        self.drag_text_offset_start = None
        self.drag_text_angle_start = 0.0
        self.drag_rotate_center = None
        self.drag_rotate_start_angle = 0.0

    def set_image(self, image: np.ndarray):
        """Set the key image to display."""
        h, w = image.shape[:2]
        if len(image.shape) == 3:
            c = image.shape[2]
            bytes_per_line = c * w
            q_image = QImage(image.data, w, h, bytes_per_line, QImage.Format_BGR888)
        else:
            bytes_per_line = w
            q_image = QImage(image.data, w, h, bytes_per_line, QImage.Format_Grayscale8)
        self.image = QPixmap.fromImage(q_image)
        self.update()

    def set_elements(self, elements: List[KeyElement]):
        """Set elements to display."""
        self.elements = elements
        self.update()

    def set_selected(self, index: int):
        """Set selected element index."""
        self.selected_index = index
        self.update()

    def set_focus_element(self, elem: Optional[KeyElement]):
        """Set transient focused element from method result lists."""
        self.focus_element = elem
        self.update()

    def _get_scale_and_offset(self) -> Tuple[float, float, float]:
        """Get scale and offset for drawing."""
        if not self.image:
            return 1.0, 0, 0

        w_scale = self.width() / self.image.width()
        h_scale = self.height() / self.image.height()
        scale = min(w_scale, h_scale)

        scaled_w = self.image.width() * scale
        scaled_h = self.image.height() * scale
        offset_x = 0.0
        offset_y = 0.0

        return scale, offset_x, offset_y

    def _bbox_to_widget(self, bbox: List[float]) -> QRectF:
        """Convert relative bbox to widget coordinates."""
        if not self.image:
            return QRectF()

        scale, offset_x, offset_y = self._get_scale_and_offset()
        img_w = self.image.width() * scale
        img_h = self.image.height() * scale

        x = offset_x + bbox[0] * img_w
        y = offset_y + bbox[1] * img_h
        w = bbox[2] * img_w
        h = bbox[3] * img_h

        return QRectF(x, y, w, h)

    def _widget_to_bbox(self, rect: QRectF) -> List[float]:
        """Convert widget coordinates to relative bbox."""
        if not self.image:
            return [0, 0, 0, 0]

        scale, offset_x, offset_y = self._get_scale_and_offset()
        img_w = self.image.width() * scale
        img_h = self.image.height() * scale

        x = (rect.x() - offset_x) / img_w
        y = (rect.y() - offset_y) / img_h
        w = rect.width() / img_w
        h = rect.height() / img_h

        # Clamp to [0, 1]
        x = max(0, min(1 - w, x))
        y = max(0, min(1 - h, y))
        w = max(0.05, min(1 - x, w))
        h = max(0.05, min(1 - y, h))

        return [x, y, w, h]

    @staticmethod
    def _ensure_text_transform_attrs(elem: KeyElement):
        """Ensure text transform attrs exist and are sane."""
        if str(getattr(elem, "type", "")).lower() != "text":
            return
        if not hasattr(elem, "text_offset_x"):
            elem.text_offset_x = 0.0
        if not hasattr(elem, "text_offset_y"):
            elem.text_offset_y = 0.0
        if not hasattr(elem, "text_angle_deg"):
            elem.text_angle_deg = 0.0
        if not hasattr(elem, "text_size_rel_key"):
            bbox = getattr(elem, "bbox", [0.1, 0.1, 0.8, 0.8]) or [0.1, 0.1, 0.8, 0.8]
            elem.text_size_rel_key = max(0.04, min(0.5, float(bbox[3]) * 0.55))

    def _get_text_base_geometry(self, elem: KeyElement, rect: QRectF) -> Tuple[QPointF, float, float, float]:
        """Return (center, base_angle_deg, width, height) in widget coordinates."""
        quad = getattr(elem, "quad", None)
        has_quad = isinstance(quad, list) and len(quad) >= 4 and self.image is not None
        if has_quad:
            scale, offset_x, offset_y = self._get_scale_and_offset()
            img_w = self.image.width() * scale
            img_h = self.image.height() * scale
            pts = [
                QPointF(
                    offset_x + float(p[0]) * img_w,
                    offset_y + float(p[1]) * img_h,
                )
                for p in quad[:4]
            ]
            p0, p1, p2, p3 = pts
            edge_w = max(8.0, math.hypot(p1.x() - p0.x(), p1.y() - p0.y()))
            edge_h = max(
                8.0,
                0.5
                * (
                    math.hypot(p3.x() - p0.x(), p3.y() - p0.y())
                    + math.hypot(p2.x() - p1.x(), p2.y() - p1.y())
                ),
            )
            cx = sum(p.x() for p in pts) / 4.0
            cy = sum(p.y() for p in pts) / 4.0
            angle_deg = math.degrees(math.atan2(p1.y() - p0.y(), p1.x() - p0.x()))
            return QPointF(cx, cy), angle_deg, edge_w, edge_h
        return rect.center(), 0.0, max(8.0, rect.width()), max(8.0, rect.height())

    def _get_text_overlay_geometry(self, elem: KeyElement, rect: QRectF) -> Tuple[QPointF, float, float, float]:
        """Return (center, angle_deg, width, height) including user text transforms."""
        self._ensure_text_transform_attrs(elem)
        center, base_angle, edge_w, edge_h = self._get_text_base_geometry(elem, rect)
        if self.image is None:
            return center, base_angle + float(getattr(elem, "text_angle_deg", 0.0)), edge_w, edge_h
        scale, _, _ = self._get_scale_and_offset()
        img_w = self.image.width() * scale
        img_h = self.image.height() * scale
        tx = float(getattr(elem, "text_offset_x", 0.0)) * img_w
        ty = float(getattr(elem, "text_offset_y", 0.0)) * img_h
        return QPointF(center.x() + tx, center.y() + ty), base_angle + float(getattr(elem, "text_angle_deg", 0.0)), edge_w, edge_h

    def _get_text_handle_points(self, elem: KeyElement, rect: QRectF) -> Tuple[QPointF, QPointF]:
        """Return (move_handle_center, rotate_handle_center) for selected text."""
        center, angle_deg, edge_w, edge_h = self._get_text_overlay_geometry(elem, rect)
        radius = max(16.0, 0.5 * max(edge_w, edge_h) + 20.0)
        a = math.radians(angle_deg - 90.0)
        rotate = QPointF(center.x() + radius * math.cos(a), center.y() + radius * math.sin(a))
        return center, rotate

    def paintEvent(self, event):
        if not self.image:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        scale, offset_x, offset_y = self._get_scale_and_offset()

        # Draw image
        scaled_pixmap = self.image.scaled(
            int(self.image.width() * scale),
            int(self.image.height() * scale),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        painter.drawPixmap(int(offset_x), int(offset_y), scaled_pixmap)

        # Draw element bboxes
        for i, elem in enumerate(self.elements):
            if not hasattr(elem, 'bbox') or not elem.bbox:
                continue

            rect = self._bbox_to_widget(elem.bbox)

            if i == self.selected_index:
                self._draw_selected_preview(painter, rect, elem)

            if i == self.selected_index:
                pen_color = QColor(255, 0, 0)
                fill_color = QColor(255, 0, 0, 28)
                pen_width = 3
            else:
                pen_color = QColor(0, 255, 0)
                fill_color = QColor(0, 255, 0, 18)
                pen_width = 2

            painter.setPen(QPen(pen_color, pen_width))
            painter.setBrush(QBrush(fill_color))
            painter.drawRect(rect)

            # Draw resize handles for selected
            if i == self.selected_index:
                handle_size = 8
                handles = [
                    rect.topLeft(),
                    rect.topRight(),
                    rect.bottomLeft(),
                    rect.bottomRight()
                ]
                painter.setBrush(QBrush(pen_color))
                for h in handles:
                    painter.drawRect(
                        h.x() - handle_size/2,
                        h.y() - handle_size/2,
                        handle_size, handle_size
                    )
                if str(getattr(elem, "type", "")).lower() == "text":
                    move_h, rot_h = self._get_text_handle_points(elem, rect)
                    painter.setPen(QPen(QColor(255, 220, 0), 2))
                    painter.drawLine(move_h, rot_h)
                    painter.setBrush(QBrush(QColor(0, 200, 255)))
                    painter.drawEllipse(move_h, 5, 5)
                    painter.setBrush(QBrush(QColor(255, 220, 0)))
                    painter.drawEllipse(rot_h, 6, 6)

        # Draw focused method result (cyan highlight) on top.
        if self.focus_element is not None and hasattr(self.focus_element, "bbox") and self.focus_element.bbox:
            rect = self._bbox_to_widget(self.focus_element.bbox)
            painter.setPen(QPen(QColor(0, 220, 255), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)

        painter.end()

    def _draw_selected_preview(self, painter: QPainter, rect: QRectF, elem: KeyElement):
        """Draw selected element as final overlay style (without key photo background)."""
        etype = str(getattr(elem, "type", "")).lower()
        content = str(getattr(elem, "content", "") or "").strip()
        quad = getattr(elem, "quad", None)
        has_quad = isinstance(quad, list) and len(quad) >= 4 and self.image is not None

        painter.save()
        try:
            if etype == "text":
                if has_quad:
                    scale, offset_x, offset_y = self._get_scale_and_offset()
                    img_w = self.image.width() * scale
                    img_h = self.image.height() * scale
                    pts = [
                        QPointF(
                            offset_x + float(p[0]) * img_w,
                            offset_y + float(p[1]) * img_h,
                        )
                        for p in quad[:4]
                    ]
                    poly = QPolygonF(pts)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(20, 20, 20, 95))
                    painter.drawPolygon(poly)
                else:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(20, 20, 20, 95))
                    painter.drawRect(rect)

                center, angle_deg, edge_w, edge_h = self._get_text_overlay_geometry(elem, rect)
                if self.image is not None:
                    scale, _, _ = self._get_scale_and_offset()
                    img_h = self.image.height() * scale
                else:
                    img_h = max(100.0, rect.height())
                rel_size = float(getattr(elem, "text_size_rel_key", 0.12))
                rel_size = max(0.03, min(0.6, rel_size))
                font_px = max(8, int(rel_size * img_h))
                font = QFont("Segoe UI", font_px)
                painter.setFont(font)
                painter.setPen(QPen(QColor(245, 245, 245), 1))
                painter.translate(center)
                painter.rotate(angle_deg)
                draw_w = max(edge_w * 1.35, font_px * max(2.0, len(content) * 0.7))
                draw_h = max(edge_h * 1.2, font_px * 1.5)
                draw_rect = QRectF(-draw_w / 2.0, -draw_h / 2.0, draw_w, draw_h)
                painter.drawText(draw_rect, Qt.AlignCenter, content or "text")
            else:
                # Fallback: bbox-based preview when no oriented quad is available.
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(20, 20, 20, 95))
                painter.drawRect(rect)
                pad = 3.0
                inner = rect.adjusted(pad, pad, -pad, -pad)
                if inner.width() < 4 or inner.height() < 4:
                    return
                # Support icon/image and divider preview.
                is_divider = etype == "divider" or content.startswith("divider_") or content in {"divider_vertical", "divider_horizontal", "divider"}
                if is_divider:
                    ori = str(getattr(elem, "divider_orientation", "") or "")
                    if not ori:
                        if "horizontal" in content:
                            ori = "horizontal"
                        else:
                            ori = "vertical"
                    th = float(getattr(elem, "divider_thickness", 0.08))
                    th = max(0.01, min(0.5, th))
                    pen_w = max(1, int((inner.height() if ori == "horizontal" else inner.width()) * th))
                    painter.setPen(QPen(QColor(240, 240, 240), pen_w))
                    if ori == "horizontal":
                        cy = inner.center().y()
                        painter.drawLine(int(inner.left()), int(cy), int(inner.right()), int(cy))
                    else:
                        cx = inner.center().x()
                        painter.drawLine(int(cx), int(inner.top()), int(cx), int(inner.bottom()))
                elif os.path.exists(content):
                    pix = QPixmap(content)
                    if not pix.isNull():
                        fitted = pix.scaled(
                            int(inner.width()),
                            int(inner.height()),
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation,
                        )
                        px = inner.x() + (inner.width() - fitted.width()) / 2
                        py = inner.y() + (inner.height() - fitted.height()) / 2
                        painter.drawPixmap(int(px), int(py), fitted)
                else:
                    painter.setPen(QPen(QColor(240, 240, 240), 2))
                    painter.drawEllipse(inner)
        finally:
            painter.restore()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton or not self.image:
            return

        pos = event.position()

        # Check if clicking on a handle of selected element
        if self.selected_index >= 0 and self.selected_index < len(self.elements):
            elem = self.elements[self.selected_index]
            if hasattr(elem, 'bbox') and elem.bbox:
                rect = self._bbox_to_widget(elem.bbox)
                if str(getattr(elem, "type", "")).lower() == "text":
                    move_h, rot_h = self._get_text_handle_points(elem, rect)
                    if math.hypot(pos.x() - rot_h.x(), pos.y() - rot_h.y()) <= 12:
                        self.dragging = True
                        self.drag_mode = "text_rotate"
                        self.drag_start = pos
                        self.drag_text_angle_start = float(getattr(elem, "text_angle_deg", 0.0))
                        self.drag_rotate_center = move_h
                        self.drag_rotate_start_angle = math.degrees(
                            math.atan2(pos.y() - move_h.y(), pos.x() - move_h.x())
                        )
                        return
                    if math.hypot(pos.x() - move_h.x(), pos.y() - move_h.y()) <= 10:
                        self.dragging = True
                        self.drag_mode = "text_move"
                        self.drag_start = pos
                        self.drag_text_offset_start = [
                            float(getattr(elem, "text_offset_x", 0.0)),
                            float(getattr(elem, "text_offset_y", 0.0)),
                        ]
                        return

                handle_size = 12

                corners = {
                    "resize_tl": rect.topLeft(),
                    "resize_tr": rect.topRight(),
                    "resize_bl": rect.bottomLeft(),
                    "resize_br": rect.bottomRight()
                }

                for mode, corner in corners.items():
                    if abs(pos.x() - corner.x()) < handle_size and \
                       abs(pos.y() - corner.y()) < handle_size:
                        self.dragging = True
                        self.drag_mode = mode
                        self.drag_start = pos
                        self.drag_bbox_start = list(elem.bbox)
                        return

                # Check if clicking inside bbox (move)
                if rect.contains(pos):
                    self.dragging = True
                    self.drag_mode = "move"
                    self.drag_start = pos
                    self.drag_bbox_start = list(elem.bbox)
                    return

        # Check if clicking on any element
        for i, elem in enumerate(self.elements):
            if hasattr(elem, 'bbox') and elem.bbox:
                rect = self._bbox_to_widget(elem.bbox)
                if rect.contains(pos):
                    self.selected_index = i
                    self.element_selected.emit(i)
                    self.update()
                    return

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self.dragging or self.selected_index < 0:
            return

        pos = event.position()
        elem = self.elements[self.selected_index]

        scale, offset_x, offset_y = self._get_scale_and_offset()
        img_w = self.image.width() * scale
        img_h = self.image.height() * scale

        if self.drag_mode == "text_move":
            self._ensure_text_transform_attrs(elem)
            dx = (pos.x() - self.drag_start.x()) / img_w
            dy = (pos.y() - self.drag_start.y()) / img_h
            elem.text_offset_x = float(self.drag_text_offset_start[0] + dx)
            elem.text_offset_y = float(self.drag_text_offset_start[1] + dy)
            self.update()
            return
        if self.drag_mode == "text_rotate":
            self._ensure_text_transform_attrs(elem)
            c = self.drag_rotate_center
            cur_angle = math.degrees(math.atan2(pos.y() - c.y(), pos.x() - c.x()))
            delta = cur_angle - self.drag_rotate_start_angle
            elem.text_angle_deg = float(self.drag_text_angle_start + delta)
            while elem.text_angle_deg > 180.0:
                elem.text_angle_deg -= 360.0
            while elem.text_angle_deg < -180.0:
                elem.text_angle_deg += 360.0
            self.update()
            return

        dx = (pos.x() - self.drag_start.x()) / img_w
        dy = (pos.y() - self.drag_start.y()) / img_h

        bbox = list(self.drag_bbox_start)

        if self.drag_mode == "move":
            bbox[0] += dx
            bbox[1] += dy
        elif self.drag_mode == "resize_tl":
            bbox[0] += dx
            bbox[1] += dy
            bbox[2] -= dx
            bbox[3] -= dy
        elif self.drag_mode == "resize_tr":
            bbox[2] += dx
            bbox[1] += dy
            bbox[3] -= dy
        elif self.drag_mode == "resize_bl":
            bbox[0] += dx
            bbox[2] -= dx
            bbox[3] += dy
        elif self.drag_mode == "resize_br":
            bbox[2] += dx
            bbox[3] += dy

        # Clamp
        bbox[0] = max(0, min(1 - 0.05, bbox[0]))
        bbox[1] = max(0, min(1 - 0.05, bbox[1]))
        bbox[2] = max(0.05, min(1 - bbox[0], bbox[2]))
        bbox[3] = max(0.05, min(1 - bbox[1], bbox[3]))

        elem.bbox = bbox
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.dragging and self.selected_index >= 0:
            elem = self.elements[self.selected_index]
            if self.drag_mode in {"text_move", "text_rotate"}:
                self.text_transform_changed.emit(
                    self.selected_index,
                    float(getattr(elem, "text_offset_x", 0.0)),
                    float(getattr(elem, "text_offset_y", 0.0)),
                    float(getattr(elem, "text_angle_deg", 0.0)),
                )
            else:
                self.bbox_changed.emit(self.selected_index, list(elem.bbox))
        self.dragging = False
        self.drag_mode = None


class ElementEditorDialog(QDialog):
    """Dialog for editing elements of a single key."""

    def __init__(
        self,
        key: KeyCandidate,
        key_image: np.ndarray,
        parent=None,
        full_image: Optional[np.ndarray] = None,
        method_elements: Optional[dict] = None,
    ):
        super().__init__(parent)
        self.key = key
        self.key_image = key_image
        self.full_image = full_image
        self.elements = list(key.elements) if key.elements else []
        self.method_elements = method_elements or {}

        self._init_ui()
        self._update_list()
        self._update_method_columns()

    def _init_ui(self):
        self.setWindowTitle(f"Edit Elements - {self.key.name or f'Key #{self.key.id}'}")
        self.setMinimumSize(800, 600)

        ui_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "ui",
            "element_editor_dialog.ui",
        )
        if not os.path.exists(ui_path):
            raise RuntimeError("Failed to load UI from ui/element_editor_dialog.ui")
        try:
            from PySide6.QtUiTools import QUiLoader
        except Exception as e:
            raise RuntimeError(f"QtUiTools unavailable: {e}") from e

        ui_file = QFile(ui_path)
        if not ui_file.open(QFile.ReadOnly):
            raise RuntimeError("Failed to open ui/element_editor_dialog.ui")
        try:
            root = QUiLoader().load(ui_file, self)
        finally:
            ui_file.close()
        if root is None:
            raise RuntimeError("Failed to parse ui/element_editor_dialog.ui")

        wrapper_layout = QHBoxLayout(self)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addWidget(root)

        # Core panels and layouts.
        self.right_panel = root.findChild(QWidget, "right_panel")
        self.props_group = root.findChild(QGroupBox, "props_group")
        self.props_left_widget = root.findChild(QWidget, "props_left_widget")
        self.props_right_widget = root.findChild(QWidget, "props_right_widget")
        self.props_left_form = root.findChild(QFormLayout, "props_left_form")
        self.props_right_form = root.findChild(QFormLayout, "props_right_form")
        splitter = root.findChild(QSplitter, "main_splitter")
        image_container = root.findChild(QWidget, "image_container")

        # Left side widgets.
        self.chk_rec_ocr_new = root.findChild(QCheckBox, "chk_rec_ocr_new")
        self.chk_rec_legacy = root.findChild(QCheckBox, "chk_rec_legacy")
        self.chk_rec_trocr = root.findChild(QCheckBox, "chk_rec_trocr")
        self.chk_rec_shapes = root.findChild(QCheckBox, "chk_rec_shapes")
        self.btn_run_recognition = root.findChild(QPushButton, "btn_run_recognition")
        self.recognition_status = root.findChild(QLabel, "recognition_status")

        # Right side widgets.
        self.name_edit = root.findChild(QLineEdit, "name_edit")
        self.list_m_new = root.findChild(QListWidget, "list_m_new")
        self.list_m_legacy = root.findChild(QListWidget, "list_m_legacy")
        self.list_m_trocr = root.findChild(QListWidget, "list_m_trocr")
        self.list_m_shapes = root.findChild(QListWidget, "list_m_shapes")
        self.btn_add = root.findChild(QPushButton, "btn_add")
        self.btn_delete = root.findChild(QPushButton, "btn_delete")
        self.element_list = root.findChild(QListWidget, "element_list")
        self.type_combo = root.findChild(QComboBox, "type_combo")
        self.content_edit = root.findChild(QLineEdit, "content_edit")
        self.btn_browse_icon = root.findChild(QPushButton, "btn_browse_icon")
        self.bbox_x = root.findChild(QDoubleSpinBox, "bbox_x")
        self.bbox_y = root.findChild(QDoubleSpinBox, "bbox_y")
        self.bbox_w = root.findChild(QDoubleSpinBox, "bbox_w")
        self.bbox_h = root.findChild(QDoubleSpinBox, "bbox_h")
        self.divider_orientation = root.findChild(QComboBox, "divider_orientation")
        self.divider_thickness = root.findChild(QDoubleSpinBox, "divider_thickness")
        self.text_offset_x = root.findChild(QDoubleSpinBox, "text_offset_x")
        self.text_offset_y = root.findChild(QDoubleSpinBox, "text_offset_y")
        self.text_angle = root.findChild(QDoubleSpinBox, "text_angle")
        self.text_size_rel_key = root.findChild(QDoubleSpinBox, "text_size_rel_key")
        self.btn_ok = root.findChild(QPushButton, "btn_ok")
        self.btn_cancel = root.findChild(QPushButton, "btn_cancel")

        required = [
            self.right_panel, self.props_group, self.props_left_widget, self.props_right_widget,
            self.props_left_form, self.props_right_form, splitter, image_container,
            self.chk_rec_ocr_new, self.chk_rec_legacy, self.chk_rec_trocr, self.chk_rec_shapes,
            self.btn_run_recognition, self.recognition_status, self.name_edit,
            self.list_m_new, self.list_m_legacy, self.list_m_trocr, self.list_m_shapes,
            self.btn_add, self.btn_delete, self.element_list, self.type_combo,
            self.content_edit, self.btn_browse_icon, self.bbox_x, self.bbox_y, self.bbox_w, self.bbox_h,
            self.divider_orientation, self.divider_thickness, self.text_offset_x, self.text_offset_y,
            self.text_angle, self.text_size_rel_key, self.btn_ok, self.btn_cancel,
        ]
        if any(w is None for w in required):
            raise RuntimeError("UI is missing required widgets for ElementEditorDialog")

        # Place custom image widget into UI placeholder.
        image_layout = QVBoxLayout(image_container)
        image_layout.setContentsMargins(0, 0, 0, 0)
        self.image_widget = KeyImageWidget()
        self.image_widget.set_image(self.key_image)
        self.image_widget.set_elements(self.elements)
        self.image_widget.element_selected.connect(self._on_element_selected)
        self.image_widget.bbox_changed.connect(self._on_bbox_changed)
        self.image_widget.text_transform_changed.connect(self._on_text_transform_changed)
        image_layout.addWidget(self.image_widget, 1)

        # Keep previous runtime visual tweaks.
        self.name_edit.setText(self.key.name or "")
        for w in [self.list_m_new, self.list_m_legacy, self.list_m_trocr, self.list_m_shapes]:
            w.setSelectionMode(QListWidget.SingleSelection)
            w.setMinimumHeight(104)
            w.setMinimumWidth(0)
            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            w.setStyleSheet("QListWidget::item { padding: 5px 2px; }")
        self.element_list.setMinimumHeight(110)
        self.element_list.setStyleSheet("QListWidget::item { padding: 6px 2px; }")
        self.btn_browse_icon.setFixedWidth(30)

        self.props_left_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.props_right_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.props_left_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.props_right_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        # Configure controls (ranges/choices) and bind signals.
        if self.type_combo.count() == 0:
            self.type_combo.addItems(["text", "icon", "divider"])
        if self.divider_orientation.count() == 0:
            self.divider_orientation.addItems(["vertical", "horizontal"])
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        self.content_edit.textChanged.connect(self._on_content_changed)
        self.btn_browse_icon.clicked.connect(self._browse_icon_file)
        self.divider_orientation.currentTextChanged.connect(self._on_divider_params_changed)
        self.divider_thickness.valueChanged.connect(self._on_divider_params_changed)
        self.text_offset_x.valueChanged.connect(self._on_text_transform_params_changed)
        self.text_offset_y.valueChanged.connect(self._on_text_transform_params_changed)
        self.text_angle.valueChanged.connect(self._on_text_transform_params_changed)
        self.text_size_rel_key.valueChanged.connect(self._on_text_transform_params_changed)
        self.btn_add.clicked.connect(self._add_element)
        self.btn_delete.clicked.connect(self._delete_element)
        self.element_list.currentRowChanged.connect(self._on_list_selection)
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_run_recognition.clicked.connect(self._run_selected_recognition)

        self.list_m_new.currentRowChanged.connect(lambda row: self._on_method_row_changed("ocr_new", row))
        self.list_m_legacy.currentRowChanged.connect(lambda row: self._on_method_row_changed("ocr_legacy", row))
        self.list_m_trocr.currentRowChanged.connect(lambda row: self._on_method_row_changed("trocr", row))
        self.list_m_shapes.currentRowChanged.connect(lambda row: self._on_method_row_changed("icon_divider", row))
        self.list_m_new.itemDoubleClicked.connect(lambda item: self._on_method_item_double_clicked("ocr_new", item))
        self.list_m_legacy.itemDoubleClicked.connect(lambda item: self._on_method_item_double_clicked("ocr_legacy", item))
        self.list_m_trocr.itemDoubleClicked.connect(lambda item: self._on_method_item_double_clicked("trocr", item))
        self.list_m_shapes.itemDoubleClicked.connect(lambda item: self._on_method_item_double_clicked("icon_divider", item))

        self.bbox_x.setRange(0, 1)
        self.bbox_x.setSingleStep(0.05)
        self.bbox_x.setDecimals(2)
        self.bbox_x.valueChanged.connect(self._on_bbox_spinbox_changed)
        self.bbox_y.setRange(0, 1)
        self.bbox_y.setSingleStep(0.05)
        self.bbox_y.setDecimals(2)
        self.bbox_y.valueChanged.connect(self._on_bbox_spinbox_changed)
        self.bbox_w.setRange(0.05, 1)
        self.bbox_w.setSingleStep(0.05)
        self.bbox_w.setDecimals(2)
        self.bbox_w.valueChanged.connect(self._on_bbox_spinbox_changed)
        self.bbox_h.setRange(0.05, 1)
        self.bbox_h.setSingleStep(0.05)
        self.bbox_h.setDecimals(2)
        self.bbox_h.valueChanged.connect(self._on_bbox_spinbox_changed)
        self.divider_thickness.setRange(0.01, 0.5)
        self.divider_thickness.setSingleStep(0.01)
        self.divider_thickness.setDecimals(2)
        self.text_offset_x.setRange(-1.0, 1.0)
        self.text_offset_x.setSingleStep(0.01)
        self.text_offset_x.setDecimals(2)
        self.text_offset_y.setRange(-1.0, 1.0)
        self.text_offset_y.setSingleStep(0.01)
        self.text_offset_y.setDecimals(2)
        self.text_angle.setRange(-180.0, 180.0)
        self.text_angle.setSingleStep(1.0)
        self.text_angle.setDecimals(1)
        self.text_size_rel_key.setRange(0.03, 0.6)
        self.text_size_rel_key.setSingleStep(0.01)
        self.text_size_rel_key.setDecimals(2)

        splitter.setSizes([560, 540])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)

        self._stabilize_right_panel_size()
        self._update_properties(-1)

    def _update_method_columns(self):
        """Populate three read-only columns with results from each recognition method."""
        type_tag = {"text": "T", "icon": "I", "divider": "D"}
        cols = {
            "ocr_new": self.list_m_new,
            "ocr_legacy": self.list_m_legacy,
            "trocr": self.list_m_trocr,
            "icon_divider": self.list_m_shapes,
        }
        for name, widget in cols.items():
            widget.clear()
            for i, elem in enumerate(self.method_elements.get(name, []) or []):
                etype = str(getattr(elem, "type", "") or "text")
                content = str(getattr(elem, "content", "") or "").strip()
                if not content:
                    continue
                tag = type_tag.get(etype.lower(), "?")
                item = QListWidgetItem(f"[{tag}] {content}")
                item.setData(Qt.ItemDataRole.UserRole, i)
                widget.addItem(item)
            if widget.count() == 0:
                widget.addItem("(none)")

    def _set_method_elements(self, method_name: str, elements: List[KeyElement]):
        """Update one method column without changing final manual elements."""
        self.method_elements[method_name] = list(elements or [])
        self._update_method_columns()
        self.image_widget.set_focus_element(None)

    def _on_method_row_changed(self, method_name: str, row: int):
        """Focus selected method candidate on key image."""
        # Keep method lists mutually exclusive for clearer focus behavior.
        sender = self.sender()
        for w in [self.list_m_new, self.list_m_legacy, self.list_m_trocr, self.list_m_shapes]:
            if w is sender:
                continue
            w.blockSignals(True)
            w.clearSelection()
            w.blockSignals(False)

        if row < 0:
            self.image_widget.set_focus_element(None)
            return
        entries = self.method_elements.get(method_name, []) or []
        sender = self.sender()
        item = sender.currentItem() if hasattr(sender, "currentItem") else None
        entry_idx = int(item.data(Qt.ItemDataRole.UserRole)) if item is not None and item.data(Qt.ItemDataRole.UserRole) is not None else row
        if entry_idx < 0 or entry_idx >= len(entries):
            self.image_widget.set_focus_element(None)
            return
        self.image_widget.set_focus_element(entries[entry_idx])

    @staticmethod
    def _elements_equivalent(a: KeyElement, b: KeyElement) -> bool:
        ab = getattr(a, "bbox", None) or [0.0, 0.0, 0.0, 0.0]
        bb = getattr(b, "bbox", None) or [0.0, 0.0, 0.0, 0.0]
        return (
            str(getattr(a, "type", "")) == str(getattr(b, "type", ""))
            and str(getattr(a, "content", "")) == str(getattr(b, "content", ""))
            and abs(float(ab[0]) - float(bb[0])) < 0.01
            and abs(float(ab[1]) - float(bb[1])) < 0.01
            and abs(float(ab[2]) - float(bb[2])) < 0.01
            and abs(float(ab[3]) - float(bb[3])) < 0.01
        )

    def _on_method_item_double_clicked(self, method_name: str, item: QListWidgetItem):
        """Copy selected method candidate to final Elements list."""
        idx = int(item.data(Qt.ItemDataRole.UserRole)) if item.data(Qt.ItemDataRole.UserRole) is not None else -1
        entries = self.method_elements.get(method_name, []) or []
        if idx < 0 or idx >= len(entries):
            return
        src = entries[idx]
        elem = KeyElement(
            type=str(getattr(src, "type", "text") or "text"),
            content=str(getattr(src, "content", "") or ""),
            position=tuple(getattr(src, "position", (0.5, 0.5))),
            size=getattr(src, "size", 0.5),
            bbox=list(getattr(src, "bbox", [0.1, 0.1, 0.8, 0.8])),
        )
        quad = getattr(src, "quad", None)
        if quad:
            elem.quad = [list(p) for p in quad]
        if hasattr(src, "divider_orientation"):
            elem.divider_orientation = getattr(src, "divider_orientation")
        if hasattr(src, "divider_thickness"):
            divider_thickness = getattr(src, "divider_thickness")
            elem.divider_thickness = (float(divider_thickness) if divider_thickness is not None else None)
        if str(getattr(elem, "type", "")).lower() == "text":
            self.image_widget._ensure_text_transform_attrs(elem)
            for attr in ["text_offset_x", "text_offset_y", "text_angle_deg", "text_size_rel_key"]:
                if hasattr(src, attr):
                    setattr(elem, attr, float(getattr(src, attr)))
        for ex in self.elements:
            if self._elements_equivalent(ex, elem):
                return
        self.elements.append(elem)
        self._update_list()
        self.element_list.setCurrentRow(len(self.elements) - 1)
        self.image_widget.set_selected(len(self.elements) - 1)
        self.image_widget.set_focus_element(None)
        self.image_widget.update()

    def _update_list(self):
        type_tag = {"text": "T", "icon": "I", "divider": "D"}
        self.element_list.clear()
        for i, elem in enumerate(self.elements):
            type_str = elem.type if hasattr(elem, 'type') else "text"
            content = elem.content if hasattr(elem, 'content') else ""
            tag = type_tag.get(str(type_str).lower(), "?")
            item = QListWidgetItem(f"[{tag}] {content}")
            self.element_list.addItem(item)
        self.image_widget.set_elements(self.elements)

    @staticmethod
    def _set_form_row_visible(form: QFormLayout, field: QWidget, visible: bool):
        label = form.labelForField(field)
        if label is not None:
            label.setVisible(visible)
        field.setVisible(visible)

    def _apply_type_visibility(self, etype: str):
        et = str(etype or "").lower()
        is_text = et == "text"
        is_icon = et == "icon"
        is_divider = et == "divider"

        self._set_form_row_visible(self.props_left_form, self.content_edit.parentWidget(), is_text or is_icon)
        self._set_form_row_visible(self.props_left_form, self.divider_orientation, is_divider)
        self._set_form_row_visible(self.props_right_form, self.divider_thickness, is_divider)
        self._set_form_row_visible(self.props_right_form, self.text_offset_x.parentWidget(), is_text)
        self._set_form_row_visible(self.props_left_form, self.text_angle, is_text)
        self._set_form_row_visible(self.props_right_form, self.text_size_rel_key, is_text)
        self.btn_browse_icon.setVisible(is_icon)

    def _stabilize_right_panel_size(self):
        """Keep right panel geometry stable when type-specific rows are shown/hidden."""
        if not hasattr(self, "right_panel") or not hasattr(self, "props_group"):
            return
        max_h = 0
        for et in ("text", "icon", "divider"):
            self._apply_type_visibility(et)
            self.props_group.updateGeometry()
            max_h = max(max_h, int(self.props_group.sizeHint().height()))
        if max_h > 0:
            self.props_group.setMinimumHeight(max_h)

    def _on_list_selection(self, row: int):
        self.image_widget.set_focus_element(None)
        self.image_widget.set_selected(row)
        self._update_properties(row)

    def _on_element_selected(self, index: int):
        self.image_widget.set_focus_element(None)
        self.element_list.setCurrentRow(index)
        self._update_properties(index)

    def _update_properties(self, index: int):
        # Disable properties if no element selected
        has_element = index >= 0 and index < len(self.elements)
        self.type_combo.setEnabled(has_element)
        self.content_edit.setEnabled(has_element)
        self.btn_browse_icon.setEnabled(False)
        self.divider_orientation.setEnabled(False)
        self.divider_thickness.setEnabled(False)
        self.text_offset_x.setEnabled(False)
        self.text_offset_y.setEnabled(False)
        self.text_angle.setEnabled(False)
        self.text_size_rel_key.setEnabled(False)
        self.bbox_x.setEnabled(has_element)
        self.bbox_y.setEnabled(has_element)
        self.bbox_w.setEnabled(has_element)
        self.bbox_h.setEnabled(has_element)

        if not has_element:
            self.content_edit.clear()
            self._apply_type_visibility("text")
            return

        elem = self.elements[index]

        # Block signals while updating
        self.type_combo.blockSignals(True)
        self.content_edit.blockSignals(True)
        self.divider_orientation.blockSignals(True)
        self.divider_thickness.blockSignals(True)
        self.bbox_x.blockSignals(True)
        self.bbox_y.blockSignals(True)
        self.bbox_w.blockSignals(True)
        self.bbox_h.blockSignals(True)
        self.text_offset_x.blockSignals(True)
        self.text_offset_y.blockSignals(True)
        self.text_angle.blockSignals(True)
        self.text_size_rel_key.blockSignals(True)

        etype = elem.type if hasattr(elem, 'type') else "text"
        self._apply_type_visibility(etype)
        self.type_combo.setCurrentText(etype)
        self.content_edit.setText(elem.content if hasattr(elem, 'content') else "")
        if etype == "icon":
            self.btn_browse_icon.setEnabled(True)
        if etype == "divider":
            self.divider_orientation.setEnabled(True)
            self.divider_thickness.setEnabled(True)
            ori = str(getattr(elem, "divider_orientation", "vertical") or "vertical")
            if ori not in {"vertical", "horizontal"}:
                ori = "vertical"
            self.divider_orientation.setCurrentText(ori)
            self.divider_thickness.setValue(float(getattr(elem, "divider_thickness", 0.08)))
        else:
            self.divider_orientation.setCurrentText("vertical")
            self.divider_thickness.setValue(0.08)

        if etype == "text":
            self.image_widget._ensure_text_transform_attrs(elem)
            self.text_offset_x.setEnabled(True)
            self.text_offset_y.setEnabled(True)
            self.text_angle.setEnabled(True)
            self.text_size_rel_key.setEnabled(True)
            self.text_offset_x.setValue(float(getattr(elem, "text_offset_x", 0.0)))
            self.text_offset_y.setValue(float(getattr(elem, "text_offset_y", 0.0)))
            self.text_angle.setValue(float(getattr(elem, "text_angle_deg", 0.0)))
            self.text_size_rel_key.setValue(float(getattr(elem, "text_size_rel_key", 0.12)))
        else:
            self.text_offset_x.setValue(0.0)
            self.text_offset_y.setValue(0.0)
            self.text_angle.setValue(0.0)
            self.text_size_rel_key.setValue(0.12)

        if hasattr(elem, 'bbox') and elem.bbox:
            self.bbox_x.setValue(elem.bbox[0])
            self.bbox_y.setValue(elem.bbox[1])
            self.bbox_w.setValue(elem.bbox[2])
            self.bbox_h.setValue(elem.bbox[3])
        else:
            self.bbox_x.setValue(0.1)
            self.bbox_y.setValue(0.1)
            self.bbox_w.setValue(0.8)
            self.bbox_h.setValue(0.8)

        self.type_combo.blockSignals(False)
        self.content_edit.blockSignals(False)
        self.divider_orientation.blockSignals(False)
        self.divider_thickness.blockSignals(False)
        self.bbox_x.blockSignals(False)
        self.bbox_y.blockSignals(False)
        self.bbox_w.blockSignals(False)
        self.bbox_h.blockSignals(False)
        self.text_offset_x.blockSignals(False)
        self.text_offset_y.blockSignals(False)
        self.text_angle.blockSignals(False)
        self.text_size_rel_key.blockSignals(False)

    def _on_type_changed(self, type_str: str):
        index = self.element_list.currentRow()
        if index >= 0 and index < len(self.elements):
            elem = self.elements[index]
            elem.type = type_str
            if type_str == "divider":
                ori = str(getattr(elem, "divider_orientation", "vertical") or "vertical")
                elem.divider_orientation = ori
                elem.divider_thickness = float(getattr(elem, "divider_thickness", 0.08))
                elem.content = f"divider_{ori}"
            elif type_str == "icon" and str(getattr(elem, "content", "")).startswith("divider_"):
                elem.content = ""
            self._update_list()
            self.element_list.setCurrentRow(index)
            self._update_properties(index)

    def _on_content_changed(self, content: str):
        index = self.element_list.currentRow()
        if index >= 0 and index < len(self.elements):
            self.elements[index].content = content
            self._update_list()
            self.element_list.setCurrentRow(index)
            self.image_widget.update()

    def _browse_icon_file(self):
        index = self.element_list.currentRow()
        if index < 0 or index >= len(self.elements):
            return
        elem = self.elements[index]
        if str(getattr(elem, "type", "")).lower() != "icon":
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Icon File",
            "effects/manual_icons",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.svg)",
        )
        if not path:
            return
        elem.content = path.replace("\\", "/")
        self._update_list()
        self.element_list.setCurrentRow(index)
        self._update_properties(index)
        self.image_widget.update()

    def _on_divider_params_changed(self):
        index = self.element_list.currentRow()
        if index < 0 or index >= len(self.elements):
            return
        elem = self.elements[index]
        if str(getattr(elem, "type", "")).lower() != "divider":
            return
        ori = str(self.divider_orientation.currentText() or "vertical")
        th = float(self.divider_thickness.value())
        elem.divider_orientation = ori
        elem.divider_thickness = th
        elem.content = f"divider_{ori}"
        self._update_list()
        self.element_list.setCurrentRow(index)
        self.image_widget.update()

    def _on_text_transform_params_changed(self):
        index = self.element_list.currentRow()
        if index < 0 or index >= len(self.elements):
            return
        elem = self.elements[index]
        if str(getattr(elem, "type", "")).lower() != "text":
            return
        self.image_widget._ensure_text_transform_attrs(elem)
        elem.text_offset_x = float(self.text_offset_x.value())
        elem.text_offset_y = float(self.text_offset_y.value())
        elem.text_angle_deg = float(self.text_angle.value())
        elem.text_size_rel_key = float(self.text_size_rel_key.value())
        self.image_widget.update()

    def _on_bbox_spinbox_changed(self):
        index = self.element_list.currentRow()
        if index >= 0 and index < len(self.elements):
            elem = self.elements[index]
            elem.bbox = [
                self.bbox_x.value(),
                self.bbox_y.value(),
                self.bbox_w.value(),
                self.bbox_h.value()
            ]
            if hasattr(elem, "quad"):
                elem.quad = None
            self.image_widget.update()

    def _on_bbox_changed(self, index: int, bbox: list):
        if index >= 0 and index < len(self.elements):
            elem = self.elements[index]
            if hasattr(elem, "quad"):
                elem.quad = None
            self._update_properties(index)

    def _on_text_transform_changed(self, index: int, offset_x: float, offset_y: float, angle_deg: float):
        if index < 0 or index >= len(self.elements):
            return
        elem = self.elements[index]
        if str(getattr(elem, "type", "")).lower() != "text":
            return
        self.image_widget._ensure_text_transform_attrs(elem)
        elem.text_offset_x = float(offset_x)
        elem.text_offset_y = float(offset_y)
        elem.text_angle_deg = float(angle_deg)
        if index == self.element_list.currentRow():
            self._update_properties(index)

    def _add_element(self):
        elem = KeyElement(
            type="text",
            content="",
            position=(0.5, 0.5),
            size=0.5
        )
        # Default bbox covering center of key
        elem.bbox = [0.2, 0.2, 0.6, 0.6]
        self.image_widget._ensure_text_transform_attrs(elem)
        self.elements.append(elem)
        self._update_list()
        # Select the new element to show its bbox
        self.element_list.setCurrentRow(len(self.elements) - 1)
        self.image_widget.set_selected(len(self.elements) - 1)
        self.image_widget.update()

    def _delete_element(self):
        index = self.element_list.currentRow()
        if index >= 0 and index < len(self.elements):
            del self.elements[index]
            self._update_list()
            if self.elements:
                self.element_list.setCurrentRow(min(index, len(self.elements) - 1))

    def _run_selected_recognition(self):
        """Run only recognition backends selected by checkboxes."""
        jobs = []
        if self.chk_rec_ocr_new.isChecked():
            jobs.append(("OCR New", self._auto_detect_ocr_new))
        if self.chk_rec_legacy.isChecked():
            jobs.append(("EasyOCR Legacy", self._auto_detect_easyocr))
        if self.chk_rec_trocr.isChecked():
            jobs.append(("TrOCR", self._auto_detect_trocr))
        if self.chk_rec_shapes.isChecked():
            jobs.append(("Detect Icon/Divider", self._detect_icon_and_divider))
        if not jobs:
            self.recognition_status.setText("Recognition status: no methods selected")
            return

        self.btn_run_recognition.setEnabled(False)
        try:
            total = len(jobs)
            for idx, (name, fn) in enumerate(jobs, start=1):
                self.recognition_status.setText(f"Recognition status: [{idx}/{total}] running {name}...")
                QApplication.processEvents()
                fn()
            self.recognition_status.setText(f"Recognition status: completed ({total} method(s))")
        except Exception as e:
            self.recognition_status.setText(f"Recognition status: failed ({e})")
            raise
        finally:
            self.btn_run_recognition.setEnabled(True)

    def _auto_detect_easyocr(self):
        """Detect text with legacy EasyOCR and update only method column."""
        reader = get_ocr_reader()
        if reader is None:
            QMessageBox.warning(
                self, "Auto Detect",
                "EasyOCR not available. Please install it with:\npip install easyocr"
            )
            return

        h, w = self.key_image.shape[:2]
        new_elements = []

        try:
            # Preprocess: enhance contrast for better OCR
            gray = cv2.cvtColor(self.key_image, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            # Convert back to BGR for EasyOCR
            processed = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)

            # Use EasyOCR with preprocessed image
            results = reader.readtext(processed, detail=1)

            print(f"EasyOCR found {len(results)} regions for key (image {w}x{h}):")

            # Add ALL results - no filtering, so user can see all bboxes
            for (bbox_pts, text, conf) in results:
                print(f"  '{text}' conf={conf:.2f}")

                # bbox_pts is [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
                x1 = int(min(p[0] for p in bbox_pts))
                y1 = int(min(p[1] for p in bbox_pts))
                x2 = int(max(p[0] for p in bbox_pts))
                y2 = int(max(p[1] for p in bbox_pts))

                # Convert to relative bbox [x, y, w, h]
                rel_bbox = [x1/w, y1/h, (x2-x1)/w, (y2-y1)/h]

                # Show confidence in content for debugging
                content = text.strip() if text.strip() else "?"
                display_text = f"{content} ({conf:.0%})"

                elem = KeyElement(
                    type="text",
                    content=content,
                    position=(rel_bbox[0] + rel_bbox[2]/2, rel_bbox[1] + rel_bbox[3]/2),
                    size=max(rel_bbox[2], rel_bbox[3])
                )
                elem.bbox = rel_bbox
                elem.quad = [[float(p[0]) / w, float(p[1]) / h] for p in bbox_pts]
                self.image_widget._ensure_text_transform_attrs(elem)
                new_elements.append(elem)

        except Exception as e:
            QMessageBox.warning(
                self, "Auto Detect",
                f"Error during detection: {e}"
            )
            return

        self._set_method_elements("ocr_legacy", new_elements)

    def _auto_detect_ocr_new(self):
        """Detect text with OCR New and update only method column."""
        if self.full_image is None:
            QMessageBox.information(
                self,
                "OCR New",
                "Original full image is not available in this dialog.\nUsing legacy OCR is recommended here.",
            )
            return

        reader = get_ocr_reader()
        if reader is None:
            QMessageBox.warning(
                self, "OCR New",
                "EasyOCR not available. Please install it with:\npip install easyocr"
            )
            return

        try:
            pipeline = KeyOCRPipeline(
                easyocr_reader=reader,
                # Keep manual OCR New lightweight/stable. TrOCR is a separate button.
                trocr_fn=None,
                use_trocr_fallback=False,
                debug=False,
            )
            best, _ = pipeline.recognize_key(self.full_image, self.key)
        except Exception as e:
            print("[OCR New] detection error:")
            print(traceback.format_exc())
            QMessageBox.warning(self, "OCR New", f"Error during detection: {e}")
            return

        if best is None or not best.text:
            self._set_method_elements("ocr_new", [])
            return

        elem = KeyElement(type="text", content=best.text, position=(0.5, 0.5), size=0.6)
        elem.bbox = [0.1, 0.1, 0.8, 0.8]
        self.image_widget._ensure_text_transform_attrs(elem)
        self._set_method_elements("ocr_new", [elem])

    def _auto_detect_trocr(self):
        """Detect text with TrOCR and update only method column."""
        text = recognize_with_trocr(self.key_image)

        if text:
            elem = KeyElement(
                type="text",
                content=text,
                position=(0.5, 0.5),
                size=0.6
            )
            elem.bbox = [0.1, 0.1, 0.8, 0.8]
            self.image_widget._ensure_text_transform_attrs(elem)
            self._set_method_elements("trocr", [elem])
        else:
            self._set_method_elements("trocr", [])

    def _detect_icon_and_divider(self):
        """Detect non-text symbols and update only method column."""
        h, w = self.key_image.shape[:2]
        if h < 12 or w < 12:
            return

        gray = cv2.cvtColor(self.key_image, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(blur)

        # Binary for bright marks on dark keycaps.
        _, bw = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(bw) > 160:
            bw = cv2.bitwise_not(bw)

        # Build mask of existing text boxes to avoid duplicating OCR detections.
        text_mask = np.zeros((h, w), dtype=np.uint8)
        for elem in self.elements:
            if getattr(elem, "type", "") != "text" or not elem.bbox:
                continue
            rx, ry, rw, rh = elem.bbox
            x1 = max(0, int(rx * w))
            y1 = max(0, int(ry * h))
            x2 = min(w, int((rx + rw) * w))
            y2 = min(h, int((ry + rh) * h))
            if x2 > x1 and y2 > y1:
                cv2.rectangle(text_mask, (x1, y1), (x2, y2), 255, -1)
        text_mask = cv2.dilate(text_mask, np.ones((3, 3), np.uint8), iterations=1)

        # 1) Divider detection via probabilistic Hough.
        divider_added = 0
        detected: List[KeyElement] = []
        divider_mask = np.zeros((h, w), dtype=np.uint8)
        edges = cv2.Canny(enhanced, 40, 120)
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=max(18, int(0.15 * max(h, w))),
            minLineLength=int(0.42 * h),
            maxLineGap=5,
        )
        if lines is not None:
            best_line = None
            best_len = 0.0
            for line in lines[:, 0]:
                x1, y1, x2, y2 = [int(v) for v in line]
                dx, dy = abs(x2 - x1), abs(y2 - y1)
                if dy < dx * 2:  # prefer near-vertical lines
                    continue
                length = float(np.hypot(x2 - x1, y2 - y1))
                if length > best_len:
                    best_len = length
                    best_line = (x1, y1, x2, y2)
            if best_line is not None:
                x1, y1, x2, y2 = best_line
                cv2.line(divider_mask, (x1, y1), (x2, y2), 255, thickness=3)
                rx = min(x1, x2) / w
                ry = min(y1, y2) / h
                rw_rel = max(2, abs(x2 - x1) + 3) / w
                rh_rel = max(4, abs(y2 - y1) + 3) / h
                detected.append(
                    KeyElement(
                        type="divider",
                        content="divider_vertical",
                        position=(rx + rw_rel / 2, ry + rh_rel / 2),
                        size=max(rw_rel, rh_rel),
                        bbox=[rx, ry, rw_rel, rh_rel],
                    )
                )
                detected[-1].divider_orientation = "vertical"
                detected[-1].divider_thickness = 0.08
                divider_added = 1

        # 2) Icon candidates from non-text, non-divider connected contours.
        content = cv2.bitwise_and(bw, cv2.bitwise_not(text_mask))
        if divider_added:
            content = cv2.bitwise_and(content, cv2.bitwise_not(cv2.dilate(divider_mask, np.ones((5, 5), np.uint8), 1)))

        content = cv2.morphologyEx(content, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        content = cv2.morphologyEx(content, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

        contours, _ = cv2.findContours(content, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        icon_added = 0

        icons_dir = os.path.join("effects", "manual_icons")
        os.makedirs(icons_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        for idx, contour in enumerate(contours):
            area = cv2.contourArea(contour)
            if area < 25 or area > 0.28 * (w * h):
                continue

            x, y, cw, ch = cv2.boundingRect(contour)
            if cw < 6 or ch < 6:
                continue

            aspect = cw / float(max(1, ch))
            if aspect < 0.25 or aspect > 3.5:
                continue

            # Reject obvious text-like long strips.
            if cw > int(0.5 * w) and ch < int(0.2 * h):
                continue

            pad = 2
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(w, x + cw + pad)
            y2 = min(h, y + ch + pad)
            crop = self.key_image[y1:y2, x1:x2].copy()

            local_mask = np.zeros((y2 - y1, x2 - x1), dtype=np.uint8)
            shifted = contour - np.array([[x1, y1]])
            cv2.drawContours(local_mask, [shifted], -1, 255, thickness=-1)

            rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
            rgba[:, :, 3] = local_mask

            icon_name = f"key_{self.key.id}_icon_{stamp}_{idx}.png"
            icon_path = os.path.join(icons_dir, icon_name)
            cv2.imwrite(icon_path, rgba)

            rel_x = x1 / float(w)
            rel_y = y1 / float(h)
            rel_w = (x2 - x1) / float(w)
            rel_h = (y2 - y1) / float(h)

            detected.append(
                KeyElement(
                    type="icon",
                    content=icon_path.replace("\\", "/"),
                    position=(rel_x + rel_w / 2, rel_y + rel_h / 2),
                    size=max(rel_w, rel_h),
                    bbox=[rel_x, rel_y, rel_w, rel_h],
                )
            )
            icon_added += 1

        self._set_method_elements("icon_divider", detected)

    def get_result(self) -> Tuple[str, List[KeyElement]]:
        """Get the edited key name and elements."""
        return self.name_edit.text(), self.elements

