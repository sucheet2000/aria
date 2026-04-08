"""
Week 8: Gesture classifier tests.

- test_stop_gesture: open palm landmarks → HAND_GESTURE_OPEN_PALM
- test_point_gesture: pointing landmarks → POINT + vector computed
- test_fist_gesture: fist landmarks → HAND_GESTURE_PINCH
- test_thumb_up_gesture: thumbs-up landmarks → HAND_GESTURE_THUMB_UP
- test_classifier_confidence: each gesture returns 0.0–1.0 confidence
"""
from __future__ import annotations

import pytest

from app.pipeline.gesture_classifier import (
    HAND_GESTURE_OPEN_PALM,
    HAND_GESTURE_PINCH,
    HAND_GESTURE_POINT,
    HAND_GESTURE_THUMB_UP,
    HAND_GESTURE_UNSPECIFIED,
    GestureClassifier,
)

# ── landmark factory helpers ──────────────────────────────────────────────────
#
# MediaPipe normalized coords: x,y in [0,1] with y increasing downward.
# We construct minimal synthetic landmarks that satisfy the rule conditions.
#
# A finger is extended when tip.y < mcp.y  (tip is higher = smaller y).
# A finger is curled  when tip.y > mcp.y  (tip is lower  = larger  y).
#
# Base: 21 landmarks all at (0.5, 0.5, 0.0).


def _base_landmarks() -> list[list[float]]:
    return [[0.5, 0.5, 0.0] for _ in range(21)]


def _open_palm_landmarks() -> list[list[float]]:
    """All 5 fingers extended: tip.y << mcp.y for every finger."""
    lm = _base_landmarks()
    # Wrist at y=0.9 (bottom of image)
    lm[0]  = [0.5, 0.9, 0.0]  # WRIST

    # Thumb: CMC=1, MCP=2, IP=3, TIP=4
    lm[1] = [0.35, 0.75, 0.0]  # THUMB_CMC
    lm[2] = [0.30, 0.65, 0.0]  # THUMB_MCP
    lm[3] = [0.25, 0.55, 0.0]  # THUMB_IP
    lm[4] = [0.20, 0.45, 0.0]  # THUMB_TIP — extended (y < MCP y)

    _extend_finger(lm, mcp=5, pip=6, dip=7, tip=8, base_y=0.75)    # index
    _extend_finger(lm, mcp=9, pip=10, dip=11, tip=12, base_y=0.75) # middle
    _extend_finger(lm, mcp=13, pip=14, dip=15, tip=16, base_y=0.75) # ring
    _extend_finger(lm, mcp=17, pip=18, dip=19, tip=20, base_y=0.75) # pinky
    return lm


def _point_landmarks() -> list[list[float]]:
    """Index extended, others curled."""
    lm = _base_landmarks()
    lm[0] = [0.5, 0.9, 0.0]  # WRIST

    _extend_finger(lm, mcp=5, pip=6, dip=7, tip=8, base_y=0.75)    # INDEX extended
    _curl_finger(lm, mcp=9,  pip=10, dip=11, tip=12, base_y=0.7)   # middle curled
    _curl_finger(lm, mcp=13, pip=14, dip=15, tip=16, base_y=0.7)   # ring curled
    _curl_finger(lm, mcp=17, pip=18, dip=19, tip=20, base_y=0.7)   # pinky curled
    return lm


def _fist_landmarks() -> list[list[float]]:
    """All 4 non-thumb fingers curled; thumb also tucked (below wrist level)."""
    lm = _base_landmarks()
    lm[0] = [0.5, 0.60, 0.0]  # WRIST at mid-image

    # Thumb tucked: tip at same y as wrist (not above it → not thumbs-up)
    lm[1] = [0.45, 0.65, 0.0]  # THUMB_CMC
    lm[2] = [0.42, 0.68, 0.0]  # THUMB_MCP
    lm[3] = [0.40, 0.71, 0.0]  # THUMB_IP
    lm[4] = [0.38, 0.75, 0.0]  # THUMB_TIP — below wrist, not extended

    _curl_finger(lm, mcp=5,  pip=6,  dip=7,  tip=8,  base_y=0.65)
    _curl_finger(lm, mcp=9,  pip=10, dip=11, tip=12, base_y=0.65)
    _curl_finger(lm, mcp=13, pip=14, dip=15, tip=16, base_y=0.65)
    _curl_finger(lm, mcp=17, pip=18, dip=19, tip=20, base_y=0.65)
    return lm


def _thumbs_up_landmarks() -> list[list[float]]:
    """Thumb tip well above wrist, other fingers curled."""
    lm = _base_landmarks()
    lm[0] = [0.5, 0.85, 0.0]  # WRIST (low in image)

    # Thumb pointing up: TIP has small y (near top of image)
    lm[1] = [0.5, 0.75, 0.0]  # CMC
    lm[2] = [0.5, 0.70, 0.0]  # MCP
    lm[3] = [0.5, 0.60, 0.0]  # IP
    lm[4] = [0.5, 0.45, 0.0]  # TIP — well above wrist

    _curl_finger(lm, mcp=5,  pip=6,  dip=7,  tip=8,  base_y=0.7)
    _curl_finger(lm, mcp=9,  pip=10, dip=11, tip=12, base_y=0.7)
    _curl_finger(lm, mcp=13, pip=14, dip=15, tip=16, base_y=0.7)
    _curl_finger(lm, mcp=17, pip=18, dip=19, tip=20, base_y=0.7)
    return lm


def _extend_finger(
    lm: list[list[float]], mcp: int, pip: int, dip: int, tip: int, base_y: float
) -> None:
    """Place finger landmarks so tip is clearly above mcp (extended)."""
    lm[mcp] = [0.5, base_y, 0.0]
    lm[pip] = [0.5, base_y - 0.08, 0.0]
    lm[dip] = [0.5, base_y - 0.16, 0.0]
    lm[tip] = [0.5, base_y - 0.24, 0.0]  # tip above mcp


def _curl_finger(
    lm: list[list[float]], mcp: int, pip: int, dip: int, tip: int, base_y: float
) -> None:
    """Place finger landmarks so tip is clearly below mcp (curled)."""
    lm[mcp] = [0.5, base_y, 0.0]
    lm[pip] = [0.5, base_y + 0.05, 0.0]
    lm[dip] = [0.5, base_y + 0.09, 0.0]
    lm[tip] = [0.5, base_y + 0.13, 0.0]  # tip below mcp


# ── tests ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def classifier() -> GestureClassifier:
    return GestureClassifier()


class TestStopGesture:
    def test_open_palm_returns_stop(self, classifier: GestureClassifier) -> None:
        result = classifier.classify(_open_palm_landmarks())
        assert result.gesture_type == HAND_GESTURE_OPEN_PALM

    def test_confidence_in_range(self, classifier: GestureClassifier) -> None:
        result = classifier.classify(_open_palm_landmarks())
        assert 0.0 <= result.confidence <= 1.0


class TestPointGesture:
    def test_point_returns_point(self, classifier: GestureClassifier) -> None:
        result = classifier.classify(_point_landmarks())
        assert result.gesture_type == HAND_GESTURE_POINT

    def test_point_has_pointing_vector(self, classifier: GestureClassifier) -> None:
        result = classifier.classify(_point_landmarks())
        assert result.pointing_vector is not None

    def test_pointing_vector_is_unit(self, classifier: GestureClassifier) -> None:
        result = classifier.classify(_point_landmarks())
        vx, vy, vz = result.pointing_vector
        magnitude = (vx**2 + vy**2 + vz**2) ** 0.5
        assert magnitude == pytest.approx(1.0, abs=1e-5)

    def test_confidence_in_range(self, classifier: GestureClassifier) -> None:
        result = classifier.classify(_point_landmarks())
        assert 0.0 <= result.confidence <= 1.0


class TestThumbUpGesture:
    def test_thumb_up_gesture(self, classifier: GestureClassifier) -> None:
        result = classifier.classify(_thumbs_up_landmarks())
        assert result.gesture_type == HAND_GESTURE_THUMB_UP

    def test_confidence_in_range(self, classifier: GestureClassifier) -> None:
        result = classifier.classify(_thumbs_up_landmarks())
        assert 0.0 <= result.confidence <= 1.0


class TestFistGesture:
    def test_fist_returns_cancel(self, classifier: GestureClassifier) -> None:
        result = classifier.classify(_fist_landmarks())
        assert result.gesture_type == HAND_GESTURE_PINCH

    def test_no_pointing_vector_for_fist(self, classifier: GestureClassifier) -> None:
        result = classifier.classify(_fist_landmarks())
        assert result.pointing_vector is None

    def test_confidence_in_range(self, classifier: GestureClassifier) -> None:
        result = classifier.classify(_fist_landmarks())
        assert 0.0 <= result.confidence <= 1.0


class TestClassifierConfidence:
    def test_stop_confidence_between_0_and_1(self, classifier: GestureClassifier) -> None:
        r = classifier.classify(_open_palm_landmarks())
        assert 0.0 <= r.confidence <= 1.0

    def test_point_confidence_between_0_and_1(self, classifier: GestureClassifier) -> None:
        r = classifier.classify(_point_landmarks())
        assert 0.0 <= r.confidence <= 1.0

    def test_fist_confidence_between_0_and_1(self, classifier: GestureClassifier) -> None:
        r = classifier.classify(_fist_landmarks())
        assert 0.0 <= r.confidence <= 1.0

    def test_confirm_confidence_between_0_and_1(self, classifier: GestureClassifier) -> None:
        r = classifier.classify(_thumbs_up_landmarks())
        assert 0.0 <= r.confidence <= 1.0

    def test_wrong_landmark_count_returns_unspecified(
        self, classifier: GestureClassifier
    ) -> None:
        result = classifier.classify([[0.5, 0.5, 0.0]] * 10)  # wrong count
        assert result.gesture_type == HAND_GESTURE_UNSPECIFIED
        assert result.confidence == 0.0

    def test_empty_landmarks_returns_unspecified(
        self, classifier: GestureClassifier
    ) -> None:
        result = classifier.classify([])
        assert result.gesture_type == HAND_GESTURE_UNSPECIFIED
