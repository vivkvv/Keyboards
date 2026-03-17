from typing import List, Optional, Set, Tuple
import math
import os

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap, QPolygon, QPolygonF
from PySide6.QtWidgets import QWidget

from ..models import KeyCandidate, KeyStatus


class ImageWidget(QWidget):
    clicked = Signal(int, int, bool)
    double_clicked = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.image: Optional[QPixmap] = None
        self.keys: List[KeyCandidate] = []
        self.row_guides: List[List[Tuple[int, int]]] = []
        self.problematic_key_ids: Set[int] = set()
        self.selected_keys: List[int] = []
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        self.display_mode = "all"
        self.show_row_guides = True
        self.show_recognized_labels = False
        self.hide_original_labels = False

    def set_image(self, image: np.ndarray):
        h, w, c = image.shape
        bytes_per_line = c * w
        q_image = QImage(image.data, w, h, bytes_per_line, QImage.Format_BGR888)
        self.image = QPixmap.fromImage(q_image)
        self._update_scale()
        self.update()

    def set_keys(self, keys: List[KeyCandidate]):
        self.keys = keys
        self.update()

    def set_row_guides(self, guides: List[List[Tuple[int, int]]]):
        self.row_guides = guides
        self.update()

    def set_problematic_keys(self, key_ids: Set[int]):
        self.problematic_key_ids = set(key_ids)
        self.update()

    def set_selected(self, indices: List[int]):
        self.selected_keys = indices
        self.update()

    def set_display_mode(self, mode: str):
        self.display_mode = mode
        self.update()

    def set_show_row_guides(self, show: bool):
        self.show_row_guides = bool(show)
        self.update()

    def set_show_recognized_labels(self, show: bool):
        self.show_recognized_labels = bool(show)
        self.update()

    def set_hide_original_labels(self, hide: bool):
        self.hide_original_labels = bool(hide)
        self.update()

    def _update_scale(self):
        if not self.image:
            return
        w_scale = self.width() / self.image.width()
        h_scale = self.height() / self.image.height()
        self.scale = min(w_scale, h_scale, 1.0)
        scaled_w = self.image.width() * self.scale
        scaled_h = self.image.height() * self.scale
        self.offset_x = (self.width() - scaled_w) / 2
        self.offset_y = (self.height() - scaled_h) / 2

    def resizeEvent(self, event):
        self._update_scale()
        super().resizeEvent(event)

    def _key_rect(self, key: KeyCandidate) -> QRectF:
        bx, by, bw, bh = key.bbox
        return QRectF(
            self.offset_x + bx * self.scale,
            self.offset_y + by * self.scale,
            bw * self.scale,
            bh * self.scale,
        )

    def _element_rect(self, key: KeyCandidate, elem) -> QRectF:
        key_rect = self._key_rect(key)
        bbox = getattr(elem, "bbox", None) or [0.1, 0.1, 0.8, 0.8]
        return QRectF(
            key_rect.left() + float(bbox[0]) * key_rect.width(),
            key_rect.top() + float(bbox[1]) * key_rect.height(),
            float(bbox[2]) * key_rect.width(),
            float(bbox[3]) * key_rect.height(),
        )

    def _quad_polygon(self, elem):
        quad = getattr(elem, "quad", None)
        if not (isinstance(quad, list) and len(quad) >= 4 and self.image is not None):
            return None
        img_w = self.image.width() * self.scale
        img_h = self.image.height() * self.scale
        pts = [
            QPointF(
                self.offset_x + float(p[0]) * img_w,
                self.offset_y + float(p[1]) * img_h,
            )
            for p in quad[:4]
        ]
        return QPolygonF(pts)

    def _resolve_asset_path(self, asset_path: str) -> str:
        asset_path = os.path.normpath(str(asset_path or "").strip())
        if not asset_path:
            return ""
        if os.path.isabs(asset_path) and os.path.exists(asset_path):
            return asset_path

        candidates = [
            asset_path,
            os.path.join(os.getcwd(), asset_path),
            os.path.join(os.path.dirname(__file__), "..", "..", asset_path),
        ]
        for candidate in candidates:
            candidate = os.path.normpath(candidate)
            if os.path.exists(candidate):
                return candidate
        return asset_path

    def _get_text_geometry(self, key: KeyCandidate, elem) -> Tuple[QPointF, float, float, float]:
        quad_poly = self._quad_polygon(elem)
        if quad_poly is not None:
            pts = list(quad_poly)
            p0, p1, p2, p3 = pts[:4]
            edge_w = max(8.0, math.hypot(p1.x() - p0.x(), p1.y() - p0.y()))
            edge_h = max(
                8.0,
                0.5 * (
                    math.hypot(p3.x() - p0.x(), p3.y() - p0.y())
                    + math.hypot(p2.x() - p1.x(), p2.y() - p1.y())
                ),
            )
            cx = sum(p.x() for p in pts[:4]) / 4.0
            cy = sum(p.y() for p in pts[:4]) / 4.0
            angle_deg = math.degrees(math.atan2(p1.y() - p0.y(), p1.x() - p0.x()))
            center = QPointF(cx, cy)
        else:
            rect = self._element_rect(key, elem)
            center = rect.center()
            angle_deg = 0.0
            edge_w = max(8.0, rect.width())
            edge_h = max(8.0, rect.height())

        key_rect = self._key_rect(key)
        center = QPointF(
            center.x() + float(getattr(elem, "text_offset_x", 0.0)) * key_rect.width(),
            center.y() + float(getattr(elem, "text_offset_y", 0.0)) * key_rect.height(),
        )
        angle_deg += float(getattr(elem, "text_angle_deg", 0.0))
        return center, angle_deg, edge_w, edge_h

    def _draw_recognized_labels(self, painter: QPainter, key: KeyCandidate):
        if not self.image:
            return

        key_rect = self._key_rect(key)
        crop_h_scaled = max(1.0, key_rect.height() * 1.08)
        elems = list(key.elements or [])
        text_elems = [
            elem for elem in elems
            if str(getattr(elem, "type", "")).lower() == "text" and str(getattr(elem, "content", "")).strip()
        ]
        other_elems = [elem for elem in elems if str(getattr(elem, "type", "")).lower() != "text"]

        if self.hide_original_labels and elems:
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(28, 28, 28, 245)))
            if key.polygon:
                points = []
                for px, py in key.polygon:
                    points.append(QPoint(int(px * self.scale + self.offset_x), int(py * self.scale + self.offset_y)))
                painter.drawPolygon(QPolygon(points))
            else:
                painter.drawRect(key_rect)
            painter.restore()

        for elem in other_elems:
            elem_type = str(getattr(elem, "type", "")).lower()
            quad_poly = self._quad_polygon(elem)
            elem_rect = self._element_rect(key, elem)

            if elem_type == "icon":
                icon_path = str(getattr(elem, "content", "")).strip()
                if not icon_path:
                    continue
                icon_path = self._resolve_asset_path(icon_path)
                icon_pixmap = QPixmap(icon_path)
                if icon_pixmap.isNull():
                    continue
                painter.save()
                if not self.hide_original_labels:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(QColor(20, 20, 20, 55)))
                    if quad_poly is not None:
                        painter.drawPolygon(quad_poly)
                    else:
                        painter.drawRect(elem_rect)
                painter.drawPixmap(elem_rect.toRect(), icon_pixmap)
                painter.restore()
                continue

            if elem_type == "divider":
                painter.save()
                orientation = str(getattr(elem, "divider_orientation", "vertical") or "vertical").lower()
                thickness_rel = float(getattr(elem, "divider_thickness", 0.08) or 0.08)
                if orientation == "horizontal":
                    pen_width = max(2, int(elem_rect.height() * thickness_rel))
                    y = elem_rect.center().y()
                    p1 = QPointF(elem_rect.left(), y)
                    p2 = QPointF(elem_rect.right(), y)
                else:
                    pen_width = max(2, int(elem_rect.width() * thickness_rel))
                    x = elem_rect.center().x()
                    p1 = QPointF(x, elem_rect.top())
                    p2 = QPointF(x, elem_rect.bottom())
                painter.setPen(QPen(QColor(245, 245, 245), pen_width))
                painter.drawLine(p1, p2)
                painter.restore()

        for elem in text_elems:
            text = str(getattr(elem, "content", "")).strip()
            quad_poly = self._quad_polygon(elem)
            elem_rect = self._element_rect(key, elem)
            center, angle_deg, edge_w, edge_h = self._get_text_geometry(key, elem)
            size_rel = max(0.03, min(0.6, float(getattr(elem, "text_size_rel_key", 0.12))))
            font_px = max(6, int(size_rel * crop_h_scaled))

            painter.save()
            if not self.hide_original_labels:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(20, 20, 20, 55)))
                if quad_poly is not None:
                    painter.drawPolygon(quad_poly)
                else:
                    painter.drawRect(elem_rect)

            font = QFont("Segoe UI", font_px)
            painter.setFont(font)
            painter.setPen(QPen(QColor(245, 245, 245), 1))
            painter.translate(center)
            painter.rotate(angle_deg)
            draw_w = max(edge_w * 1.35, font_px * max(2.0, len(text) * 0.7))
            draw_h = max(edge_h * 1.2, font_px * 1.5)
            draw_rect = QRectF(-draw_w / 2.0, -draw_h / 2.0, draw_w, draw_h)
            painter.drawText(draw_rect, Qt.AlignCenter, text)
            painter.restore()

    def paintEvent(self, event):
        if not self.image:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        scaled_pixmap = self.image.scaled(
            int(self.image.width() * self.scale),
            int(self.image.height() * self.scale),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        painter.drawPixmap(int(self.offset_x), int(self.offset_y), scaled_pixmap)

        for i, key in enumerate(self.keys):
            is_selected = i in self.selected_keys
            if self.display_mode == "selected" and not is_selected:
                continue
            if self.display_mode == "none":
                continue

            if is_selected:
                pen_color = QColor(255, 0, 0)
                fill_color = QColor(255, 0, 0, 50)
                pen_width = 3
            elif key.status == KeyStatus.APPROVED:
                pen_color = QColor(0, 255, 0)
                fill_color = QColor(0, 255, 0, 30)
                pen_width = 2
            else:
                pen_color = QColor(255, 255, 0)
                fill_color = QColor(255, 255, 0, 20)
                pen_width = 1

            if key.id in self.problematic_key_ids:
                pen_color = QColor(255, 0, 255)
                fill_color = QColor(255, 0, 255, 30)
                pen_width = max(pen_width, 3)

            key_poly = None
            if key.polygon:
                points = []
                for px, py in key.polygon:
                    wx = int(px * self.scale + self.offset_x)
                    wy = int(py * self.scale + self.offset_y)
                    points.append(QPoint(wx, wy))
                key_poly = QPolygon(points)

            if self.hide_original_labels:
                painter.save()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(28, 28, 28, 245)))
                if key_poly is not None:
                    painter.drawPolygon(key_poly)
                else:
                    painter.drawRect(self._key_rect(key))
                painter.restore()

            pen = QPen(pen_color, pen_width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(QBrush(fill_color))

            if key_poly is not None:
                painter.drawPolygon(key_poly)

            if self.show_recognized_labels:
                self._draw_recognized_labels(painter, key)

            if is_selected:
                cx, cy = key.center()
                wx = int(cx * self.scale + self.offset_x)
                wy = int(cy * self.scale + self.offset_y)
                label = key.name or f"#{key.id}"
                painter.setPen(QPen(pen_color))
                painter.drawText(wx - 10, wy + 5, label)

        if self.show_row_guides and self.row_guides and self.display_mode != "none":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for row_idx, row in enumerate(self.row_guides):
                if len(row) < 2:
                    continue
                color = self._row_guide_color(row_idx)
                guide_pen = QPen(color, 2)
                guide_pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(guide_pen)
                points = []
                for px, py in row:
                    wx = int(px * self.scale + self.offset_x)
                    wy = int(py * self.scale + self.offset_y)
                    points.append(QPoint(wx, wy))
                painter.drawPolyline(QPolygon(points))

        painter.end()

    def _row_guide_color(self, index: int) -> QColor:
        palette = [
            QColor(0, 255, 255),
            QColor(255, 120, 0),
            QColor(0, 220, 90),
            QColor(255, 70, 160),
            QColor(80, 160, 255),
            QColor(255, 220, 0),
            QColor(180, 120, 255),
            QColor(255, 80, 80),
        ]
        return palette[index % len(palette)]

    def mousePressEvent(self, event):
        if not self.image or event.button() != Qt.LeftButton:
            return
        wx, wy = event.position().x(), event.position().y()
        ix = int((wx - self.offset_x) / self.scale)
        iy = int((wy - self.offset_y) / self.scale)
        if 0 <= ix < self.image.width() and 0 <= iy < self.image.height():
            ctrl_pressed = event.modifiers() & Qt.KeyboardModifier.ControlModifier
            self.clicked.emit(ix, iy, bool(ctrl_pressed))

    def mouseDoubleClickEvent(self, event):
        if not self.image or event.button() != Qt.LeftButton:
            return
        wx, wy = event.position().x(), event.position().y()
        ix = int((wx - self.offset_x) / self.scale)
        iy = int((wy - self.offset_y) / self.scale)
        if 0 <= ix < self.image.width() and 0 <= iy < self.image.height():
            self.double_clicked.emit(ix, iy)

    def find_key_at_point(self, x: int, y: int) -> Optional[int]:
        for i, key in enumerate(self.keys):
            if key.contains_point(x, y):
                return i
        return None

    def select_key(self, index: int, add_to_selection: bool = False):
        if add_to_selection:
            if index not in self.selected_keys:
                self.selected_keys.append(index)
        else:
            self.selected_keys = [index]
        self.update()
