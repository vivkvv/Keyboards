"""Polygon-aware OCR pipeline for keyboard keys with debug diagnostics."""
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .models import KeyCandidate


ALLOWED_TEXT_RE = re.compile(r"^[A-Za-z0-9`~!@#$%^&*()_\-+=\[\]{}\\|;:'\",.<>/?]+$")


@dataclass
class OCRPick:
    """Single OCR candidate."""
    text: str
    confidence: float
    score: float
    backend: str
    geometry: str
    angle: float
    profile: str
    raw_text: str


class OCRDebugWriter:
    """Writes OCR debug artifacts for each processed key."""

    def __init__(self, root_dir: str, enabled: bool):
        self.enabled = bool(enabled)
        self.root_dir = root_dir
        self.session_dir: Optional[str] = None
        if self.enabled:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.session_dir = os.path.join(root_dir, f"session_{stamp}")
            os.makedirs(self.session_dir, exist_ok=True)

    def save_image(self, key_id: int, name: str, image: np.ndarray):
        if not self.enabled or self.session_dir is None or image is None:
            return
        key_dir = os.path.join(self.session_dir, f"key_{int(key_id):03d}")
        os.makedirs(key_dir, exist_ok=True)
        cv2.imwrite(os.path.join(key_dir, name), image)

    def save_json(self, key_id: int, payload: Dict):
        if not self.enabled or self.session_dir is None:
            return
        key_dir = os.path.join(self.session_dir, f"key_{int(key_id):03d}")
        os.makedirs(key_dir, exist_ok=True)
        with open(os.path.join(key_dir, "report.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def write_summary(self, payload: Dict):
        if not self.enabled or self.session_dir is None:
            return
        with open(os.path.join(self.session_dir, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)


class KeyOCRPipeline:
    """OCR pipeline with geometry normalization and deterministic scoring."""

    def __init__(
        self,
        easyocr_reader,
        trocr_fn: Optional[Callable[[np.ndarray], str]] = None,
        use_trocr_fallback: bool = True,
        debug: bool = False,
        debug_dir: str = "debug_ocr_pipeline",
    ):
        self.reader = easyocr_reader
        self.trocr_fn = trocr_fn
        self.use_trocr_fallback = bool(use_trocr_fallback and trocr_fn is not None)
        self.debug = OCRDebugWriter(debug_dir, debug)

    @staticmethod
    def clean_text(text: str) -> str:
        text = (text or "").strip()
        text = re.sub(r"\s+", " ", text)
        return text

    @staticmethod
    def _polygon_from_key(key: KeyCandidate) -> np.ndarray:
        if key.polygon and len(key.polygon) >= 3:
            return np.array(key.polygon, dtype=np.float32)
        x, y, w, h = key.bbox
        return np.array(
            [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
            dtype=np.float32,
        )

    @staticmethod
    def _safe_bbox(points: np.ndarray, width: int, height: int, pad: int = 6) -> Tuple[int, int, int, int]:
        x_min = int(np.floor(np.min(points[:, 0]))) - pad
        y_min = int(np.floor(np.min(points[:, 1]))) - pad
        x_max = int(np.ceil(np.max(points[:, 0]))) + pad
        y_max = int(np.ceil(np.max(points[:, 1]))) + pad
        x_min = max(0, x_min)
        y_min = max(0, y_min)
        x_max = min(width - 1, x_max)
        y_max = min(height - 1, y_max)
        w = max(1, x_max - x_min + 1)
        h = max(1, y_max - y_min + 1)
        return x_min, y_min, w, h

    @staticmethod
    def _normalize_angle_deg(poly_local: np.ndarray) -> float:
        rect = cv2.minAreaRect(poly_local.astype(np.float32))
        angle = float(rect[2])
        rw, rh = rect[1]
        if rw < rh:
            angle += 90.0
        while angle > 45.0:
            angle -= 90.0
        while angle < -45.0:
            angle += 90.0
        return angle

    @staticmethod
    def _rotate_with_mask(
        image: np.ndarray,
        mask: np.ndarray,
        angle_deg: float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        h, w = image.shape[:2]
        cx, cy = w / 2.0, h / 2.0
        rot = cv2.getRotationMatrix2D((cx, cy), angle_deg, 1.0)
        border = int(np.median(image))
        rot_img = cv2.warpAffine(
            image,
            rot,
            (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(border, border, border),
        )
        rot_mask = cv2.warpAffine(
            mask,
            rot,
            (w, h),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        ys, xs = np.where(rot_mask > 0)
        if len(xs) == 0 or len(ys) == 0:
            return rot_img, rot_mask
        x1, x2 = int(xs.min()), int(xs.max())
        y1, y2 = int(ys.min()), int(ys.max())
        return rot_img[y1:y2 + 1, x1:x2 + 1], rot_mask[y1:y2 + 1, x1:x2 + 1]

    @staticmethod
    def _order_points(pts: np.ndarray) -> np.ndarray:
        s = pts.sum(axis=1)
        d = np.diff(pts, axis=1).reshape(-1)
        ordered = np.zeros((4, 2), dtype=np.float32)
        ordered[0] = pts[np.argmin(s)]  # top-left
        ordered[2] = pts[np.argmax(s)]  # bottom-right
        ordered[1] = pts[np.argmin(d)]  # top-right
        ordered[3] = pts[np.argmax(d)]  # bottom-left
        return ordered

    @classmethod
    def _warp_key(cls, crop: np.ndarray, poly_local: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        rect = cv2.minAreaRect(poly_local.astype(np.float32))
        box = cv2.boxPoints(rect).astype(np.float32)
        src = cls._order_points(box)
        w_a = np.linalg.norm(src[2] - src[3])
        w_b = np.linalg.norm(src[1] - src[0])
        h_a = np.linalg.norm(src[1] - src[2])
        h_b = np.linalg.norm(src[0] - src[3])
        width = max(1, int(round(max(w_a, w_b))))
        height = max(1, int(round(max(h_a, h_b))))
        if height > width:
            width, height = height, width
            dst = np.array(
                [[0, height - 1], [0, 0], [width - 1, 0], [width - 1, height - 1]],
                dtype=np.float32,
            )
        else:
            dst = np.array(
                [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
                dtype=np.float32,
            )
        m = cv2.getPerspectiveTransform(src, dst)
        warped = cv2.warpPerspective(crop, m, (width, height), flags=cv2.INTER_CUBIC)
        mask_src = np.zeros(crop.shape[:2], dtype=np.uint8)
        cv2.fillPoly(mask_src, [poly_local.astype(np.int32)], 255)
        mask_warped = cv2.warpPerspective(mask_src, m, (width, height), flags=cv2.INTER_NEAREST)
        return warped, mask_warped

    @staticmethod
    def _apply_mask(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        masked = cv2.bitwise_and(image, image, mask=mask)
        bg = np.full_like(image, int(np.median(image)))
        inv = cv2.bitwise_not(mask)
        bg = cv2.bitwise_and(bg, bg, mask=inv)
        return cv2.add(masked, bg)

    @staticmethod
    def _upscale(gray: np.ndarray, min_side: int = 96) -> np.ndarray:
        h, w = gray.shape[:2]
        if min(h, w) >= min_side:
            return gray
        scale = float(min_side) / float(max(1, min(h, w)))
        return cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    @classmethod
    def _build_profiles(cls, image_bgr: np.ndarray) -> Dict[str, np.ndarray]:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        gray = cls._upscale(gray)
        clahe = cv2.createCLAHE(clipLimit=2.4, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        den = cv2.bilateralFilter(enhanced, 5, 50, 50)
        adapt = cv2.adaptiveThreshold(
            den,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            25,
            7,
        )
        _, otsu = cv2.threshold(den, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(otsu) < 127:
            otsu = cv2.bitwise_not(otsu)
        if np.mean(adapt) < 127:
            adapt = cv2.bitwise_not(adapt)
        return {
            "clahe": cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR),
            "adaptive": cv2.cvtColor(adapt, cv2.COLOR_GRAY2BGR),
            "otsu": cv2.cvtColor(otsu, cv2.COLOR_GRAY2BGR),
        }

    @staticmethod
    def _text_score(clean_text: str, confidence: float) -> float:
        if not clean_text:
            return -1.0
        allowed_bonus = 1.0 if ALLOWED_TEXT_RE.match(clean_text) else 0.5
        length = len(clean_text)
        if length == 1:
            length_bonus = 1.55
        elif length == 2:
            length_bonus = 1.25
        elif length <= 5:
            length_bonus = 0.95
        else:
            length_bonus = 0.5

        alpha_penalty = 1.0
        if length >= 4 and clean_text.isalpha() and clean_text.lower() == clean_text:
            alpha_penalty = 0.6

        digit_symbol_bonus = 1.0
        if length <= 2 and any(ch.isdigit() or (not ch.isalnum()) for ch in clean_text):
            digit_symbol_bonus = 1.15

        return float(confidence) * allowed_bonus * length_bonus * alpha_penalty * digit_symbol_bonus

    def _run_easyocr(self, image_bgr: np.ndarray) -> List[Tuple[str, float]]:
        if self.reader is None:
            return []
        try:
            results = self.reader.readtext(
                image_bgr,
                detail=1,
                paragraph=False,
                text_threshold=0.4,
                low_text=0.2,
                link_threshold=0.2,
            )
        except Exception:
            return []
        out: List[Tuple[str, float]] = []
        for _, text, conf in results:
            out.append((self.clean_text(str(text)), float(conf)))
        return out

    def recognize_key(self, image: np.ndarray, key: KeyCandidate) -> Tuple[Optional[OCRPick], List[OCRPick]]:
        h, w = image.shape[:2]
        polygon = self._polygon_from_key(key)
        x, y, bw, bh = self._safe_bbox(polygon, w, h)
        crop = image[y:y + bh, x:x + bw].copy()
        poly_local = polygon - np.array([x, y], dtype=np.float32)

        mask = np.zeros((bh, bw), dtype=np.uint8)
        cv2.fillPoly(mask, [poly_local.astype(np.int32)], 255)
        masked = self._apply_mask(crop, mask)

        angle = self._normalize_angle_deg(poly_local)
        rotated_base, rot_mask = self._rotate_with_mask(masked, mask, -angle)
        rotated_masked = self._apply_mask(rotated_base, rot_mask)
        warped, warped_mask = self._warp_key(crop, poly_local)
        warped_masked = self._apply_mask(warped, warped_mask)

        self.debug.save_image(key.id, "raw_crop.png", crop)
        self.debug.save_image(key.id, "mask.png", mask)
        self.debug.save_image(key.id, "masked.png", masked)
        self.debug.save_image(key.id, "rotated_base.png", rotated_masked)
        self.debug.save_image(key.id, "warped.png", warped_masked)

        views = [
            ("bbox_raw", 0.0, crop),
            ("masked", 0.0, masked),
            ("rotated", 0.0, rotated_masked),
            ("warped", 0.0, warped_masked),
        ]
        for d in (-8.0, 8.0):
            rimg, rmask = self._rotate_with_mask(rotated_masked, rot_mask, d)
            views.append(("rotated", d, self._apply_mask(rimg, rmask)))

        candidates: List[OCRPick] = []
        for geometry, delta_angle, view_img in views:
            profiles = self._build_profiles(view_img)
            for profile_name, prof_img in profiles.items():
                self.debug.save_image(
                    key.id,
                    f"{geometry}_a{delta_angle:+.0f}_{profile_name}.png",
                    prof_img,
                )
                for text, conf in self._run_easyocr(prof_img):
                    score = self._text_score(text, conf)
                    candidates.append(
                        OCRPick(
                            text=text,
                            confidence=conf,
                            score=score,
                            backend="easyocr",
                            geometry=geometry,
                            angle=delta_angle,
                            profile=profile_name,
                            raw_text=text,
                        )
                    )

        easy_best = candidates[0] if candidates else None
        need_trocr = (
            self.use_trocr_fallback
            and self.trocr_fn is not None
            and (
                easy_best is None
                or easy_best.score < 0.85
                or len(easy_best.text) > 3
            )
        )
        if need_trocr and self.trocr_fn is not None:
            trocr_text = self.clean_text(self.trocr_fn(rotated_masked))
            if trocr_text:
                trocr_score = self._text_score(trocr_text, 0.62)
                candidates.append(
                    OCRPick(
                        text=trocr_text,
                        confidence=0.62,
                        score=trocr_score,
                        backend="trocr",
                        geometry="rotated",
                        angle=0.0,
                        profile="none",
                        raw_text=trocr_text,
                    )
                )

        candidates.sort(key=lambda c: c.score, reverse=True)
        best = candidates[0] if candidates else None

        self.debug.save_json(
            key.id,
            {
                "key_id": key.id,
                "bbox": [int(x), int(y), int(bw), int(bh)],
                "estimated_angle_deg": angle,
                "candidates": [
                    {
                        "text": c.text,
                        "confidence": round(c.confidence, 4),
                        "score": round(c.score, 4),
                        "backend": c.backend,
                        "geometry": c.geometry,
                        "angle": round(c.angle, 2),
                        "profile": c.profile,
                    }
                    for c in candidates[:20]
                ],
                "selected": None if best is None else {
                    "text": best.text,
                    "confidence": round(best.confidence, 4),
                    "score": round(best.score, 4),
                    "backend": best.backend,
                    "geometry": best.geometry,
                    "angle": round(best.angle, 2),
                    "profile": best.profile,
                },
            },
        )
        return best, candidates
