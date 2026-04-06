"""
Tests for GestureAnchorBridge.on_gesture_event.

Each test uses a fresh in-memory AnchorRegistry (tmp_path fixture) to stay
isolated. Tests cover every return path: anchor_registered, anchors_bonded,
anchor_thrown, world_expand, and the None fallback.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.spatial.anchor_registry import AnchorRegistry
from app.spatial.gesture_anchor_bridge import GestureAnchorBridge


@pytest.fixture
def registry(tmp_path: Path) -> AnchorRegistry:
    return AnchorRegistry(db_path=tmp_path / "anchors.db")


@pytest.fixture
def bridge(registry: AnchorRegistry) -> GestureAnchorBridge:
    return GestureAnchorBridge(registry)


# ── POINT → anchor_registered ─────────────────────────────────────────────────

class TestPointGesture:
    def test_point_with_vector_returns_anchor_registered(
        self, bridge: GestureAnchorBridge
    ) -> None:
        result = bridge.on_gesture_event(
            gesture="point",
            two_hand_gesture="NONE",
            pointing_vector=[0.0, -1.0, 0.0],
            session_id="s1",
        )
        assert result is not None
        assert result["type"] == "anchor_registered"

    def test_point_result_has_anchor_id(self, bridge: GestureAnchorBridge) -> None:
        result = bridge.on_gesture_event("point", "NONE", [0.5, 0.5, -0.7], "s1")
        assert "anchor_id" in result
        assert len(result["anchor_id"]) > 0

    def test_point_result_payload_matches_registry(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry
    ) -> None:
        result = bridge.on_gesture_event("point", "NONE", [0.1, 0.2, 0.3], "s1")
        anchor = registry.get_anchor(result["anchor_id"])
        assert anchor is not None
        payload = result["payload"]
        assert payload["x"] == pytest.approx(0.1)
        assert payload["y"] == pytest.approx(0.2)
        assert payload["z"] == pytest.approx(0.3)
        assert payload["label"] == "object"

    def test_point_without_vector_returns_none(
        self, bridge: GestureAnchorBridge
    ) -> None:
        result = bridge.on_gesture_event("point", "NONE", None, "s1")
        assert result is None

    def test_non_point_gesture_with_vector_returns_none(
        self, bridge: GestureAnchorBridge
    ) -> None:
        result = bridge.on_gesture_event("stop", "NONE", [0.0, -1.0, 0.0], "s1")
        assert result is None


# ── BOND → anchors_bonded ─────────────────────────────────────────────────────

class TestBondGesture:
    def test_bond_with_two_anchors_returns_bonded_event(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry
    ) -> None:
        registry.register_anchor((0.1, 0.0, 0.0), "a")
        registry.register_anchor((0.2, 0.0, 0.0), "b")
        result = bridge.on_gesture_event("none", "BOND", None, "s1")
        assert result is not None
        assert result["type"] == "anchors_bonded"

    def test_bond_returns_two_anchor_ids(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry
    ) -> None:
        id1 = registry.register_anchor((0.0, 0.0, -1.0), "x")
        id2 = registry.register_anchor((0.1, 0.0, -1.0), "y")
        result = bridge.on_gesture_event("none", "BOND", None, "s1")
        assert len(result["anchor_ids"]) == 2
        assert set(result["anchor_ids"]) == {id1, id2}

    def test_bond_picks_nearest_pair(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry
    ) -> None:
        # a and b are 0.1 apart; a and c are 10.0 apart
        id_a = registry.register_anchor((0.0, 0.0, 0.0), "a")
        id_b = registry.register_anchor((0.1, 0.0, 0.0), "b")
        _id_c = registry.register_anchor((10.0, 0.0, 0.0), "c")
        result = bridge.on_gesture_event("none", "BOND", None, "s1")
        assert set(result["anchor_ids"]) == {id_a, id_b}

    def test_bond_with_no_anchors_returns_none(
        self, bridge: GestureAnchorBridge
    ) -> None:
        result = bridge.on_gesture_event("none", "BOND", None, "s1")
        assert result is None

    def test_bond_with_one_anchor_returns_none(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry
    ) -> None:
        registry.register_anchor((0.5, 0.5, 0.0), "solo")
        result = bridge.on_gesture_event("none", "BOND", None, "s1")
        assert result is None


# ── THROW → anchor_thrown ─────────────────────────────────────────────────────

class TestThrowGesture:
    def test_throw_with_anchor_returns_thrown_event(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry
    ) -> None:
        registry.register_anchor((0.0, 0.0, -1.0), "obj")
        result = bridge.on_gesture_event("none", "THROW", [0.0, 0.0, -1.0], "s1")
        assert result is not None
        assert result["type"] == "anchor_thrown"

    def test_throw_result_has_anchor_id_and_velocity(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry
    ) -> None:
        aid = registry.register_anchor((0.0, 0.0, -1.0), "obj")
        result = bridge.on_gesture_event("none", "THROW", [0.1, 0.0, -0.9], "s1")
        assert "anchor_id" in result
        assert "velocity" in result
        assert isinstance(result["velocity"], list)

    def test_throw_velocity_matches_pointing_vector(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry
    ) -> None:
        registry.register_anchor((0.0, 0.0, -1.0), "obj")
        vec = [0.3, 0.1, -0.8]
        result = bridge.on_gesture_event("none", "THROW", vec, "s1")
        assert result["velocity"] == vec

    def test_throw_no_vector_uses_default_velocity(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry
    ) -> None:
        registry.register_anchor((0.0, 0.0, -1.0), "obj")
        result = bridge.on_gesture_event("none", "THROW", None, "s1")
        assert result["velocity"] == [0.0, 0.0, -1.0]

    def test_throw_picks_most_aligned_anchor(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry
    ) -> None:
        # forward = (0,0,-1); anchor_f is directly ahead, anchor_b is behind
        id_f = registry.register_anchor((0.0, 0.0, -1.0), "forward")
        _id_b = registry.register_anchor((0.0, 0.0, 1.0), "behind")
        result = bridge.on_gesture_event("none", "THROW", [0.0, 0.0, -1.0], "s1")
        assert result["anchor_id"] == id_f

    def test_throw_with_no_anchors_returns_none(
        self, bridge: GestureAnchorBridge
    ) -> None:
        result = bridge.on_gesture_event("none", "THROW", [0.0, 0.0, -1.0], "s1")
        assert result is None


# ── EXPAND → world_expand ─────────────────────────────────────────────────────

class TestExpandGesture:
    def test_expand_returns_world_expand_event(
        self, bridge: GestureAnchorBridge
    ) -> None:
        result = bridge.on_gesture_event("none", "EXPAND", None, "s1")
        assert result is not None
        assert result["type"] == "world_expand"

    def test_expand_factor_is_1_5(self, bridge: GestureAnchorBridge) -> None:
        result = bridge.on_gesture_event("none", "EXPAND", None, "s1")
        assert result["factor"] == pytest.approx(1.5)


# ── fallback → None ───────────────────────────────────────────────────────────

class TestFallback:
    def test_none_gesture_returns_none(self, bridge: GestureAnchorBridge) -> None:
        result = bridge.on_gesture_event("none", "NONE", None, "s1")
        assert result is None

    def test_hold_returns_none(self, bridge: GestureAnchorBridge) -> None:
        result = bridge.on_gesture_event("none", "HOLD", None, "s1")
        assert result is None

    def test_unknown_gesture_strings_return_none(
        self, bridge: GestureAnchorBridge
    ) -> None:
        result = bridge.on_gesture_event("wave", "UNKNOWN", None, "s1")
        assert result is None

    def test_stop_gesture_returns_none(self, bridge: GestureAnchorBridge) -> None:
        result = bridge.on_gesture_event("stop", "NONE", None, "s1")
        assert result is None

    def test_confirm_gesture_returns_none(self, bridge: GestureAnchorBridge) -> None:
        result = bridge.on_gesture_event("confirm", "NONE", None, "s1")
        assert result is None
