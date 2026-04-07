"""
Two-hand gesture tests for GestureClassifier.classify_two_hand and compute_velocity.

Landmark conventions (same as test_gesture_classifier.py):
  x, y in [0,1], y increases downward.
  Finger extended: tip.y < mcp.y
  Finger curled:   tip.y > mcp.y
"""
from __future__ import annotations

import math

import pytest

from app.pipeline.gesture_classifier import (
    TWO_HAND_BOND,
    TWO_HAND_EXPAND,
    TWO_HAND_HOLD,
    TWO_HAND_NONE,
    TWO_HAND_THROW,
    GestureClassifier,
    TwoHandGesture,
)

# ── landmark helpers ───────────────────────────────────────────────────────────

def _base(wrist_x: float = 0.5, wrist_y: float = 0.9) -> list[list[float]]:
    lm = [[0.5, 0.5, 0.0] for _ in range(21)]
    lm[0] = [wrist_x, wrist_y, 0.0]
    return lm


def _extend(lm: list[list[float]], mcp: int, pip: int, dip: int, tip: int, base_y: float) -> None:
    lm[mcp] = [lm[0][0], base_y, 0.0]
    lm[pip] = [lm[0][0], base_y - 0.08, 0.0]
    lm[dip] = [lm[0][0], base_y - 0.16, 0.0]
    lm[tip] = [lm[0][0], base_y - 0.24, 0.0]


def _curl(lm: list[list[float]], mcp: int, pip: int, dip: int, tip: int, base_y: float) -> None:
    lm[mcp] = [lm[0][0], base_y, 0.0]
    lm[pip] = [lm[0][0], base_y + 0.05, 0.0]
    lm[dip] = [lm[0][0], base_y + 0.09, 0.0]
    lm[tip] = [lm[0][0], base_y + 0.13, 0.0]


def _open_palm_lm(wrist_x: float = 0.5) -> list[list[float]]:
    """All 5 fingers extended."""
    lm = _base(wrist_x=wrist_x)
    lm[1] = [wrist_x - 0.15, 0.75, 0.0]
    lm[2] = [wrist_x - 0.20, 0.65, 0.0]
    lm[3] = [wrist_x - 0.25, 0.55, 0.0]
    lm[4] = [wrist_x - 0.30, 0.45, 0.0]
    _extend(lm, 5,  6,  7,  8,  0.75)
    _extend(lm, 9,  10, 11, 12, 0.75)
    _extend(lm, 13, 14, 15, 16, 0.75)
    _extend(lm, 17, 18, 19, 20, 0.75)
    return lm


def _fist_lm(wrist_x: float = 0.5, wrist_y: float = 0.9) -> list[list[float]]:
    """All 4 non-thumb fingers curled, thumb tucked."""
    lm = _base(wrist_x=wrist_x, wrist_y=wrist_y)
    # Thumb below wrist (not thumbs-up)
    lm[1] = [wrist_x + 0.03, wrist_y + 0.02, 0.0]
    lm[2] = [wrist_x + 0.05, wrist_y + 0.04, 0.0]
    lm[3] = [wrist_x + 0.07, wrist_y + 0.06, 0.0]
    lm[4] = [wrist_x + 0.09, wrist_y + 0.08, 0.0]
    base = wrist_y + 0.02
    _curl(lm, 5,  6,  7,  8,  base)
    _curl(lm, 9,  10, 11, 12, base)
    _curl(lm, 13, 14, 15, 16, base)
    _curl(lm, 17, 18, 19, 20, base)
    return lm


def _neutral_lm(wrist_x: float = 0.5) -> list[list[float]]:
    """No clear gesture — all landmarks near centre."""
    lm = [[wrist_x, 0.5, 0.0] for _ in range(21)]
    return lm


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def clf() -> GestureClassifier:
    return GestureClassifier()


# ── TwoHandGesture dataclass ───────────────────────────────────────────────────

class TestTwoHandGestureDataclass:
    def test_defaults(self) -> None:
        g = TwoHandGesture("NONE", 0.0)
        assert g.velocity_vector is None
        assert g.distance is None

    def test_all_fields(self) -> None:
        g = TwoHandGesture("BOND", 1.0, velocity_vector=(0.1, 0.2, 0.0), distance=0.03)
        assert g.gesture_type == "BOND"
        assert g.confidence == 1.0
        assert g.velocity_vector == (0.1, 0.2, 0.0)
        assert g.distance == pytest.approx(0.03)


# ── HOLD ───────────────────────────────────────────────────────────────────────

class TestHold:
    def test_left_open_palm_returns_hold(self, clf: GestureClassifier) -> None:
        result = clf.classify_two_hand(_open_palm_lm(wrist_x=0.3), _fist_lm(wrist_x=0.5))
        assert result.gesture_type == TWO_HAND_HOLD

    def test_right_open_palm_returns_hold(self, clf: GestureClassifier) -> None:
        result = clf.classify_two_hand(_fist_lm(wrist_x=0.3), _open_palm_lm(wrist_x=0.5))
        assert result.gesture_type == TWO_HAND_HOLD

    def test_hold_confidence_in_range(self, clf: GestureClassifier) -> None:
        result = clf.classify_two_hand(_open_palm_lm(wrist_x=0.3), _fist_lm(wrist_x=0.5))
        assert 0.0 < result.confidence <= 1.0


# ── EXPAND ─────────────────────────────────────────────────────────────────────

class TestExpand:
    def test_wrists_far_apart_returns_expand(self, clf: GestureClassifier) -> None:
        # wrist x=0.1 vs x=0.9 → distance = 0.8 > 0.3
        result = clf.classify_two_hand(_neutral_lm(wrist_x=0.1), _neutral_lm(wrist_x=0.9))
        assert result.gesture_type == TWO_HAND_EXPAND

    def test_expand_distance_field_set(self, clf: GestureClassifier) -> None:
        result = clf.classify_two_hand(_neutral_lm(wrist_x=0.1), _neutral_lm(wrist_x=0.9))
        assert result.distance is not None
        assert result.distance > 0.3

    def test_expand_confidence_in_range(self, clf: GestureClassifier) -> None:
        result = clf.classify_two_hand(_neutral_lm(wrist_x=0.1), _neutral_lm(wrist_x=0.9))
        assert 0.0 < result.confidence <= 1.0

    def test_wrists_close_not_expand(self, clf: GestureClassifier) -> None:
        result = clf.classify_two_hand(_neutral_lm(wrist_x=0.45), _neutral_lm(wrist_x=0.55))
        assert result.gesture_type != TWO_HAND_EXPAND


# ── THROW ──────────────────────────────────────────────────────────────────────

class TestThrow:
    # Wrists kept < 0.3 apart so EXPAND is not triggered.
    # Wrist moves 0.05 units in 33 ms → speed = 0.05/33 ≈ 0.00152 > threshold 0.0005.
    def test_fist_then_open_palm_returns_throw(self, clf: GestureClassifier) -> None:
        # Frame 1: right fist at x=0.5
        clf.classify_two_hand(_neutral_lm(wrist_x=0.4), _fist_lm(wrist_x=0.5))
        # Frame 2: right open palm at x=0.55 (wrist moved 0.05 units in 33ms)
        result = clf.classify_two_hand(_neutral_lm(wrist_x=0.4), _open_palm_lm(wrist_x=0.55))
        assert result.gesture_type == TWO_HAND_THROW

    def test_throw_has_velocity_vector(self, clf: GestureClassifier) -> None:
        clf.classify_two_hand(_neutral_lm(wrist_x=0.4), _fist_lm(wrist_x=0.5))
        result = clf.classify_two_hand(_neutral_lm(wrist_x=0.4), _open_palm_lm(wrist_x=0.55))
        assert result.velocity_vector is not None

    def test_throw_confidence_in_range(self, clf: GestureClassifier) -> None:
        clf.classify_two_hand(_neutral_lm(wrist_x=0.4), _fist_lm(wrist_x=0.5))
        result = clf.classify_two_hand(_neutral_lm(wrist_x=0.4), _open_palm_lm(wrist_x=0.55))
        assert 0.0 < result.confidence <= 1.0

    def test_no_throw_without_prior_fist(self, clf: GestureClassifier) -> None:
        # First call — no previous state; open palm should not be THROW
        result = clf.classify_two_hand(_neutral_lm(wrist_x=0.4), _open_palm_lm(wrist_x=0.55))
        assert result.gesture_type != TWO_HAND_THROW

    def test_left_hand_throw(self, clf: GestureClassifier) -> None:
        # Frame 1: left fist at x=0.4
        clf.classify_two_hand(_fist_lm(wrist_x=0.4), _neutral_lm(wrist_x=0.5))
        # Frame 2: left open palm at x=0.45 (wrist moved 0.05 units)
        result = clf.classify_two_hand(_open_palm_lm(wrist_x=0.45), _neutral_lm(wrist_x=0.5))
        assert result.gesture_type == TWO_HAND_THROW


# ── BOND ───────────────────────────────────────────────────────────────────────

class TestBond:
    def test_wrists_touching_returns_bond(self, clf: GestureClassifier) -> None:
        # wrists at nearly same position
        result = clf.classify_two_hand(_neutral_lm(wrist_x=0.50), _neutral_lm(wrist_x=0.51))
        assert result.gesture_type == TWO_HAND_BOND

    def test_bond_distance_below_threshold(self, clf: GestureClassifier) -> None:
        result = clf.classify_two_hand(_neutral_lm(wrist_x=0.50), _neutral_lm(wrist_x=0.51))
        assert result.distance is not None
        assert result.distance < 0.05

    def test_bond_confidence_is_1(self, clf: GestureClassifier) -> None:
        result = clf.classify_two_hand(_neutral_lm(wrist_x=0.50), _neutral_lm(wrist_x=0.51))
        assert result.confidence == 1.0


# ── NONE ───────────────────────────────────────────────────────────────────────

class TestNone:
    def test_neutral_landmarks_returns_none(self, clf: GestureClassifier) -> None:
        # wrists at 0.38 / 0.62 — distance ≈ 0.24 < 0.3, no open palm
        result = clf.classify_two_hand(_fist_lm(wrist_x=0.38), _fist_lm(wrist_x=0.62))
        assert result.gesture_type == TWO_HAND_NONE

    def test_none_confidence_is_zero(self, clf: GestureClassifier) -> None:
        result = clf.classify_two_hand(_fist_lm(wrist_x=0.38), _fist_lm(wrist_x=0.62))
        assert result.confidence == 0.0


# ── compute_velocity ───────────────────────────────────────────────────────────

class TestComputeVelocity:
    def test_zero_dt_returns_zero_vector(self, clf: GestureClassifier) -> None:
        lm = _neutral_lm()
        v = clf.compute_velocity(lm, lm, dt_ms=0.0)
        assert v == (0.0, 0.0, 0.0)

    def test_velocity_units_normalized_per_ms(self, clf: GestureClassifier) -> None:
        prev = _neutral_lm(wrist_x=0.5)
        curr = _neutral_lm(wrist_x=0.6)  # wrist moved 0.1 in x
        v = clf.compute_velocity(prev, curr, dt_ms=10.0)
        assert v[0] == pytest.approx(0.01, rel=1e-5)  # 0.1 / 10 ms
        assert v[1] == pytest.approx(0.0, abs=1e-9)
        assert v[2] == pytest.approx(0.0, abs=1e-9)

    def test_velocity_negative_direction(self, clf: GestureClassifier) -> None:
        prev = _neutral_lm(wrist_x=0.7)
        curr = _neutral_lm(wrist_x=0.5)
        v = clf.compute_velocity(prev, curr, dt_ms=20.0)
        assert v[0] == pytest.approx(-0.01, rel=1e-5)

    def test_velocity_z_component(self, clf: GestureClassifier) -> None:
        prev = [[0.5, 0.5, 0.0]] * 21
        curr = [[0.5, 0.5, 0.2]] * 21
        v = clf.compute_velocity(prev, curr, dt_ms=10.0)
        assert v[2] == pytest.approx(0.02, rel=1e-5)

    def test_velocity_magnitude_is_scalar_speed(self, clf: GestureClassifier) -> None:
        prev = _neutral_lm(wrist_x=0.5)
        curr = _neutral_lm(wrist_x=0.8)
        v = clf.compute_velocity(prev, curr, dt_ms=30.0)
        speed = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
        assert speed == pytest.approx(0.3 / 30.0, rel=1e-5)
