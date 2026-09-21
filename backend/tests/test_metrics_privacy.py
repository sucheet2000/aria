"""M1 Phase 8 - nothing a caller says may reach the metrics document.

/metrics is a document one party writes and another reads. The collector's own
discipline is good - latency histograms, model constants, fixed status literals
- but discipline is a property of today's call sites, not of the endpoint. This
drives the real cognition route with sentinels in every field a caller controls
and asserts none of them survive into the published snapshot.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.observability.metrics import MetricsCollector

# Each sentinel stands for a class of content the metrics must never carry.
SENTINELS = {
    "user message": "SENT-MSG-a1b2c3-the-user-said-something-private",
    "working memory": "SENT-MEM-d4e5f6-recalled-fact-about-the-user",
    "history content": "SENT-HIST-g7h8i9-an-earlier-turn",
    "gesture": "SENT-GEST-j1k2l3",
    "session id": "SENT-SESSION-m4n5o6",
    "email-shaped": "sentinel.person@example.invalid",
    "url-shaped": "https://sentinel.invalid/secret?token=abc",
    "token-shaped": "sk-ant-SENTINELtokenvalue0000000000",
}


@pytest.fixture(autouse=True)
def _reset() -> None:
    m = MetricsCollector()
    m._gesture_events.clear()
    m._cognition_timeout.clear()


def _drive_one_turn() -> None:
    from app.api.cognition_route import get_bridge, get_client, get_memory
    from app.main import app
    from tests.test_cognition import _stub_llm_client, _stub_memory, _tmp_bridge

    with tempfile.TemporaryDirectory() as tmp:
        app.dependency_overrides[get_client] = lambda: _stub_llm_client()
        app.dependency_overrides[get_memory] = lambda: _stub_memory()
        app.dependency_overrides[get_bridge] = lambda: _tmp_bridge(Path(tmp))
        try:
            resp = TestClient(app).post(
                "/api/cognition",
                json={
                    "message": SENTINELS["user message"] + " " + SENTINELS["email-shaped"],
                    "working_memory": [SENTINELS["working memory"], SENTINELS["url-shaped"]],
                    "conversation_history": [
                        {"role": "user", "content": SENTINELS["history content"]},
                        {"role": "assistant", "content": SENTINELS["token-shaped"]},
                    ],
                    "gesture": SENTINELS["gesture"],
                    "session_id": SENTINELS["session id"],
                    "vision_state": {"emotion": "happy", "emotion_confidence": 0.8},
                },
                headers={"X-Request-ID": SENTINELS["session id"] + "-reqid"},
            )
            assert resp.status_code == 200, resp.text
        finally:
            app.dependency_overrides.clear()


class TestMetricsCarryNoCallerContent:
    def test_1_no_sentinel_survives_a_real_cognition_turn(self) -> None:
        _drive_one_turn()

        published = json.dumps(MetricsCollector().snapshot())
        leaked = {name: v for name, v in SENTINELS.items() if v in published}
        assert not leaked, f"metrics published caller content: {sorted(leaked)}"

    def test_2_the_turn_was_actually_observed(self) -> None:
        """Guards against the test passing because nothing was recorded."""
        _drive_one_turn()

        snap = MetricsCollector().snapshot()
        assert snap["cognition_latency_ms"]["count"] >= 1, "no latency recorded; test proves nothing"
        assert snap["gesture_events"], "no gesture recorded; test proves nothing"

    def test_3_an_unknown_gesture_is_counted_but_not_named(self) -> None:
        _drive_one_turn()

        events = MetricsCollector().snapshot()["gesture_events"]
        assert events == {"unknown": 1}, f"gesture key set = {events}"

    def test_4_every_published_key_is_server_chosen(self) -> None:
        """The structural invariant: no map in the document may be keyed by
        anything a caller supplied."""
        _drive_one_turn()
        snap = MetricsCollector().snapshot()

        from app.observability.metrics import (
            GESTURE_EVENT_UNKNOWN,
            KNOWN_GESTURE_EVENTS,
        )

        allowed = {
            "gesture_events": set(KNOWN_GESTURE_EVENTS) | {GESTURE_EVENT_UNKNOWN},
            "cognition_timeout": {"cancelled", "python_total_timeout"},
        }
        for field, permitted in allowed.items():
            stray = set(snap[field]) - permitted
            assert not stray, f"{field} carries caller-chosen keys: {sorted(stray)}"

        # token_cost / prompt_cache / llm_response are keyed by model constants.
        for field in ("token_cost", "prompt_cache", "llm_response"):
            for key in snap[field]:
                assert key.startswith("claude-"), f"{field} key {key!r} is not a model constant"
