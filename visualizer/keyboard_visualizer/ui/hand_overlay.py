"""Hand overlay graphics for typing tutor mode."""

from typing import Optional
from enum import IntEnum

from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsLineItem
from PySide6.QtGui import QPainterPath, QPen, QColor, QBrush, QPainter
from PySide6.QtCore import Qt, QPointF


class Finger(IntEnum):
    """Finger identifiers."""
    LEFT_PINKY = 0
    LEFT_RING = 1
    LEFT_MIDDLE = 2
    LEFT_INDEX = 3
    LEFT_THUMB = 4
    RIGHT_THUMB = 5
    RIGHT_INDEX = 6
    RIGHT_MIDDLE = 7
    RIGHT_RING = 8
    RIGHT_PINKY = 9


# Finger colors (matching edclub style - subtle, professional)
FINGER_COLORS = {
    Finger.LEFT_PINKY: QColor("#e57373"),    # Red
    Finger.LEFT_RING: QColor("#ffb74d"),     # Orange
    Finger.LEFT_MIDDLE: QColor("#fff176"),   # Yellow
    Finger.LEFT_INDEX: QColor("#81c784"),    # Green
    Finger.LEFT_THUMB: QColor("#64b5f6"),    # Blue
    Finger.RIGHT_THUMB: QColor("#64b5f6"),   # Blue
    Finger.RIGHT_INDEX: QColor("#81c784"),   # Green
    Finger.RIGHT_MIDDLE: QColor("#fff176"),  # Yellow
    Finger.RIGHT_RING: QColor("#ffb74d"),    # Orange
    Finger.RIGHT_PINKY: QColor("#e57373"),   # Red
}


class HandGraphics(QGraphicsPathItem):
    """
    Hand silhouette graphic.

    Draws a simplified hand outline that can be positioned over the keyboard.
    """

    def __init__(self, is_left: bool, scale: float = 1.0, parent: QGraphicsItem | None = None):
        super().__init__(parent)

        self.is_left = is_left
        self._scale = scale

        # Finger tip positions (relative to hand center, will be set after path creation)
        self._finger_tips: dict[Finger, QPointF] = {}

        # Create the hand path
        self._create_hand_path()

        # Style
        self.setPen(QPen(QColor(100, 100, 100, 150), 2))
        self.setBrush(QBrush(QColor(200, 200, 200, 80)))

    def _create_hand_path(self) -> None:
        """Create the hand silhouette path with smooth curves."""
        path = QPainterPath()
        s = self._scale

        # More realistic hand shape using Bezier curves
        # Finger widths and lengths based on anatomical proportions

        if self.is_left:
            self._create_left_hand(path, s)
        else:
            self._create_right_hand(path, s)

        self.setPath(path)

    def _draw_finger(self, path: QPainterPath, s: float,
                     base_x: float, base_y: float,
                     tip_x: float, tip_y: float,
                     width: float, finger: Finger) -> None:
        """Draw a single finger with rounded tip."""
        # Finger sides
        half_w = width / 2

        # Left side of finger (going up)
        path.lineTo((base_x - half_w) * s, base_y * s)
        path.quadTo((tip_x - half_w * 0.9) * s, (tip_y + 15) * s,
                    (tip_x - half_w * 0.7) * s, (tip_y + 5) * s)

        # Rounded fingertip
        path.quadTo((tip_x - half_w * 0.3) * s, tip_y * s,
                    tip_x * s, (tip_y - 2) * s)

        # Store finger tip position
        self._finger_tips[finger] = QPointF(tip_x * s, tip_y * s)

        # Continue rounded tip
        path.quadTo((tip_x + half_w * 0.3) * s, tip_y * s,
                    (tip_x + half_w * 0.7) * s, (tip_y + 5) * s)

        # Right side of finger (going down)
        path.quadTo((tip_x + half_w * 0.9) * s, (tip_y + 15) * s,
                    (base_x + half_w) * s, base_y * s)

    def _create_left_hand(self, path: QPainterPath, s: float) -> None:
        """Create left hand path."""
        # Start at wrist
        path.moveTo(-35 * s, 75 * s)

        # Wrist to palm - left side curve
        path.quadTo(-45 * s, 50 * s, -48 * s, 20 * s)
        path.quadTo(-50 * s, 5 * s, -48 * s, -5 * s)

        # Pinky finger
        self._draw_finger(path, s, -43, -5, -40, -45, 10, Finger.LEFT_PINKY)

        # Between pinky and ring
        path.quadTo(-33 * s, -10 * s, -28 * s, -15 * s)

        # Ring finger
        self._draw_finger(path, s, -25, -15, -20, -65, 11, Finger.LEFT_RING)

        # Between ring and middle
        path.quadTo(-12 * s, -18 * s, -5 * s, -20 * s)

        # Middle finger (longest)
        self._draw_finger(path, s, 0, -20, 2, -78, 12, Finger.LEFT_MIDDLE)

        # Between middle and index
        path.quadTo(12 * s, -18 * s, 20 * s, -15 * s)

        # Index finger
        self._draw_finger(path, s, 25, -15, 28, -62, 12, Finger.LEFT_INDEX)

        # Between index and thumb - palm curve
        path.quadTo(38 * s, -5 * s, 42 * s, 10 * s)
        path.quadTo(48 * s, 25 * s, 50 * s, 35 * s)

        # Thumb (angled outward)
        path.quadTo(55 * s, 30 * s, 62 * s, 28 * s)
        path.quadTo(68 * s, 26 * s, 72 * s, 30 * s)

        # Thumb tip (rounded)
        self._finger_tips[Finger.LEFT_THUMB] = QPointF(75 * s, 35 * s)
        path.quadTo(76 * s, 33 * s, 76 * s, 37 * s)
        path.quadTo(75 * s, 42 * s, 70 * s, 45 * s)

        # Thumb back to palm
        path.quadTo(62 * s, 50 * s, 52 * s, 52 * s)
        path.quadTo(45 * s, 55 * s, 40 * s, 60 * s)

        # Back to wrist - right side
        path.quadTo(38 * s, 70 * s, 35 * s, 75 * s)

        # Close the wrist
        path.quadTo(0 * s, 78 * s, -35 * s, 75 * s)

    def _create_right_hand(self, path: QPainterPath, s: float) -> None:
        """Create right hand path (mirror of left)."""
        # Start at wrist
        path.moveTo(35 * s, 75 * s)

        # Wrist to palm - right side curve
        path.quadTo(45 * s, 50 * s, 48 * s, 20 * s)
        path.quadTo(50 * s, 5 * s, 48 * s, -5 * s)

        # Pinky finger
        self._draw_finger(path, s, 43, -5, 40, -45, 10, Finger.RIGHT_PINKY)

        # Between pinky and ring
        path.quadTo(33 * s, -10 * s, 28 * s, -15 * s)

        # Ring finger
        self._draw_finger(path, s, 25, -15, 20, -65, 11, Finger.RIGHT_RING)

        # Between ring and middle
        path.quadTo(12 * s, -18 * s, 5 * s, -20 * s)

        # Middle finger (longest)
        self._draw_finger(path, s, 0, -20, -2, -78, 12, Finger.RIGHT_MIDDLE)

        # Between middle and index
        path.quadTo(-12 * s, -18 * s, -20 * s, -15 * s)

        # Index finger
        self._draw_finger(path, s, -25, -15, -28, -62, 12, Finger.RIGHT_INDEX)

        # Between index and thumb - palm curve
        path.quadTo(-38 * s, -5 * s, -42 * s, 10 * s)
        path.quadTo(-48 * s, 25 * s, -50 * s, 35 * s)

        # Thumb (angled outward)
        path.quadTo(-55 * s, 30 * s, -62 * s, 28 * s)
        path.quadTo(-68 * s, 26 * s, -72 * s, 30 * s)

        # Thumb tip (rounded)
        self._finger_tips[Finger.RIGHT_THUMB] = QPointF(-75 * s, 35 * s)
        path.quadTo(-76 * s, 33 * s, -76 * s, 37 * s)
        path.quadTo(-75 * s, 42 * s, -70 * s, 45 * s)

        # Thumb back to palm
        path.quadTo(-62 * s, 50 * s, -52 * s, 52 * s)
        path.quadTo(-45 * s, 55 * s, -40 * s, 60 * s)

        # Back to wrist - left side
        path.quadTo(-38 * s, 70 * s, -35 * s, 75 * s)

        # Close the wrist
        path.quadTo(0 * s, 78 * s, 35 * s, 75 * s)

    def get_finger_tip_pos(self, finger: Finger) -> Optional[QPointF]:
        """Get the scene position of a finger tip."""
        if finger in self._finger_tips:
            # Map local position to scene coordinates
            return self.mapToScene(self._finger_tips[finger])
        return None

    def get_all_finger_tips(self) -> dict[Finger, QPointF]:
        """Get all finger tip positions in scene coordinates."""
        return {
            finger: self.mapToScene(pos)
            for finger, pos in self._finger_tips.items()
        }


class FingerLine(QGraphicsLineItem):
    """Line from finger tip to target key."""

    def __init__(self, finger: Finger, parent: QGraphicsItem | None = None):
        super().__init__(parent)

        self.finger = finger
        color = FINGER_COLORS.get(finger, QColor("#4fc3f7"))

        # Style - thick line with finger color
        pen = QPen(color, 3)
        pen.setCapStyle(Qt.RoundCap)
        self.setPen(pen)

        self.hide()  # Hidden by default

    def connect_to(self, finger_pos: QPointF, key_pos: QPointF) -> None:
        """Set line from finger to key position."""
        self.setLine(finger_pos.x(), finger_pos.y(), key_pos.x(), key_pos.y())
        self.show()


# Default finger mapping for Charybdis Nano 3x5+3 layout
# Key indices map to fingers
# This assumes standard split keyboard finger placement
CHARYBDIS_NANO_FINGER_MAP: dict[int, Finger] = {
    # Left hand - top row (indices 0-4)
    0: Finger.LEFT_PINKY,
    1: Finger.LEFT_RING,
    2: Finger.LEFT_MIDDLE,
    3: Finger.LEFT_INDEX,
    4: Finger.LEFT_INDEX,  # Inner column

    # Left hand - middle row (indices 5-9)
    5: Finger.LEFT_PINKY,
    6: Finger.LEFT_RING,
    7: Finger.LEFT_MIDDLE,
    8: Finger.LEFT_INDEX,
    9: Finger.LEFT_INDEX,  # Inner column

    # Left hand - bottom row (indices 10-14)
    10: Finger.LEFT_PINKY,
    11: Finger.LEFT_RING,
    12: Finger.LEFT_MIDDLE,
    13: Finger.LEFT_INDEX,
    14: Finger.LEFT_INDEX,  # Inner column

    # Left hand - thumb cluster
    15: Finger.LEFT_THUMB,
    17: Finger.LEFT_THUMB,
    18: Finger.LEFT_THUMB,

    # Right hand - top row
    20: Finger.RIGHT_PINKY,
    21: Finger.RIGHT_RING,
    22: Finger.RIGHT_MIDDLE,
    23: Finger.RIGHT_INDEX,
    24: Finger.RIGHT_INDEX,

    # Right hand - middle row
    25: Finger.RIGHT_PINKY,
    26: Finger.RIGHT_RING,
    27: Finger.RIGHT_MIDDLE,
    28: Finger.RIGHT_INDEX,
    29: Finger.RIGHT_INDEX,

    # Right hand - bottom row
    30: Finger.RIGHT_PINKY,
    31: Finger.RIGHT_RING,
    32: Finger.RIGHT_MIDDLE,
    33: Finger.RIGHT_INDEX,
    34: Finger.RIGHT_INDEX,

    # Right hand - thumb cluster
    35: Finger.RIGHT_THUMB,
    37: Finger.RIGHT_THUMB,
}


CHARYBDIS_NANO_HOME_POSITION_MAP: dict[Finger, int] = {
    Finger.LEFT_PINKY: 5,
    Finger.LEFT_RING: 6,
    Finger.LEFT_MIDDLE: 7,
    Finger.LEFT_INDEX: 8,
    Finger.LEFT_THUMB: 17,
    Finger.RIGHT_THUMB: 35,
    Finger.RIGHT_INDEX: 28,
    Finger.RIGHT_MIDDLE: 27,
    Finger.RIGHT_RING: 26,
    Finger.RIGHT_PINKY: 25,
}


def get_finger_for_key(key_index: int, finger_map: dict[int, Finger] | None = None) -> Optional[Finger]:
    """Get the recommended finger for a key index."""
    if finger_map is None:
        finger_map = CHARYBDIS_NANO_FINGER_MAP
    return finger_map.get(key_index)


def get_finger_color(finger: Finger) -> QColor:
    """Get the color associated with a finger."""
    return FINGER_COLORS.get(finger, QColor("#808080"))
