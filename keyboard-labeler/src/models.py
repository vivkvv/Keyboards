"""Data models for keyboard key labeling."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


class KeyStatus(Enum):
    DRAFT = "draft"
    APPROVED = "approved"


@dataclass
class KeyElement:
    """Single element on a key (text or image)."""
    type: str
    content: str
    position: Tuple[float, float]
    size: float | Tuple[float, float]
    bbox: Optional[List[float]] = None
    text_offset_x: float = 0.0
    text_offset_y: float = 0.0
    text_angle_deg: float = 0.0
    text_size_rel_key: float = 0.12
    divider_orientation: Optional[str] = None
    divider_thickness: Optional[float] = None
    quad: Optional[List[List[float]]] = None


def key_element_to_dict(e: KeyElement) -> dict:
    return {
        "type": e.type,
        "content": e.content,
        "position": list(e.position),
        "size": list(e.size) if isinstance(e.size, tuple) else e.size,
        "bbox": e.bbox,
        "text_offset_x": e.text_offset_x,
        "text_offset_y": e.text_offset_y,
        "text_angle_deg": e.text_angle_deg,
        "text_size_rel_key": e.text_size_rel_key,
        "divider_orientation": e.divider_orientation,
        "divider_thickness": e.divider_thickness,
        "quad": e.quad,
    }


def key_element_from_dict(ed: dict) -> KeyElement:
    return KeyElement(
        type=ed["type"],
        content=ed["content"],
        position=tuple(ed["position"]),
        size=tuple(ed["size"]) if isinstance(ed["size"], list) else ed["size"],
        bbox=ed.get("bbox"),
        text_offset_x=float(ed.get("text_offset_x", 0.0)),
        text_offset_y=float(ed.get("text_offset_y", 0.0)),
        text_angle_deg=float(ed.get("text_angle_deg", 0.0)),
        text_size_rel_key=float(ed.get("text_size_rel_key", 0.12)),
        divider_orientation=ed.get("divider_orientation"),
        divider_thickness=(float(ed["divider_thickness"]) if ed.get("divider_thickness") is not None else None),
        quad=ed.get("quad"),
    )


@dataclass
class KeyCandidate:
    """A candidate key detected by segmentation."""
    id: int
    status: KeyStatus = KeyStatus.DRAFT
    polygon: List[Tuple[int, int]] = field(default_factory=list)
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)
    elements: List[KeyElement] = field(default_factory=list)
    name: Optional[str] = None
    area: int = 0
    shape_type: str = "free"
    corner_radius: float = 0.0
    recognition_by_method: Dict[str, List[KeyElement]] = field(default_factory=dict)

    def center(self) -> Tuple[int, int]:
        if not self.polygon:
            return (self.bbox[0] + self.bbox[2] // 2,
                    self.bbox[1] + self.bbox[3] // 2)

        if len(self.polygon) < 3:
            xs = [p[0] for p in self.polygon]
            ys = [p[1] for p in self.polygon]
            return (sum(xs) // len(xs), sum(ys) // len(ys))

        area2 = 0.0
        cx_num = 0.0
        cy_num = 0.0
        n = len(self.polygon)
        for i in range(n):
            x0, y0 = self.polygon[i]
            x1, y1 = self.polygon[(i + 1) % n]
            cross = x0 * y1 - x1 * y0
            area2 += cross
            cx_num += (x0 + x1) * cross
            cy_num += (y0 + y1) * cross

        if abs(area2) < 1e-6:
            xs = [p[0] for p in self.polygon]
            ys = [p[1] for p in self.polygon]
            return (sum(xs) // len(xs), sum(ys) // len(ys))

        cx = cx_num / (3.0 * area2)
        cy = cy_num / (3.0 * area2)
        return (int(round(cx)), int(round(cy)))

    def contains_point(self, x: int, y: int) -> bool:
        import cv2
        import numpy as np
        if not self.polygon:
            bx, by, bw, bh = self.bbox
            return bx <= x <= bx + bw and by <= y <= by + bh
        pts = np.array(self.polygon, dtype=np.int32)
        return cv2.pointPolygonTest(pts, (x, y), False) >= 0


@dataclass
class KeyboardLayout:
    image_path: str
    image_size: Tuple[int, int]
    keys: List[KeyCandidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "image": self.image_path,
            "image_size": list(self.image_size),
            "keys": [
                {
                    "id": k.id,
                    "status": k.status.value,
                    "name": k.name,
                    "polygon": k.polygon,
                    "bbox": list(k.bbox),
                    "shape_type": k.shape_type,
                    "corner_radius": k.corner_radius,
                    "elements": [key_element_to_dict(e) for e in k.elements],
                    "recognition_candidates": {
                        method_name: [key_element_to_dict(e) for e in items]
                        for method_name, items in k.recognition_by_method.items()
                    }
                }
                for k in self.keys
            ]
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KeyboardLayout":
        layout = cls(
            image_path=data["image"],
            image_size=tuple(data["image_size"])
        )
        for kd in data.get("keys", []):
            key = KeyCandidate(
                id=kd["id"],
                status=KeyStatus(kd["status"]),
                name=kd.get("name"),
                polygon=[tuple(p) for p in kd["polygon"]],
                bbox=tuple(kd["bbox"]),
                shape_type=kd.get("shape_type", "free"),
                corner_radius=kd.get("corner_radius", 0.0),
                recognition_by_method={},
            )
            for ed in kd.get("elements", []):
                key.elements.append(key_element_from_dict(ed))
            for method_name, items in (kd.get("recognition_candidates", {}) or {}).items():
                key.recognition_by_method[method_name] = [key_element_from_dict(ed) for ed in (items or [])]
            layout.keys.append(key)
        return layout
