import numpy as np

from ..element_editor import ElementEditorDialog
from ..models import KeyCandidate, KeyElement


def edit_elements(app) -> None:
    """Open element editor for selected key."""
    if len(app.image_widget.selected_keys) != 1:
        return

    idx = app.image_widget.selected_keys[0]
    if idx >= len(app.keys):
        return

    key = app.keys[idx]

    ox, oy, ow, oh = key.bbox
    if ow <= 0 or oh <= 0:
        return
    if key.polygon and len(key.polygon) >= 3:
        pts = np.array(key.polygon, dtype=np.int32)
        px1 = int(np.min(pts[:, 0]))
        py1 = int(np.min(pts[:, 1]))
        px2 = int(np.max(pts[:, 0])) + 1
        py2 = int(np.max(pts[:, 1])) + 1
    else:
        px1, py1, px2, py2 = ox, oy, ox + ow, oy + oh

    pad = max(3, int(round(0.04 * max(ow, oh))))
    cx1 = max(0, px1 - pad)
    cy1 = max(0, py1 - pad)
    cx2 = min(app.image.shape[1], px2 + pad)
    cy2 = min(app.image.shape[0], py2 + pad)
    cw = max(1, cx2 - cx1)
    ch = max(1, cy2 - cy1)
    key_image = app.image[cy1:cy2, cx1:cx2].copy()

    def map_elem_to_crop(src: KeyElement) -> KeyElement:
        e = KeyElement(type=src.type, content=src.content, position=src.position, size=src.size, bbox=None)
        for k, v in vars(src).items():
            if k in {"type", "content", "position", "size", "bbox", "quad"}:
                continue
            setattr(e, k, v)
        if hasattr(src, "text_offset_x"):
            e.text_offset_x = float(getattr(src, "text_offset_x", 0.0)) * float(app.image.shape[1]) / float(max(1, cw))
        if hasattr(src, "text_offset_y"):
            e.text_offset_y = float(getattr(src, "text_offset_y", 0.0)) * float(app.image.shape[0]) / float(max(1, ch))
        if getattr(src, "bbox", None):
            rx, ry, rw, rh = src.bbox
            ax = ox + rx * ow
            ay = oy + ry * oh
            aw = rw * ow
            ah = rh * oh
            nrx = (ax - cx1) / float(cw)
            nry = (ay - cy1) / float(ch)
            nrw = aw / float(cw)
            nrh = ah / float(ch)
            e.bbox = [nrx, nry, nrw, nrh]
            e.position = (nrx + nrw / 2.0, nry + nrh / 2.0)
            e.size = max(nrw, nrh)
        if hasattr(src, "quad") and getattr(src, "quad"):
            q = []
            for p in getattr(src, "quad"):
                ax = ox + float(p[0]) * ow
                ay = oy + float(p[1]) * oh
                q.append([(ax - cx1) / float(cw), (ay - cy1) / float(ch)])
            e.quad = q
        return e

    def map_elem_from_crop(src: KeyElement) -> KeyElement:
        e = KeyElement(type=src.type, content=src.content, position=src.position, size=src.size, bbox=None)
        for k, v in vars(src).items():
            if k in {"type", "content", "position", "size", "bbox", "quad"}:
                continue
            setattr(e, k, v)
        if hasattr(src, "text_offset_x"):
            e.text_offset_x = float(getattr(src, "text_offset_x", 0.0)) * float(max(1, cw)) / float(app.image.shape[1])
        if hasattr(src, "text_offset_y"):
            e.text_offset_y = float(getattr(src, "text_offset_y", 0.0)) * float(max(1, ch)) / float(app.image.shape[0])
        if getattr(src, "bbox", None):
            rx, ry, rw, rh = src.bbox
            ax = cx1 + rx * cw
            ay = cy1 + ry * ch
            aw = rw * cw
            ah = rh * ch
            orx = (ax - ox) / float(max(1, ow))
            ory = (ay - oy) / float(max(1, oh))
            orw = aw / float(max(1, ow))
            orh = ah / float(max(1, oh))
            e.bbox = [orx, ory, orw, orh]
            e.position = (orx + orw / 2.0, ory + orh / 2.0)
            e.size = max(orw, orh)
        if hasattr(src, "quad") and getattr(src, "quad"):
            q = []
            for p in getattr(src, "quad"):
                ax = cx1 + float(p[0]) * cw
                ay = cy1 + float(p[1]) * ch
                q.append([(ax - ox) / float(max(1, ow)), (ay - oy) / float(max(1, oh))])
            e.quad = q
        return e

    dialog_key = KeyCandidate(
        id=key.id,
        status=key.status,
        polygon=list(key.polygon),
        bbox=key.bbox,
        elements=[map_elem_to_crop(e) for e in (key.elements or [])],
        name=key.name,
        area=key.area,
        shape_type=key.shape_type,
        corner_radius=key.corner_radius,
    )

    method_elements = {}
    for mname, items in dict(getattr(key, "recognition_by_method", {}) or {}).items():
        method_elements[mname] = [map_elem_to_crop(e) for e in (items or [])]

    dialog = ElementEditorDialog(
        dialog_key,
        key_image,
        app,
        full_image=app.image,
        method_elements=method_elements,
    )
    if dialog.exec():
        name, elements = dialog.get_result()
        key.name = name
        key.elements = [map_elem_from_crop(e) for e in (elements or [])]
        out_methods = {}
        for mname, items in dict(getattr(dialog, "method_elements", {}) or {}).items():
            out_methods[mname] = [map_elem_from_crop(e) for e in (items or [])]
        key.recognition_by_method = out_methods
        app._update_key_list()
        app.image_widget.update()
        app.status_bar.showMessage(f"Updated key {key.name or f'#{key.id}'} with {len(elements)} elements")

