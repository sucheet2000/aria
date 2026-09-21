"""Workstream D — a point must be intentional before it becomes an anchor.

Every cognition request carrying a point gesture used to register a new anchor.
A user holding a point for a few seconds, or simply talking while their hand
rested in a pointing shape, produced one anchor per request — a pile of
near-identical anchors that the user never asked for and cannot easily undo.

An anchor now needs a steady point: the same direction, held for a dwell
window. Afterwards the same direction is on cooldown, so continuing to point
does not spam, while a genuinely different direction can still anchor.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.spatial.anchor_registry import AnchorRegistry
from app.spatial.gesture_anchor_bridge import GestureAnchorBridge


@pytest.fixture
def registry(tmp_path: Path) -> AnchorRegistry:
    return AnchorRegistry(db_path=tmp_path / "anchors.db")


class FakeClock:
    """Monotonic seconds under the test's control."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def bridge(registry: AnchorRegistry, clock: FakeClock) -> GestureAnchorBridge:
    return GestureAnchorBridge(registry, clock=clock)


FORWARD = [0.0, 0.0, -1.0]
LEFT = [-1.0, 0.0, 0.0]


def point(bridge: GestureAnchorBridge, vec: list[float], owner: str = "u1"):
    return bridge.on_gesture_event("point", "NONE", vec, "s1", owner)


def anchors_for(registry: AnchorRegistry, owner: str = "u1") -> int:
    return len(registry.list_anchors(owner))


class TestDwell:
    def test_1_a_transient_point_creates_no_anchor(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry, clock: FakeClock
    ) -> None:
        assert point(bridge, FORWARD) is None
        clock.advance(0.2)
        assert point(bridge, FORWARD) is None
        assert anchors_for(registry) == 0

    def test_2_a_steady_point_creates_exactly_one_anchor(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry, clock: FakeClock
    ) -> None:
        point(bridge, FORWARD)
        clock.advance(2.0)
        event = point(bridge, FORWARD)

        assert event is not None
        assert event.event_type == "anchor_registered"
        assert anchors_for(registry) == 1

    def test_3_continuing_to_point_does_not_spam(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry, clock: FakeClock
    ) -> None:
        point(bridge, FORWARD)
        clock.advance(2.0)
        point(bridge, FORWARD)  # anchors

        for _ in range(30):
            clock.advance(0.1)
            point(bridge, FORWARD)

        assert anchors_for(registry) == 1

    def test_4_hand_jitter_around_one_target_is_still_one_anchor(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry, clock: FakeClock
    ) -> None:
        jitter = [
            [0.01, 0.0, -1.0],
            [-0.01, 0.01, -1.0],
            [0.0, -0.01, -1.0],
        ]
        point(bridge, FORWARD)
        for v in jitter:
            clock.advance(0.5)
            point(bridge, v)
        clock.advance(2.0)
        point(bridge, FORWARD)

        assert anchors_for(registry) == 1

    def test_6_a_genuinely_different_direction_anchors_separately(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry, clock: FakeClock
    ) -> None:
        point(bridge, FORWARD)
        clock.advance(2.0)
        point(bridge, FORWARD)

        point(bridge, LEFT)
        clock.advance(2.0)
        point(bridge, LEFT)

        assert anchors_for(registry) == 2

    def test_5_the_same_target_anchors_again_after_the_cooldown(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry, clock: FakeClock
    ) -> None:
        point(bridge, FORWARD)
        clock.advance(2.0)
        point(bridge, FORWARD)
        assert anchors_for(registry) == 1

        # The hand leaves, and comes back much later.
        bridge.on_gesture_event("none", "NONE", None, "s1", "u1")
        clock.advance(600.0)
        point(bridge, FORWARD)
        clock.advance(2.0)
        point(bridge, FORWARD)

        assert anchors_for(registry) == 2

    def test_dropping_the_gesture_restarts_the_dwell(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry, clock: FakeClock
    ) -> None:
        point(bridge, FORWARD)
        clock.advance(1.0)
        bridge.on_gesture_event("none", "NONE", None, "s1", "u1")  # tracking lost
        clock.advance(1.0)
        point(bridge, FORWARD)  # dwell starts over

        assert anchors_for(registry) == 0


class TestIsolationAndSafety:
    def test_7_two_owners_do_not_share_dwell_state(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry, clock: FakeClock
    ) -> None:
        point(bridge, FORWARD, owner="u1")
        clock.advance(2.0)
        point(bridge, FORWARD, owner="u2")  # u2's first sighting, not u1's dwell

        assert anchors_for(registry, "u1") == 0
        assert anchors_for(registry, "u2") == 0

        clock.advance(2.0)
        point(bridge, FORWARD, owner="u2")
        assert anchors_for(registry, "u2") == 1
        assert anchors_for(registry, "u1") == 0

    def test_9_malformed_vectors_are_ignored(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry, clock: FakeClock
    ) -> None:
        for bad in ([float("nan"), 0.0, -1.0], [float("inf"), 0.0, 0.0], [0.0, 0.0]):
            bridge.on_gesture_event("point", "NONE", bad, "s1", "u1")
            clock.advance(2.0)
            bridge.on_gesture_event("point", "NONE", bad, "s1", "u1")

        assert anchors_for(registry) == 0

    def test_10_candidate_state_does_not_grow_without_bound(
        self, bridge: GestureAnchorBridge, clock: FakeClock
    ) -> None:
        for i in range(200):
            clock.advance(5.0)
            bridge.on_gesture_event("point", "NONE", FORWARD, "s1", f"owner{i}")

        # Owners who stopped pointing long ago are forgotten.
        assert bridge.tracked_owner_count() <= 32

    def test_8_clearing_a_session_resets_its_candidate(
        self, bridge: GestureAnchorBridge, registry: AnchorRegistry, clock: FakeClock
    ) -> None:
        point(bridge, FORWARD)
        clock.advance(1.5)
        bridge.forget_owner("u1")  # camera torn down
        point(bridge, FORWARD)

        assert anchors_for(registry) == 0


class TestConcurrentAccess:
    """The bridge is one app-scoped object and cognition runs its handlers on a
    threadpool, so two overlapping turns for one owner touch the same tracking
    record in parallel. Found by the final security and code reviews.
    """

    def test_overlapping_turns_do_not_duplicate_an_anchor(
        self, registry: AnchorRegistry, clock: FakeClock
    ) -> None:
        import threading

        bridge = GestureAnchorBridge(registry, clock=clock)
        point(bridge, FORWARD)          # start the dwell
        clock.advance(2.0)              # dwell satisfied for both racers

        barrier = threading.Barrier(8)

        def racer() -> None:
            barrier.wait()
            point(bridge, FORWARD)

        threads = [threading.Thread(target=racer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Eight simultaneous turns, one intentional point, one anchor.
        assert anchors_for(registry) == 1

    def test_the_sweep_does_not_race_a_concurrent_delete(
        self, registry: AnchorRegistry, clock: FakeClock
    ) -> None:
        import threading

        bridge = GestureAnchorBridge(registry, clock=clock)
        errors: list[BaseException] = []

        def churn(start: int) -> None:
            try:
                for i in range(start, start + 40):
                    bridge.on_gesture_event("point", "NONE", FORWARD, "s1", f"o{i}")
                    bridge.forget_owner(f"o{i}")
            except BaseException as exc:  # noqa: BLE001 - recorded, then asserted
                errors.append(exc)

        threads = [threading.Thread(target=churn, args=(n * 40,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"concurrent sweep raised: {errors}"
