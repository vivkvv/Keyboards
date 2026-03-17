import os
from typing import Dict, List

from ..models import KeyCandidate, KeyElement, KeyboardLayout, KeyStatus, key_element_from_dict, key_element_to_dict


def build_segmentation_payload(image_path: str, image_width: int, image_height: int, keys: List[KeyCandidate]) -> Dict:
    return {
        "type": "segmentation",
        "image": os.path.basename(image_path),
        "image_size": [image_width, image_height],
        "keys": [
            {
                "id": k.id,
                "status": k.status.value,
                "polygon": k.polygon,
                "bbox": list(k.bbox),
                "area": k.area,
                "shape_type": k.shape_type,
                "corner_radius": k.corner_radius,
                "name": k.name,
                "elements": [key_element_to_dict(e) for e in k.elements],
                "recognition_candidates": {
                    method_name: [key_element_to_dict(e) for e in items]
                    for method_name, items in k.recognition_by_method.items()
                },
            }
            for k in keys
        ],
    }


def parse_segmentation_keys(data: Dict) -> List[KeyCandidate]:
    loaded_keys: List[KeyCandidate] = []
    for kd in data.get("keys", []):
        status_raw = kd.get("status", KeyStatus.DRAFT.value)
        try:
            status = KeyStatus(status_raw)
        except Exception:
            status = KeyStatus.DRAFT

        key = KeyCandidate(
            id=int(kd.get("id", len(loaded_keys))),
            status=status,
            polygon=[tuple(p) for p in kd.get("polygon", [])],
            bbox=tuple(kd.get("bbox", [0, 0, 0, 0])),
            area=int(kd.get("area", 0)),
            name=kd.get("name"),
            shape_type=kd.get("shape_type", "free"),
            corner_radius=float(kd.get("corner_radius", 0.0)),
            recognition_by_method={},
        )

        for ed in kd.get("elements", []):
            key.elements.append(key_element_from_dict(ed))

        for method_name, items in (kd.get("recognition_candidates", {}) or {}).items():
            key.recognition_by_method[method_name] = [key_element_from_dict(ed) for ed in (items or [])]

        loaded_keys.append(key)
    return loaded_keys


def build_layout_payload(image_path: str, image_width: int, image_height: int, keys: List[KeyCandidate]) -> Dict:
    layout = KeyboardLayout(
        image_path=os.path.basename(image_path),
        image_size=(image_width, image_height),
        keys=keys,
    )
    return layout.to_dict()
