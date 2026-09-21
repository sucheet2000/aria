"""M1 - the stored publication channel, end to end.

Cardinality is only half the defect. The other half is that the gesture field
of a cognition request became *stored state* that a different reader could
retrieve: an authenticated application caller wrote arbitrary text, the metrics
collector kept it forever, and GET /metrics published it. This drives the real
bridge rather than poking the collector, so the whole path is exercised.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.observability.metrics import MetricsCollector
from app.spatial.anchor_registry import AnchorRegistry
from app.spatial.gesture_anchor_bridge import GestureAnchorBridge

SENTINEL = "<script>aria-metrics-publication-sentinel</script>"


@pytest.fixture(autouse=True)
def _reset() -> None:
    MetricsCollector()._gesture_events.clear()


@pytest.fixture
def bridge(tmp_path: Path) -> GestureAnchorBridge:
    return GestureAnchorBridge(AnchorRegistry(db_path=tmp_path / "anchors.db"))


class TestStoredPublicationChannel:
    def test_attacker_text_via_single_hand_gesture_is_never_published(
        self, bridge: GestureAnchorBridge
    ) -> None:
        bridge.on_gesture_event(SENTINEL, "NONE", None, "s1", "attacker")

        published = json.dumps(MetricsCollector().snapshot())
        assert SENTINEL not in published
        assert "script" not in published

    def test_attacker_text_via_two_hand_gesture_is_never_published(
        self, bridge: GestureAnchorBridge
    ) -> None:
        bridge.on_gesture_event("none", SENTINEL, None, "s1", "attacker")

        published = json.dumps(MetricsCollector().snapshot())
        assert SENTINEL not in published

    def test_a_second_reader_cannot_retrieve_what_the_first_caller_wrote(
        self, bridge: GestureAnchorBridge
    ) -> None:
        """The cross-caller shape: one owner writes, another reads /metrics."""
        for payload in [SENTINEL, "victim@example.com", "https://exfil.test/a?b=c"]:
            bridge.on_gesture_event(payload, "NONE", None, "s1", "attacker")

        published = json.dumps(MetricsCollector().snapshot())
        for payload in [SENTINEL, "victim@example.com", "exfil.test"]:
            assert payload not in published, f"{payload!r} was published to every reader"

    def test_the_gesture_still_counts_so_the_signal_is_not_lost(
        self, bridge: GestureAnchorBridge
    ) -> None:
        bridge.on_gesture_event(SENTINEL, "NONE", None, "s1", "attacker")
        bridge.on_gesture_event("point", "NONE", [0.0, 0.0, -1.0], "s1", "real-user")

        events = MetricsCollector().snapshot()["gesture_events"]
        assert events.get("unknown") == 1, "the anomaly must still be observable"
        assert events.get("point") == 1, "a real gesture must still count by name"
