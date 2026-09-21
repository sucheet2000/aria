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

import linecache
import pathlib
import sys
import threading
from pathlib import Path

import pytest

from app.spatial import gesture_anchor_bridge
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


# ── Closure 4 ────────────────────────────────────────────────────────────────
# The eight-thread test above passes whether or not the lock is there, so it is
# not evidence of anything. Two earlier attempts at a real detector failed for
# the same reason and are worth recording: synchronizing the threads as they
# ENTER the decision does not interleave them, because the section is a handful
# of bytecodes with no I/O, so whichever thread the GIL hands over to runs it to
# completion before the other resumes.
#
# What a duplicate anchor actually requires is both turns reading the owner's
# record and only then writing it back. So the rendezvous is placed at that
# exact point: the line that records the anchor. A thread arriving there has
# already read the record and passed every check, and has not yet written
# anything. Hold two threads there and the duplicate is certain; a lock that
# works means the second thread never arrives, because it is still waiting
# outside for the first to finish.
#
# This lives entirely in the test. Production has no sleep, no hook, no
# test-only switch, and no knowledge that any of this exists — the interleave
# is imposed from outside with sys.settrace, which is what it is for.
_ANCHOR_WRITE_LINE = "track.anchored = vec"
_INTERLEAVE_TIMEOUT = 0.5


class _HoldAtLine:
    """Holds every thread that reaches one source line until two have."""

    def __init__(self, func_name: str, line_text: str) -> None:
        self._func = func_name
        self._text = line_text
        self._gate = threading.Barrier(2, timeout=_INTERLEAVE_TIMEOUT)
        self.arrivals = 0
        self._mu = threading.Lock()

    def _line(self, frame, event, arg):  # noqa: ANN001 - tracer signature
        if event == "line":
            src = linecache.getline(frame.f_code.co_filename, frame.f_lineno).strip()
            if src.startswith(self._text):
                with self._mu:
                    self.arrivals += 1
                try:
                    self._gate.wait()
                except threading.BrokenBarrierError:
                    # Nobody else arrived: the lock kept them out.
                    pass
        return self._line

    def __call__(self, frame, event, arg):  # noqa: ANN001 - tracer signature
        if event == "call" and frame.f_code.co_name == self._func:
            return self._line
        return None


class TestAnchorDecisionIsSerialized:
    """Two turns forced to overlap inside the decision, not left to chance."""

    def test_two_turns_interleaved_at_the_write_still_anchor_once(
        self, registry: AnchorRegistry
    ) -> None:
        # The line the rendezvous targets must exist, or this test proves
        # nothing while looking like it passed.
        source = pathlib.Path(gesture_anchor_bridge.__file__).read_text()
        assert _ANCHOR_WRITE_LINE in source, (
            f"{_ANCHOR_WRITE_LINE!r} is gone from the bridge; this detector is "
            "pointing at nothing and must be re-aimed"
        )

        clock = FakeClock()
        bridge = GestureAnchorBridge(registry, clock=clock)
        point(bridge, FORWARD)  # start the dwell
        clock.advance(2.0)      # dwell satisfied for both turns

        hold = _HoldAtLine("_should_anchor_locked", _ANCHOR_WRITE_LINE)
        errors: list[BaseException] = []

        def turn() -> None:
            sys.settrace(hold)
            try:
                point(bridge, FORWARD)
            except BaseException as exc:  # noqa: BLE001 - recorded, then asserted
                errors.append(exc)
            finally:
                sys.settrace(None)

        threads = [threading.Thread(target=turn) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)

        assert errors == [], f"concurrent decision raised: {errors}"
        assert all(not t.is_alive() for t in threads), "a turn never finished"
        # One intentional point. Two anchors means both turns decided to record
        # one from the same reading of the owner's record.
        assert anchors_for(registry) == 1
        # And the detector has to have been live: exactly one turn may reach the
        # write, because the other should still be waiting for the lock when the
        # first one finishes and puts the target on cooldown.
        assert hold.arrivals == 1, (
            f"{hold.arrivals} turns reached the anchor write; 1 is the serialized "
            "outcome and 2 is the duplicate this lock prevents"
        )
