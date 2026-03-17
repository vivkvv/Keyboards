"""Helpers for deterministic key ordering and row resolution."""
from typing import Any, Dict, List, Optional, Set, Tuple

from .models import KeyCandidate


def _split_keys_into_rows_directional(
    keys: List[KeyCandidate],
    from_top: bool = True,
) -> List[List[KeyCandidate]]:
    """Split keys into rows using no-overlap rule from top or from bottom."""
    if not keys:
        return []

    remaining = list(keys)
    rows: List[List[KeyCandidate]] = []

    def x_range(key: KeyCandidate) -> Tuple[float, float]:
        x, _, w, _ = key.bbox
        if w > 0:
            return float(x), float(x + w)
        cx, _ = key.center()
        return float(cx), float(cx)

    def y_top(key: KeyCandidate) -> float:
        _, y, _, h = key.bbox
        if h > 0:
            return float(y)
        _, cy = key.center()
        return float(cy)

    def y_bottom(key: KeyCandidate) -> float:
        _, y, _, h = key.bbox
        if h > 0:
            return float(y + h)
        _, cy = key.center()
        return float(cy)

    def x_overlap(a: KeyCandidate, b: KeyCandidate) -> float:
        ax1, ax2 = x_range(a)
        bx1, bx2 = x_range(b)
        return min(ax2, bx2) - max(ax1, bx1)

    while remaining:
        top_row: List[KeyCandidate] = []
        for key in remaining:
            blocked = False
            for other in remaining:
                if other is key:
                    continue
                if from_top:
                    if y_top(other) >= y_top(key):
                        continue
                else:
                    if y_bottom(other) <= y_bottom(key):
                        continue
                if x_overlap(key, other) > 0:
                    blocked = True
                    break
            if not blocked:
                top_row.append(key)

        if not top_row:
            if from_top:
                top_row = [min(remaining, key=lambda k: (y_top(k), k.center()[0]))]
            else:
                top_row = [max(remaining, key=lambda k: (y_bottom(k), -k.center()[0]))]

        top_row.sort(key=lambda k: (k.center()[0], y_top(k)))
        rows.append(top_row)

        top_set = set(id(k) for k in top_row)
        remaining = [k for k in remaining if id(k) not in top_set]

    return rows


def split_keys_into_rows(keys: List[KeyCandidate]) -> List[List[KeyCandidate]]:
    """Split keys into rows from top to bottom."""
    return _split_keys_into_rows_directional(keys, from_top=True)


def split_keys_into_rows_from_bottom(keys: List[KeyCandidate]) -> List[List[KeyCandidate]]:
    """Split keys into rows from bottom to top."""
    return _split_keys_into_rows_directional(keys, from_top=False)


def get_problematic_key_ids(keys: List[KeyCandidate]) -> Set[int]:
    """Detect keys present in one corresponding row but missing in the other."""
    rows_top = split_keys_into_rows(keys)
    rows_bottom = split_keys_into_rows_from_bottom(keys)

    problematic: Set[int] = set()
    row_count = max(len(rows_top), len(rows_bottom))

    for ridx in range(row_count):
        top_row = rows_top[ridx] if ridx < len(rows_top) else []
        # bottom rows are built bottom->top, align them with top rows.
        bidx = len(rows_bottom) - 1 - ridx
        bottom_row = rows_bottom[bidx] if 0 <= bidx < len(rows_bottom) else []

        top_ids = {k.id for k in top_row}
        bottom_ids = {k.id for k in bottom_row}
        problematic.update(top_ids.symmetric_difference(bottom_ids))
    return problematic


def get_problematic_key_object_ids(keys: List[KeyCandidate]) -> Set[int]:
    """Object-id based variant: symmetric row-set difference."""
    rows_top = split_keys_into_rows(keys)
    rows_bottom = split_keys_into_rows_from_bottom(keys)

    problematic: Set[int] = set()
    row_count = max(len(rows_top), len(rows_bottom))

    for ridx in range(row_count):
        top_row = rows_top[ridx] if ridx < len(rows_top) else []
        bidx = len(rows_bottom) - 1 - ridx
        bottom_row = rows_bottom[bidx] if 0 <= bidx < len(rows_bottom) else []

        top_set = {id(k) for k in top_row}
        bottom_set = {id(k) for k in bottom_row}
        problematic.update(top_set.symmetric_difference(bottom_set))
    return problematic


def _polygon_for_key(key: KeyCandidate) -> List[Tuple[float, float]]:
    """Return polygon for key, falling back to bbox rectangle."""
    if key.polygon and len(key.polygon) >= 3:
        return [(float(x), float(y)) for x, y in key.polygon]
    x, y, w, h = key.bbox
    return [
        (float(x), float(y)),
        (float(x + w), float(y)),
        (float(x + w), float(y + h)),
        (float(x), float(y + h)),
    ]


def _point_in_polygon(px: float, py: float, poly: List[Tuple[float, float]]) -> bool:
    """Ray-casting point in polygon test."""
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        crosses = ((y1 > py) != (y2 > py))
        if not crosses:
            continue
        xinters = (x2 - x1) * (py - y1) / ((y2 - y1) if (y2 - y1) != 0 else 1e-9) + x1
        if px < xinters:
            inside = not inside
    return inside


def _segments_intersect(
    a1: Tuple[float, float],
    a2: Tuple[float, float],
    b1: Tuple[float, float],
    b2: Tuple[float, float],
) -> bool:
    """Check if two 2D segments intersect."""
    def orient(p, q, r) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on_seg(p, q, r) -> bool:
        return (
            min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and
            min(p[1], r[1]) <= q[1] <= max(p[1], r[1])
        )

    o1 = orient(a1, a2, b1)
    o2 = orient(a1, a2, b2)
    o3 = orient(b1, b2, a1)
    o4 = orient(b1, b2, a2)

    if (o1 > 0 > o2 or o1 < 0 < o2) and (o3 > 0 > o4 or o3 < 0 < o4):
        return True

    eps = 1e-9
    if abs(o1) <= eps and on_seg(a1, b1, a2):
        return True
    if abs(o2) <= eps and on_seg(a1, b2, a2):
        return True
    if abs(o3) <= eps and on_seg(b1, a1, b2):
        return True
    if abs(o4) <= eps and on_seg(b1, a2, b2):
        return True
    return False


def _row_polyline_intersects_key(row: List[KeyCandidate], key: KeyCandidate) -> bool:
    """Check whether row polyline intersects key polygon."""
    row_sorted = sorted(row, key=lambda k: k.center()[0])
    if len(row_sorted) < 2:
        return False

    poly = _polygon_for_key(key)
    edges = [
        (poly[i], poly[(i + 1) % len(poly)])
        for i in range(len(poly))
    ]

    centers = [tuple(map(float, k.center())) for k in row_sorted]

    for i in range(len(centers) - 1):
        s1 = centers[i]
        s2 = centers[i + 1]

        if _point_in_polygon(s1[0], s1[1], poly) or _point_in_polygon(s2[0], s2[1], poly):
            return True

        for e1, e2 in edges:
            if _segments_intersect(s1, s2, e1, e2):
                return True

    return False


def _polyline_points_intersect_key(
    points: List[Tuple[float, float]],
    key: KeyCandidate,
) -> bool:
    """Check whether a polyline intersects a key polygon."""
    if len(points) < 2:
        return False

    poly = _polygon_for_key(key)
    edges = [
        (poly[i], poly[(i + 1) % len(poly)])
        for i in range(len(poly))
    ]

    for i in range(len(points) - 1):
        s1 = points[i]
        s2 = points[i + 1]
        if _point_in_polygon(s1[0], s1[1], poly) or _point_in_polygon(s2[0], s2[1], poly):
            return True
        for e1, e2 in edges:
            if _segments_intersect(s1, s2, e1, e2):
                return True
    return False


def _quadratic_extend_points(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    t_start: float,
    t_end: float,
    steps: int,
) -> List[Tuple[float, float]]:
    """Sample quadratic spline passing through p0,p1,p2 for t in [t_start, t_end]."""
    if steps <= 0:
        return []

    def q(a0: float, a1: float, a2: float, t: float) -> float:
        # Lagrange basis at knots 0,1,2.
        l0 = (t - 1.0) * (t - 2.0) / 2.0
        l1 = -(t) * (t - 2.0)
        l2 = t * (t - 1.0) / 2.0
        return a0 * l0 + a1 * l1 + a2 * l2

    out: List[Tuple[float, float]] = []
    for i in range(1, steps + 1):
        t = t_start + (t_end - t_start) * (i / steps)
        out.append((
            q(p0[0], p1[0], p2[0], t),
            q(p0[1], p1[1], p2[1], t),
        ))
    return out


def _build_extended_row_polyline(
    row: List[KeyCandidate],
    x_left_limit: float,
    x_right_limit: float,
) -> List[Tuple[float, float]]:
    """Build row polyline with spline extensions from first/last three points."""
    centers = [tuple(map(float, k.center())) for k in sorted(row, key=lambda k: k.center()[0])]
    if len(centers) < 2:
        return centers

    extended = list(centers)

    if len(centers) >= 3:
        # Left extension from first point using first three points.
        lp0, lp1, lp2 = centers[2], centers[1], centers[0]
        left_pts = _quadratic_extend_points(lp0, lp1, lp2, 2.0, 3.4, 12)
        left_pts = [p for p in left_pts if p[0] <= centers[0][0] and p[0] >= x_left_limit]
        extended = list(reversed(left_pts)) + extended

        # Right extension from last point using last three points.
        rp0, rp1, rp2 = centers[-3], centers[-2], centers[-1]
        right_pts = _quadratic_extend_points(rp0, rp1, rp2, 2.0, 3.4, 12)
        right_pts = [p for p in right_pts if p[0] >= centers[-1][0] and p[0] <= x_right_limit]
        extended.extend(right_pts)

    return extended


def resolve_problematic_rows_by_neighbors(
    keys: List[KeyCandidate],
    debug_report: Optional[List[Dict[str, Any]]] = None,
    resolved_rows_out: Optional[List[List[KeyCandidate]]] = None,
) -> Tuple[List[KeyCandidate], Set[int]]:
    """
    Resolve problematic keys by row-polyline intersection rule:
    - build row polylines from current rows
    - for each problematic key, detect which row polylines intersect it
    - if exactly one row intersects, assign key to that row
    - otherwise keep key unresolved
    Returns: (ordered_keys, unresolved_object_ids)
    """
    rows = split_keys_into_rows(keys)
    row_map: Dict[int, int] = {}
    for ridx, row in enumerate(rows):
        for key in row:
            row_map[id(key)] = ridx

    problematic = get_problematic_key_object_ids(keys)

    # Build guide rows only from stable keys to avoid self-intersection bias:
    # problematic keys should not influence their own resolution geometry.
    stable_rows: List[List[KeyCandidate]] = []
    for row in rows:
        stable_rows.append([k for k in row if id(k) not in problematic])

    unresolved: Set[int] = set()

    for key in keys:
        kid = id(key)
        if kid not in problematic:
            continue

        intersect_rows = []
        for ridx, row in enumerate(stable_rows):
            if _row_polyline_intersects_key(row, key):
                intersect_rows.append(ridx)

        krow = row_map.get(kid)
        target_row: Optional[int] = None
        action = "kept"
        reason = "resolved"

        if krow is None:
            reason = "missing_current_row"
            action = "unresolved"
            unresolved.add(kid)
        elif len(intersect_rows) == 1:
            target_row = intersect_rows[0]
            if krow != target_row:
                rows[krow] = [k for k in rows[krow] if k is not key]
                rows[target_row].append(key)
                row_map[kid] = target_row
                action = "moved"
            else:
                action = "kept_same_row"
        elif len(intersect_rows) == 0:
            reason = "no_stable_row_intersection"
            action = "unresolved"
            unresolved.add(kid)
        else:
            reason = "ambiguous_row_intersections"
            action = "unresolved"
            unresolved.add(kid)

        if debug_report is not None:
            debug_report.append({
                "key_id": key.id,
                "center": key.center(),
                "initial_row": krow,
                "intersect_rows": intersect_rows,
                "target_row": target_row,
                "action": action,
                "reason": reason,
            })

    # Second pass: extend each row polyline with spline continuation and
    # try resolving the keys left unresolved after direct intersections.
    if unresolved:
        stable_rows_second: List[List[KeyCandidate]] = []
        for row in rows:
            stable_rows_second.append([k for k in row if id(k) not in unresolved])

        all_centers = [k.center() for k in keys]
        min_x = float(min(c[0] for c in all_centers)) - 100.0
        max_x = float(max(c[0] for c in all_centers)) + 100.0

        row_polylines = [
            _build_extended_row_polyline(row, min_x, max_x)
            for row in stable_rows_second
        ]

        unresolved_list = [k for k in keys if id(k) in unresolved]
        for key in unresolved_list:
            kid = id(key)
            krow = row_map.get(kid)
            intersect_rows = [
                ridx for ridx, polyline in enumerate(row_polylines)
                if _polyline_points_intersect_key(polyline, key)
            ]
            if not intersect_rows or krow is None:
                continue

            # If multiple rows intersect, pick the upper row (smallest index).
            target_row = min(intersect_rows)
            if krow != target_row:
                rows[krow] = [k for k in rows[krow] if k is not key]
                rows[target_row].append(key)
                row_map[kid] = target_row
            unresolved.remove(kid)

            if debug_report is not None:
                item = next((r for r in debug_report if r.get("key_id") == key.id), None)
                if item is not None:
                    item["second_pass_intersect_rows"] = intersect_rows
                    item["second_pass_target_row"] = target_row
                    item["second_pass_action"] = "moved_or_kept"
                    item["second_pass_reason"] = "resolved_by_extended_spline"

    rows = [row for row in rows if row]
    for row in rows:
        row.sort(key=lambda k: (k.center()[0], k.center()[1]))

    ordered: List[KeyCandidate] = []
    for row in rows:
        ordered.extend(row)

    if debug_report is not None:
        row_map_final = {id(k): ridx for ridx, row in enumerate(split_keys_into_rows(ordered)) for k in row}
        for item in debug_report:
            kid = item["key_id"]
            key_obj = next((k for k in ordered if k.id == kid), None)
            if key_obj is None:
                item["final_row"] = None
                item["unresolved"] = None
                if item["reason"] == "resolved":
                    item["reason"] = "key_missing_after_ordering"
                continue
            oid = id(key_obj)
            item["final_row"] = row_map_final.get(oid)
            item["unresolved"] = (oid in unresolved)

    if resolved_rows_out is not None:
        resolved_rows_out.clear()
        for row in rows:
            resolved_rows_out.append(list(row))

    return ordered, unresolved


def sort_keys_by_position(keys: List[KeyCandidate]) -> List[KeyCandidate]:
    """Sort by rows: pick keys that have no overlapping key above them."""
    ordered: List[KeyCandidate] = []
    for row in split_keys_into_rows(keys):
        ordered.extend(row)
    return ordered
