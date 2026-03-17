import os
from datetime import datetime
from typing import List

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from ..element_editor import get_ocr_reader, recognize_with_trocr
from ..key_ocr_pipeline import KeyOCRPipeline
from ..models import KeyCandidate, KeyElement


def merge_method_elements(method_map: dict) -> List[KeyElement]:
    """Merge method-specific OCR elements into one deduplicated list."""
    merged: List[KeyElement] = []
    seen = set()
    for items in method_map.values():
        for e in items or []:
            bbox = getattr(e, "bbox", None) or [0.0, 0.0, 0.0, 0.0]
            key = (
                str(getattr(e, "type", "")),
                str(getattr(e, "content", "")),
                round(float(bbox[0]), 2),
                round(float(bbox[1]), 2),
                round(float(bbox[2]), 2),
                round(float(bbox[3]), 2),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(e)
    return merged


def recognize_key_new(image, key: KeyCandidate, pipeline: KeyOCRPipeline) -> List[KeyElement]:
    out: List[KeyElement] = []
    best, _ = pipeline.recognize_key(image, key)
    if best and best.text:
        elem = KeyElement(type="text", content=best.text, position=(0.5, 0.5), size=0.6)
        elem.bbox = [0.1, 0.1, 0.8, 0.8]
        out.append(elem)
    return out


def recognize_key_legacy(image, key: KeyCandidate, reader) -> List[KeyElement]:
    out: List[KeyElement] = []
    kx, ky, kw, kh = key.bbox
    if kw <= 0 or kh <= 0:
        return out
    key_img = image[ky:ky + kh, kx:kx + kw]
    results = reader.readtext(key_img, detail=1)
    for (bbox_pts, text, conf) in results:
        if conf < 0.3 or not text.strip():
            continue
        x1 = int(min(p[0] for p in bbox_pts))
        y1 = int(min(p[1] for p in bbox_pts))
        x2 = int(max(p[0] for p in bbox_pts))
        y2 = int(max(p[1] for p in bbox_pts))
        rel_x = x1 / kw
        rel_y = y1 / kh
        rel_w = (x2 - x1) / kw
        rel_h = (y2 - y1) / kh
        elem = KeyElement(
            type="text",
            content=text.strip(),
            position=(rel_x + rel_w / 2, rel_y + rel_h / 2),
            size=max(rel_w, rel_h),
        )
        elem.bbox = [rel_x, rel_y, rel_w, rel_h]
        out.append(elem)
    return out


def recognize_key_trocr(image, key: KeyCandidate) -> List[KeyElement]:
    out: List[KeyElement] = []
    kx, ky, kw, kh = key.bbox
    if kw <= 0 or kh <= 0:
        return out
    key_img = image[ky:ky + kh, kx:kx + kw]
    text = recognize_with_trocr(key_img)
    if text:
        elem = KeyElement(type="text", content=text, position=(0.5, 0.5), size=0.6)
        elem.bbox = [0.1, 0.1, 0.8, 0.8]
        out.append(elem)
    return out


def recognize_key_icon_divider(image, key: KeyCandidate) -> List[KeyElement]:
    out: List[KeyElement] = []
    kx, ky, kw, kh = key.bbox
    if kw <= 0 or kh <= 0:
        return out
    key_img = image[ky:ky + kh, kx:kx + kw]
    h, w = key_img.shape[:2]
    if h < 12 or w < 12:
        return out

    gray = cv2.cvtColor(key_img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(blur)
    _, bw = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if np.mean(bw) > 160:
        bw = cv2.bitwise_not(bw)

    text_mask = np.zeros((h, w), dtype=np.uint8)
    for elem in key.elements:
        if getattr(elem, "type", "") != "text" or not getattr(elem, "bbox", None):
            continue
        rx, ry, rw, rh = elem.bbox
        x1 = max(0, int(rx * w))
        y1 = max(0, int(ry * h))
        x2 = min(w, int((rx + rw) * w))
        y2 = min(h, int((ry + rh) * h))
        if x2 > x1 and y2 > y1:
            cv2.rectangle(text_mask, (x1, y1), (x2, y2), 255, -1)
    text_mask = cv2.dilate(text_mask, np.ones((3, 3), np.uint8), iterations=1)

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
            if dy < dx * 2:
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
            out.append(KeyElement(
                type="divider",
                content="divider_vertical",
                position=(rx + rw_rel / 2, ry + rh_rel / 2),
                size=max(rw_rel, rh_rel),
                bbox=[rx, ry, rw_rel, rh_rel],
            ))
            out[-1].divider_orientation = "vertical"
            out[-1].divider_thickness = 0.08

    content = bw.copy()
    if np.any(divider_mask > 0):
        content = cv2.bitwise_and(content, cv2.bitwise_not(cv2.dilate(divider_mask, np.ones((5, 5), np.uint8), 1)))
    content = cv2.morphologyEx(content, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    content = cv2.morphologyEx(content, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(content, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    icons_dir = os.path.join("effects", "manual_icons")
    os.makedirs(icons_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    icon_idx = 0
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 25 or area > 0.28 * (w * h):
            continue
        x, y, cw, ch = cv2.boundingRect(contour)
        if cw < 6 or ch < 6:
            continue
        aspect = cw / float(max(1, ch))
        if aspect < 0.25 or aspect > 3.5:
            continue
        if cw > int(0.5 * w) and ch < int(0.2 * h):
            continue
        pad = 2
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(w, x + cw + pad)
        y2 = min(h, y + ch + pad)
        crop = key_img[y1:y2, x1:x2].copy()
        local_mask = np.zeros((y2 - y1, x2 - x1), dtype=np.uint8)
        shifted = contour - np.array([[x1, y1]])
        cv2.drawContours(local_mask, [shifted], -1, 255, thickness=-1)
        rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
        rgba[:, :, 3] = local_mask
        icon_name = f"key_{key.id}_icon_{stamp}_{icon_idx}.png"
        icon_idx += 1
        icon_path = os.path.join(icons_dir, icon_name)
        cv2.imwrite(icon_path, rgba)
        rel_x = x1 / float(w)
        rel_y = y1 / float(h)
        rel_w = (x2 - x1) / float(w)
        rel_h = (y2 - y1) / float(h)
        out.append(KeyElement(
            type="icon",
            content=icon_path.replace("\\", "/"),
            position=(rel_x + rel_w / 2, rel_y + rel_h / 2),
            size=max(rel_w, rel_h),
            bbox=[rel_x, rel_y, rel_w, rel_h],
        ))
    return out


def run_recognition(app) -> None:
    """Run selected recognition methods and preserve method-specific results."""
    if not app.keys or app.image is None:
        return

    use_new = bool(app.chk_rec_new.isChecked())
    use_legacy = bool(app.chk_rec_legacy.isChecked())
    use_trocr = bool(app.chk_rec_trocr.isChecked())
    use_shapes = bool(app.chk_rec_shapes.isChecked())
    if not (use_new or use_legacy or use_trocr or use_shapes):
        QMessageBox.information(app, "Recognition", "Enable at least one method.")
        return

    app.status_bar.showMessage("Loading OCR models...")
    QApplication.processEvents()

    reader = None
    if use_new or use_legacy:
        reader = get_ocr_reader()
        if reader is None:
            QMessageBox.warning(app, "Recognition", "EasyOCR not available. Please install easyocr.")
            return

    pipeline = None
    if use_new:
        debug_enabled = os.environ.get("KV_OCR_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
        pipeline = KeyOCRPipeline(
            easyocr_reader=reader,
            trocr_fn=recognize_with_trocr,
            use_trocr_fallback=True,
            debug=debug_enabled,
            debug_dir=os.environ.get("KV_OCR_DEBUG_DIR", "debug_ocr_pipeline"),
        )

    progress = QProgressDialog("Running recognition on keys...", "Cancel", 0, len(app.keys), app)
    progress.setWindowModality(Qt.WindowModal)
    keys_with_any = 0

    for i, key in enumerate(app.keys):
        progress.setValue(i)
        progress.setLabelText(f"Recognition on key #{key.id}...")
        QApplication.processEvents()
        if progress.wasCanceled():
            break

        method_map = {"ocr_new": [], "ocr_legacy": [], "trocr": [], "icon_divider": []}
        try:
            if use_new and pipeline is not None:
                method_map["ocr_new"] = recognize_key_new(app.image, key, pipeline)
        except Exception as e:
            print(f"OCR New error on key #{key.id}: {e}")
        try:
            if use_legacy and reader is not None:
                method_map["ocr_legacy"] = recognize_key_legacy(app.image, key, reader)
        except Exception as e:
            print(f"OCR Legacy error on key #{key.id}: {e}")
        try:
            if use_trocr:
                method_map["trocr"] = recognize_key_trocr(app.image, key)
        except Exception as e:
            print(f"TrOCR error on key #{key.id}: {e}")
        try:
            if use_shapes:
                method_map["icon_divider"] = recognize_key_icon_divider(app.image, key)
        except Exception as e:
            print(f"Icon/Divider error on key #{key.id}: {e}")

        key.recognition_by_method = method_map
        if merge_method_elements(method_map):
            keys_with_any += 1

    progress.close()
    app._update_key_list()
    app.status_bar.showMessage(
        f"Recognition completed: {keys_with_any}/{len(app.keys)} keys have method results (final Elements unchanged)"
    )


def run_ocr_new(app) -> None:
    """Run OCR on each key with geometry normalization and diagnostics."""
    if not app.keys or app.image is None:
        return

    app.status_bar.showMessage("Loading OCR model...")
    QApplication.processEvents()
    reader = get_ocr_reader()

    if reader is None:
        QMessageBox.warning(app, "OCR Error", "EasyOCR not available. Please install easyocr.")
        return

    progress = QProgressDialog("Running OCR on keys...", "Cancel", 0, len(app.keys), app)
    progress.setWindowModality(Qt.WindowModal)

    debug_enabled = os.environ.get("KV_OCR_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
    pipeline = KeyOCRPipeline(
        easyocr_reader=reader,
        trocr_fn=recognize_with_trocr,
        use_trocr_fallback=True,
        debug=debug_enabled,
        debug_dir=os.environ.get("KV_OCR_DEBUG_DIR", "debug_ocr_pipeline"),
    )

    keys_with_text = 0
    poor_cases = []
    all_conf = []

    for i, key in enumerate(app.keys):
        progress.setValue(i)
        progress.setLabelText(f"OCR on key #{key.id}...")
        QApplication.processEvents()

        if progress.wasCanceled():
            break

        elements = []

        try:
            best, _ = pipeline.recognize_key(app.image, key)
            if best and best.text:
                elem = KeyElement(
                    type="text",
                    content=best.text,
                    position=(0.5, 0.5),
                    size=0.6,
                )
                elem.bbox = [0.1, 0.1, 0.8, 0.8]
                elements.append(elem)
                all_conf.append(best.confidence)
                if best.confidence < 0.5:
                    poor_cases.append((key.id, best.text, best.confidence, best.backend))
            else:
                poor_cases.append((key.id, "", 0.0, "none"))

        except Exception as e:
            print(f"OCR error on key #{key.id}: {e}")
            poor_cases.append((key.id, "", 0.0, "error"))

        key.elements = elements
        if elements:
            keys_with_text += 1

    progress.close()
    app._update_key_list()
    mean_conf = float(np.mean(all_conf)) if all_conf else 0.0
    app.status_bar.showMessage(
        f"OCR completed: {keys_with_text}/{len(app.keys)} keys have text, mean confidence={mean_conf:.2f}"
    )

    if debug_enabled:
        poor_cases = sorted(poor_cases, key=lambda it: it[2])[:30]
        pipeline.debug.write_summary({
            "total_keys": len(app.keys),
            "keys_with_text": keys_with_text,
            "mean_confidence": round(mean_conf, 4),
            "poor_cases_top30": [
                {"key_id": int(k), "text": t, "confidence": float(c), "backend": b}
                for (k, t, c, b) in poor_cases
            ],
        })


def run_ocr_legacy(app) -> None:
    """Run original EasyOCR flow on axis-aligned bbox crop."""
    if not app.keys or app.image is None:
        return

    app.status_bar.showMessage("Loading OCR model...")
    QApplication.processEvents()
    reader = get_ocr_reader()

    if reader is None:
        QMessageBox.warning(app, "OCR Error", "EasyOCR not available. Please install easyocr.")
        return

    progress = QProgressDialog("Running legacy OCR on keys...", "Cancel", 0, len(app.keys), app)
    progress.setWindowModality(Qt.WindowModal)

    keys_with_text = 0

    for i, key in enumerate(app.keys):
        progress.setValue(i)
        progress.setLabelText(f"Legacy OCR on key #{key.id}...")
        QApplication.processEvents()

        if progress.wasCanceled():
            break

        kx, ky, kw, kh = key.bbox
        if kw <= 0 or kh <= 0:
            continue

        key_img = app.image[ky:ky + kh, kx:kx + kw]
        elements = []

        try:
            results = reader.readtext(key_img, detail=1)

            for (bbox_pts, text, conf) in results:
                if conf < 0.3 or not text.strip():
                    continue

                x1 = int(min(p[0] for p in bbox_pts))
                y1 = int(min(p[1] for p in bbox_pts))
                x2 = int(max(p[0] for p in bbox_pts))
                y2 = int(max(p[1] for p in bbox_pts))

                rel_x = x1 / kw
                rel_y = y1 / kh
                rel_w = (x2 - x1) / kw
                rel_h = (y2 - y1) / kh

                elem = KeyElement(
                    type="text",
                    content=text.strip(),
                    position=(rel_x + rel_w / 2, rel_y + rel_h / 2),
                    size=max(rel_w, rel_h),
                )
                elem.bbox = [rel_x, rel_y, rel_w, rel_h]
                elements.append(elem)
        except Exception as e:
            print(f"Legacy OCR error on key #{key.id}: {e}")

        key.elements = elements
        if elements:
            keys_with_text += 1

    progress.close()
    app._update_key_list()
    app.status_bar.showMessage(f"Legacy OCR completed: {keys_with_text}/{len(app.keys)} keys have text")


def run_trocr(app) -> None:
    """Run TrOCR on each key (good for single characters)."""
    if not app.keys or app.image is None:
        return

    app.status_bar.showMessage("Loading TrOCR model...")
    QApplication.processEvents()

    progress = QProgressDialog("Running TrOCR on keys...", "Cancel", 0, len(app.keys), app)
    progress.setWindowModality(Qt.WindowModal)

    keys_with_text = 0

    for i, key in enumerate(app.keys):
        progress.setValue(i)
        progress.setLabelText(f"TrOCR on key #{key.id}...")
        QApplication.processEvents()

        if progress.wasCanceled():
            break

        kx, ky, kw, kh = key.bbox
        if kw <= 0 or kh <= 0:
            continue

        key_img = app.image[ky:ky + kh, kx:kx + kw]
        text = recognize_with_trocr(key_img)

        if text:
            elem = KeyElement(
                type="text",
                content=text,
                position=(0.5, 0.5),
                size=0.6,
            )
            elem.bbox = [0.1, 0.1, 0.8, 0.8]
            key.elements = [elem]
            keys_with_text += 1
        else:
            key.elements = []

    progress.close()
    app._update_key_list()
    app.status_bar.showMessage(f"TrOCR completed: {keys_with_text}/{len(app.keys)} keys have text")
