"""M1 - a client string must not become a permanent metric dimension.

``record_gesture_event`` keyed its dict on whatever arrived in the request's
``gesture`` / ``two_hand_gesture`` field. Nothing validated those fields
anywhere between the socket and the metric: they are bare ``str`` on the
pydantic model, forwarded verbatim by the Go edge, and the bridge records the
metric as its first act - before any branch that would discard an unrecognised
value.

Two consequences. The dict grows without bound and is never evicted, so it is a
memory-growth path. And because ``/metrics`` publishes it, a caller who can
reach ``POST /api/cognition`` can write text of their choosing into a document
other people read - a stored publication channel, not merely a counter bug.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from app.observability.metrics import (
    GESTURE_EVENT_UNKNOWN,
    KNOWN_GESTURE_EVENTS,
    MetricsCollector,
)

_FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"

_RTL_OVERRIDE = chr(0x202E)
_NUL = chr(0)


@pytest.fixture(autouse=True)
def _reset() -> None:
    MetricsCollector()._gesture_events.clear()


class TestCardinalityIsBounded:
    def test_1_a_thousand_hostile_strings_do_not_create_a_thousand_keys(self) -> None:
        m = MetricsCollector()
        for i in range(1000):
            m.record_gesture_event(f"gesture_{i:06d}")

        keys = set(m.snapshot()["gesture_events"])
        assert keys <= {GESTURE_EVENT_UNKNOWN}, f"unbounded keys leaked in: {sorted(keys)[:5]}"
        assert m.snapshot()["gesture_events"][GESTURE_EVENT_UNKNOWN] == 1000

    def test_2_the_dimension_set_can_never_exceed_the_vocabulary(self) -> None:
        m = MetricsCollector()
        for i in range(5000):
            m.record_gesture_event(f"{_RTL_OVERRIDE}{i}<script>x</script>")
        for name in KNOWN_GESTURE_EVENTS:
            m.record_gesture_event(name)

        keys = set(m.snapshot()["gesture_events"])
        ceiling = set(KNOWN_GESTURE_EVENTS) | {GESTURE_EVENT_UNKNOWN}
        assert keys <= ceiling, f"keys outside the vocabulary: {sorted(keys - ceiling)[:5]}"
        assert len(keys) <= len(ceiling)

    def test_3_hostile_text_never_reaches_the_metrics_output(self) -> None:
        sentinel = "CARDINALITY-SENTINEL-user@example.com-https://evil.test"
        MetricsCollector().record_gesture_event(sentinel)

        rendered = repr(MetricsCollector().snapshot())
        assert sentinel not in rendered
        assert "evil.test" not in rendered

    @pytest.mark.parametrize(
        "value", ["", "   ", "\n", "None", "point ", " point", "POINT", "pOiNt", _NUL]
    )
    def test_4_malformed_values_are_safe_and_bounded(self, value: str) -> None:
        MetricsCollector().record_gesture_event(value)
        keys = set(MetricsCollector().snapshot()["gesture_events"])
        assert keys <= set(KNOWN_GESTURE_EVENTS) | {GESTURE_EVENT_UNKNOWN}

    def test_5_a_non_string_cannot_become_a_key(self) -> None:
        for value in [None, 123, 4.5, ["point"], {"a": 1}]:
            MetricsCollector().record_gesture_event(value)  # type: ignore[arg-type]
        keys = set(MetricsCollector().snapshot()["gesture_events"])
        assert keys <= {GESTURE_EVENT_UNKNOWN}


class TestKnownGesturesStillCounted:
    @pytest.mark.parametrize("name", sorted(KNOWN_GESTURE_EVENTS))
    def test_6_every_canonical_gesture_is_counted_under_its_own_name(self, name: str) -> None:
        MetricsCollector().record_gesture_event(name)
        assert MetricsCollector().snapshot()["gesture_events"] == {name: 1}

    def test_7_counts_still_accumulate(self) -> None:
        m = MetricsCollector()
        for _ in range(3):
            m.record_gesture_event("point")
        m.record_gesture_event("stop")
        assert m.snapshot()["gesture_events"] == {"point": 3, "stop": 1}


class TestVocabularyMatchesItsProducers:
    """The allowlist restates contracts owned elsewhere, so it is checked
    against them rather than trusted - the pattern already used for the
    perception emotion vocabulary."""

    def test_8_single_hand_names_match_the_browser_classifier(self) -> None:
        producer = _FRONTEND / "lib" / "perception" / "gesture.ts"
        assert producer.exists(), f"the gesture producer moved: {producer}"
        # [^"]+ , not [a-z]+ : the narrower class silently parsed a PARTIAL
        # set, and the `assert emitted` guard below could not tell, because a
        # partial set is still non-empty.
        emitted = set(re.findall(r'\]:\s*"([^"]+)"', producer.read_text()))
        assert emitted, "no wire names parsed from GESTURE_NAMES; re-aim this test"

        missing = emitted - set(KNOWN_GESTURE_EVENTS)
        assert not missing, (
            f"the browser can emit {sorted(missing)}, which the metric would "
            "bucket as unknown"
        )

    def test_9_two_hand_names_match_the_protobuf_contract(self) -> None:
        # Same path insertion the sibling proto test uses.
        sys.path.insert(0, str(Path(__file__).parent.parent / "gen" / "python"))
        from perception.v1 import perception_pb2

        enum = perception_pb2.DESCRIPTOR.enum_types_by_name["TwoHandGestureType"]
        emitted = {
            v.name.removeprefix("TWO_HAND_GESTURE_TYPE_")
            for v in enum.values
            if v.name != "TWO_HAND_GESTURE_TYPE_UNSPECIFIED"
        }

        missing = emitted - set(KNOWN_GESTURE_EVENTS)
        assert not missing, (
            f"the proto defines {sorted(missing)}, which the metric would "
            "bucket as unknown"
        )

    def test_10_the_allowlist_invents_nothing_of_its_own(self) -> None:
        """The other direction. Checking only producer-minus-allowlist let a
        name be added here that no producer can emit - half a contract check
        presented as a whole one."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "gen" / "python"))
        from perception.v1 import perception_pb2

        single = set(
            re.findall(
                r'\]:\s*"([^"]+)"',
                (_FRONTEND / "lib" / "perception" / "gesture.ts").read_text(),
            )
        )
        enum = perception_pb2.DESCRIPTOR.enum_types_by_name["TwoHandGestureType"]
        two_hand = {
            v.name.removeprefix("TWO_HAND_GESTURE_TYPE_")
            for v in enum.values
            if v.name != "TWO_HAND_GESTURE_TYPE_UNSPECIFIED"
        }

        invented = set(KNOWN_GESTURE_EVENTS) - (single | two_hand)
        assert not invented, (
            f"the allowlist carries {sorted(invented)}, which no producer emits"
        )
