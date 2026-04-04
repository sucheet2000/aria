"""
Week 8: Rule-based gesture classifier from MediaPipe 21-landmark hand data.

MediaPipe landmark indices (https://developers.google.com/mediapipe/solutions/vision/hand_landmarker):
  0  WRIST
  1  THUMB_CMC   2  THUMB_MCP   3  THUMB_IP    4  THUMB_TIP
  5  INDEX_MCP   6  INDEX_PIP   7  INDEX_DIP   8  INDEX_TIP
  9  MIDDLE_MCP  10 MIDDLE_PIP  11 MIDDLE_DIP  12 MIDDLE_TIP
  13 RING_MCP    14 RING_PIP    15 RING_DIP    16 RING_TIP
  17 PINKY_MCP   18 PINKY_PIP   19 PINKY_DIP   20 PINKY_TIP

Coordinate system:
  x, y in [0,1] image space (y increases downward)
  z is depth (negative = toward camera)

Landmark layout per finger:
  MCP (knuckle) → PIP → DIP → TIP

A finger is EXTENDED when its TIP y < its MCP y (tip is higher in image = closer to top).
A finger is CURLED when its TIP y > its MCP y.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

# ── MediaPipe index constants ─────────────────────────────────────────────────
_WRIST = 0
_THUMB_CMC, _THUMB_MCP, _THUMB_IP, _THUMB_TIP = 1, 2, 3, 4
_INDEX_MCP, _INDEX_PIP, _INDEX_DIP, _INDEX_TIP = 5, 6, 7, 8
_MIDDLE_MCP, _MIDDLE_PIP, _MIDDLE_DIP, _MIDDLE_TIP = 9, 10, 11, 12
_RING_MCP, _RING_PIP, _RING_DIP, _RING_TIP = 13, 14, 15, 16
_PINKY_MCP, _PINKY_PIP, _PINKY_DIP, _PINKY_TIP = 17, 18, 19, 20

# GestureType enum values — match perception.proto GestureType
GESTURE_TYPE_UNSPECIFIED = 0
GESTURE_TYPE_STOP        = 1
GESTURE_TYPE_POINT       = 2
GESTURE_TYPE_CONFIRM     = 3
GESTURE_TYPE_CANCEL      = 4


@dataclass
class Point3D:
    x: float
    y: float
    z: float


class GestureResult(NamedTuple):
    gesture_type: int    # GestureType enum int
    confidence: float    # 0.0–1.0
    pointing_vector: tuple[float, float, float] | None  # only for POINT


def _lm(landmarks: list[list[float]], idx: int) -> Point3D:
    p = landmarks[idx]
    return Point3D(x=p[0], y=p[1], z=p[2] if len(p) > 2 else 0.0)


def _is_extended(tip: Point3D, mcp: Point3D, margin: float = 0.02) -> bool:
    """Finger is extended when tip is strictly above (lower y) the MCP knuckle."""
    return tip.y < mcp.y - margin


def _is_curled(tip: Point3D, mcp: Point3D, margin: float = 0.02) -> bool:
    return tip.y > mcp.y + margin


def _thumb_up(landmarks: list[list[float]]) -> float:
    """Thumbs-up: thumb tip above wrist, other 4 fingers curled."""
    thumb_tip = _lm(landmarks, _THUMB_TIP)
    wrist = _lm(landmarks, _WRIST)
    if thumb_tip.y >= wrist.y:
        return 0.0

    index_curled  = _is_curled(_lm(landmarks, _INDEX_TIP),  _lm(landmarks, _INDEX_MCP))
    middle_curled = _is_curled(_lm(landmarks, _MIDDLE_TIP), _lm(landmarks, _MIDDLE_MCP))
    ring_curled   = _is_curled(_lm(landmarks, _RING_TIP),   _lm(landmarks, _RING_MCP))
    pinky_curled  = _is_curled(_lm(landmarks, _PINKY_TIP),  _lm(landmarks, _PINKY_MCP))

    curl_count = sum([index_curled, middle_curled, ring_curled, pinky_curled])
    if curl_count < 3:
        return 0.0

    # Confidence: how far the thumb is above the wrist
    height_ratio = min(1.0, (wrist.y - thumb_tip.y) * 4)
    return 0.5 + 0.5 * (curl_count / 4) * height_ratio


def _open_palm(landmarks: list[list[float]]) -> float:
    """Stop / open palm: all 5 fingers extended."""
    fingers = [
        (_THUMB_TIP, _THUMB_MCP),
        (_INDEX_TIP, _INDEX_MCP),
        (_MIDDLE_TIP, _MIDDLE_MCP),
        (_RING_TIP, _RING_MCP),
        (_PINKY_TIP, _PINKY_MCP),
    ]
    extended = sum(
        1 for tip_i, mcp_i in fingers
        if _is_extended(_lm(landmarks, tip_i), _lm(landmarks, mcp_i))
    )
    if extended < 4:
        return 0.0
    return 0.5 + 0.5 * (extended / 5)


def _point_gesture(landmarks: list[list[float]]) -> float:
    """Pointing: only index finger extended, others curled."""
    index_ext  = _is_extended(_lm(landmarks, _INDEX_TIP),  _lm(landmarks, _INDEX_MCP))
    middle_curl = _is_curled(_lm(landmarks, _MIDDLE_TIP), _lm(landmarks, _MIDDLE_MCP))
    ring_curl   = _is_curled(_lm(landmarks, _RING_TIP),   _lm(landmarks, _RING_MCP))
    pinky_curl  = _is_curled(_lm(landmarks, _PINKY_TIP),  _lm(landmarks, _PINKY_MCP))

    if not index_ext:
        return 0.0
    curled_count = sum([middle_curl, ring_curl, pinky_curl])
    if curled_count < 2:
        return 0.0
    return 0.5 + 0.5 * (curled_count / 3)


def _fist(landmarks: list[list[float]]) -> float:
    """Cancel / fist: all four non-thumb fingers curled."""
    fingers = [
        (_INDEX_TIP, _INDEX_MCP),
        (_MIDDLE_TIP, _MIDDLE_MCP),
        (_RING_TIP, _RING_MCP),
        (_PINKY_TIP, _PINKY_MCP),
    ]
    curled = sum(
        1 for tip_i, mcp_i in fingers
        if _is_curled(_lm(landmarks, tip_i), _lm(landmarks, mcp_i))
    )
    if curled < 3:
        return 0.0
    return 0.5 + 0.5 * (curled / 4)


def _compute_pointing_vector(
    landmarks: list[list[float]],
) -> tuple[float, float, float]:
    """Pointing vector: from index MCP (tag 5) to index TIP (tag 8)."""
    mcp = _lm(landmarks, _INDEX_MCP)
    tip = _lm(landmarks, _INDEX_TIP)
    dx, dy, dz = tip.x - mcp.x, tip.y - mcp.y, tip.z - mcp.z
    mag = (dx**2 + dy**2 + dz**2) ** 0.5
    if mag < 1e-6:
        return (0.0, 0.0, 0.0)
    return (dx / mag, dy / mag, dz / mag)


class GestureClassifier:
    """
    Rule-based gesture classifier.

    Input: 21 Point3D landmarks as list[list[float]] with [x, y, z] per point.
    Output: GestureResult(gesture_type, confidence, pointing_vector)
    """

    def classify(self, landmarks: list[list[float]]) -> GestureResult:
        if len(landmarks) != 21:
            return GestureResult(GESTURE_TYPE_UNSPECIFIED, 0.0, None)

        # Evaluate each gesture and pick the one with highest confidence
        candidates: list[tuple[int, float]] = [
            (GESTURE_TYPE_CONFIRM, _thumb_up(landmarks)),
            (GESTURE_TYPE_STOP,    _open_palm(landmarks)),
            (GESTURE_TYPE_POINT,   _point_gesture(landmarks)),
            (GESTURE_TYPE_CANCEL,  _fist(landmarks)),
        ]

        best_type, best_conf = GESTURE_TYPE_UNSPECIFIED, 0.0
        for g_type, conf in candidates:
            if conf > best_conf:
                best_conf = conf
                best_type = g_type

        pointing_vector: tuple[float, float, float] | None = None
        if best_type == GESTURE_TYPE_POINT and best_conf > 0:
            pointing_vector = _compute_pointing_vector(landmarks)

        if best_conf < 0.5:
            return GestureResult(GESTURE_TYPE_UNSPECIFIED, 0.0, None)

        return GestureResult(
            gesture_type=best_type,
            confidence=round(best_conf, 3),
            pointing_vector=pointing_vector,
        )
