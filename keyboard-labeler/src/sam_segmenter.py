"""SAM-based keyboard segmentation."""
import cv2
import numpy as np
import torch
from typing import List, Tuple, Optional
from segment_anything import sam_model_registry, SamPredictor, SamAutomaticMaskGenerator

from .models import KeyCandidate, KeyStatus


class SAMSegmenter:
    """Segment keyboard keys using SAM."""

    def __init__(self, checkpoint_path: str, model_type: str = "vit_b",
                 device: Optional[str] = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Loading SAM model ({model_type}) on {self.device}...")

        self.sam = sam_model_registry[model_type](checkpoint=checkpoint_path)
        self.sam.to(self.device)

        self.predictor = SamPredictor(self.sam)
        self.image: Optional[np.ndarray] = None
        self.image_rgb: Optional[np.ndarray] = None
        self.edge_map: Optional[np.ndarray] = None
        print("SAM loaded successfully")

    def set_image(self, image: np.ndarray):
        """Set the image for segmentation."""
        self.image = image
        self.image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        self.predictor.set_image(self.image_rgb)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        grad = cv2.magnitude(gx, gy)
        p95 = float(np.percentile(grad, 95))
        self.edge_map = grad / p95 if p95 > 0 else grad

    def auto_segment(self, min_area: int = 200, max_area: int = 50000,
                     points_per_side: int = 24) -> List[KeyCandidate]:
        """Automatically segment all potential keys."""
        if self.image_rgb is None:
            raise ValueError("No image set. Call set_image() first.")

        print(f"Running automatic segmentation (points_per_side={points_per_side})...")

        mask_generator = SamAutomaticMaskGenerator(
            self.sam,
            points_per_side=points_per_side,
            pred_iou_thresh=0.88,
            stability_score_thresh=0.92,
            min_mask_region_area=min_area,
        )

        with torch.amp.autocast(device_type="cuda", enabled=(self.device == "cuda")):
            masks = mask_generator.generate(self.image_rgb)

        print(f"Found {len(masks)} segments")

        # Convert to KeyCandidate objects
        candidates = []
        for i, mask_data in enumerate(masks):
            area = mask_data["area"]

            # Filter by area
            if area < min_area or area > max_area:
                continue

            mask = mask_data["segmentation"]
            polygon, shape_type, corner_radius = self._mask_to_polygon(mask)

            if not polygon:
                continue

            pts = np.array(polygon)
            x_min, y_min = pts.min(axis=0)
            x_max, y_max = pts.max(axis=0)
            bbox = (int(x_min), int(y_min), int(x_max - x_min), int(y_max - y_min))

            candidates.append(KeyCandidate(
                id=len(candidates),
                status=KeyStatus.DRAFT,
                polygon=polygon,
                bbox=bbox,
                area=area,
                shape_type=shape_type,
                corner_radius=corner_radius,
            ))

        print(f"Filtered to {len(candidates)} key candidates")
        return candidates

    def segment_at_point(self, x: int, y: int) -> Optional[KeyCandidate]:
        """Segment a key at the given point."""
        if self.image_rgb is None:
            raise ValueError("No image set. Call set_image() first.")

        h, w = self.image_rgb.shape[:2]
        probe_offsets = [
            (0, 0),
            (6, 0), (-6, 0),
            (0, 6), (0, -6),
            (10, 10), (-10, 10), (10, -10), (-10, -10),
        ]

        best_mask = None
        best_score = -1.0

        for dx, dy in probe_offsets:
            px = int(np.clip(x + dx, 0, w - 1))
            py = int(np.clip(y + dy, 0, h - 1))

            masks, scores, _ = self.predictor.predict(
                point_coords=np.array([[px, py]]),
                point_labels=np.array([1]),
                multimask_output=True
            )

            for i in range(len(scores)):
                mask = masks[i]
                score = float(scores[i])
                area = float(mask.sum())

                # Reject obvious background/huge regions.
                if area < 80 or area > (w * h * 0.25):
                    continue

                weighted = score
                if weighted > best_score:
                    best_score = weighted
                    best_mask = mask

        if best_mask is None or best_score < 0.25:
            return None

        polygon, shape_type, corner_radius = self._mask_to_polygon(best_mask)
        if not polygon:
            return None

        # Calculate bbox
        pts = np.array(polygon)
        x_min, y_min = pts.min(axis=0)
        x_max, y_max = pts.max(axis=0)
        bbox = (int(x_min), int(y_min), int(x_max - x_min), int(y_max - y_min))

        area = int(best_mask.sum())

        return KeyCandidate(
            id=-1,  # Will be assigned later
            status=KeyStatus.DRAFT,
            polygon=polygon,
            bbox=bbox,
            area=area,
            shape_type=shape_type,
            corner_radius=corner_radius,
        )

    def segment_at_points(self, points: List[Tuple[int, int]]) -> Optional[KeyCandidate]:
        """Segment using multiple points (for merging)."""
        if self.image_rgb is None:
            raise ValueError("No image set. Call set_image() first.")

        masks, scores, _ = self.predictor.predict(
            point_coords=np.array(points),
            point_labels=np.array([1] * len(points)),
            multimask_output=True
        )

        best_idx = np.argmax(scores)
        mask = masks[best_idx]

        polygon, shape_type, corner_radius = self._mask_to_polygon(mask)
        if not polygon:
            return None

        pts = np.array(polygon)
        x_min, y_min = pts.min(axis=0)
        x_max, y_max = pts.max(axis=0)
        bbox = (int(x_min), int(y_min), int(x_max - x_min), int(y_max - y_min))

        return KeyCandidate(
            id=-1,
            status=KeyStatus.DRAFT,
            polygon=polygon,
            bbox=bbox,
            area=int(mask.sum()),
            shape_type=shape_type,
            corner_radius=corner_radius,
        )

    def _mask_to_polygon(self, mask: np.ndarray) -> Tuple[List[Tuple[int, int]], str, float]:
        """Convert binary mask to polygon and infer key shape type."""
        mask_uint8 = (mask * 255).astype(np.uint8)
        kernel = np.ones((3, 3), np.uint8)
        # Smooth jagged mask edges before contour extraction.
        mask_uint8 = cv2.morphologyEx(mask_uint8, cv2.MORPH_CLOSE, kernel, iterations=1)
        mask_uint8 = cv2.morphologyEx(mask_uint8, cv2.MORPH_OPEN, kernel, iterations=1)

        contours, _ = cv2.findContours(
            mask_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        if not contours:
            return [], "free", 0.0

        # Get largest contour
        largest = max(contours, key=cv2.contourArea)
        shape_type = self._classify_contour_shape(largest)
        candidates = self._build_polygon_candidates(largest, mask_uint8, shape_type)
        polygon = self._pick_best_fit_polygon(candidates, mask_uint8)
        corner = 0.0
        return polygon, shape_type, corner

    def _build_polygon_candidates(
        self,
        contour: np.ndarray,
        mask_uint8: np.ndarray,
        shape_type: str,
    ) -> List[List[Tuple[int, int]]]:
        """Generate candidate polygons from contour and smoothed masks."""
        candidates: List[List[Tuple[int, int]]] = []

        perimeter = cv2.arcLength(contour, True)
        points_count = max(int(len(contour)), 1)
        step = perimeter / points_count
        eps_values = np.linspace(step * 0.5, step * 4.0, num=7)

        for eps in eps_values:
            approx = cv2.approxPolyDP(contour, float(eps), True)
            poly = [(int(p[0][0]), int(p[0][1])) for p in approx]
            if len(poly) >= 4:
                candidates.append(poly)

        if shape_type == "rect":
            rect_poly = self._regularize_contour(contour)
            if rect_poly:
                candidates.append(rect_poly)

        sigma_values = np.linspace(step * 0.2, step * 1.0, num=4)
        for sigma in sigma_values:
            if sigma <= 0:
                continue
            blurred = cv2.GaussianBlur(mask_uint8, (0, 0), sigmaX=float(sigma), sigmaY=float(sigma))
            _, smooth_mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            smooth_contours, _ = cv2.findContours(
                smooth_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if not smooth_contours:
                continue
            largest = max(smooth_contours, key=cv2.contourArea)
            approx = cv2.approxPolyDP(largest, step * 1.5, True)
            poly = [(int(p[0][0]), int(p[0][1])) for p in approx]
            if len(poly) >= 4:
                candidates.append(poly)

        if not candidates:
            approx = cv2.approxPolyDP(contour, step, True)
            candidates.append([(int(p[0][0]), int(p[0][1])) for p in approx])

        return candidates

    def _pick_best_fit_polygon(
        self,
        candidates: List[List[Tuple[int, int]]],
        base_mask: np.ndarray,
    ) -> List[Tuple[int, int]]:
        """Pick candidate that best follows image edges while preserving original mask."""
        base = base_mask > 0
        best_poly = candidates[0]
        best_score = -1.0

        for poly in candidates:
            score = self._score_polygon_fit(poly, base)
            if score > best_score:
                best_score = score
                best_poly = poly

        return best_poly

    def _score_polygon_fit(self, polygon: List[Tuple[int, int]], base_mask: np.ndarray) -> float:
        """Image-fit score: edge alignment * IoU with original mask."""
        if self.edge_map is None or not polygon:
            return 0.0

        h, w = base_mask.shape[:2]
        poly_np = np.array(polygon, dtype=np.int32)

        cand_fill = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(cand_fill, [poly_np], 255)
        cand = cand_fill > 0

        inter = np.logical_and(base_mask, cand).sum()
        union = np.logical_or(base_mask, cand).sum()
        iou = float(inter / union) if union > 0 else 0.0

        # Line thickness derived from contour size for this key.
        perimeter = cv2.arcLength(poly_np.reshape(-1, 1, 2), True)
        step = perimeter / max(len(poly_np), 1)
        thickness = max(1, int(round(step)))

        line_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.polylines(line_mask, [poly_np], isClosed=True, color=255, thickness=thickness)
        edge_vals = self.edge_map[line_mask > 0]
        edge_fit = float(edge_vals.mean()) if edge_vals.size > 0 else 0.0

        return iou * edge_fit

    def _classify_contour_shape(self, contour: np.ndarray) -> str:
        """Classify key shape from contour geometry."""
        area = cv2.contourArea(contour)
        if area <= 0:
            return "free"

        rect = cv2.minAreaRect(contour)
        w, h = rect[1]
        if w <= 1 or h <= 1:
            return "free"

        rect_area = w * h
        if rect_area <= 0:
            return "free"

        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull) if hull is not None else 0
        fill_ratio = area / rect_area
        hull_fill_ratio = area / hull_area if hull_area > 0 else 1.0
        aspect_ratio = max(w, h) / min(w, h)

        # Very elongated bars are usually split space keys.
        if aspect_ratio >= 3.2 and fill_ratio >= 0.70:
            return "long_rect"

        # Typical single keycaps.
        if fill_ratio >= 0.76 and hull_fill_ratio >= 0.95:
            return "rect"

        # Concave but still structured shape: ISO-like Enter.
        if 0.45 <= fill_ratio < 0.76 and hull_fill_ratio < 0.94:
            return "l_shape"

        return "free"

    def _regularize_contour(self, contour: np.ndarray) -> Optional[List[Tuple[int, int]]]:
        """Return a rotated rectangle polygon for near-rectangular contours."""
        area = cv2.contourArea(contour)
        if area <= 0:
            return None

        rect = cv2.minAreaRect(contour)
        w, h = rect[1]
        if w <= 1 or h <= 1:
            return None

        rect_area = w * h
        if rect_area <= 0:
            return None

        fill_ratio = area / rect_area
        aspect_ratio = max(w, h) / min(w, h)

        # Only regularize when contour already looks close to a rectangle.
        if fill_ratio < 0.72:
            return None

        box = cv2.boxPoints(rect)
        box = np.round(box).astype(np.int32)
        return [(int(p[0]), int(p[1])) for p in box]
