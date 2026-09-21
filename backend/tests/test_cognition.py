from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

import app.cognition.prompt as prompt_module
from app.cognition.conflict import detect_conflict, speech_sentiment, visual_sentiment
from app.cognition.prompt import (
    CONFLICT_INSTRUCTION,
    NO_CONFLICT_INSTRUCTION,
    _load_soul,
    build_system_prompt,
)
from app.models.schemas import (
    CognitionRequest,
    CognitionResponse,
    PerceptionFrame,
    WorldModelTriple,
    WorldModelUpdate,
)

# --- speech_sentiment ---

def test_speech_sentiment_positive():
    score = speech_sentiment("I am happy and everything is great")
    assert score > 0.0


def test_speech_sentiment_negative():
    score = speech_sentiment("I am frustrated and stuck")
    assert score < 0.0


def test_speech_sentiment_neutral():
    score = speech_sentiment("hello there")
    assert score == 0.0


# --- visual_sentiment ---

def test_visual_sentiment_positive():
    assert visual_sentiment("happy", 0.9) == 0.9


def test_visual_sentiment_negative():
    assert visual_sentiment("fearful", 0.8) == -0.8


def test_visual_sentiment_neutral():
    assert visual_sentiment("neutral", 1.0) == 0.0


# --- detect_conflict ---

def test_detect_conflict_positive_speech_negative_visual():
    conflict, delta = detect_conflict("I am fine", "fearful", 0.8)
    assert conflict is True
    assert delta >= 0.4


def test_detect_conflict_aligned_negative():
    conflict, delta = detect_conflict("I am frustrated", "angry", 0.7)
    assert conflict is False


# --- build_system_prompt ---

def test_build_system_prompt_contains_aria():
    vision = PerceptionFrame(emotion="neutral", emotion_confidence=0.5)
    prompt = build_system_prompt(vision, "hello", [], [])
    assert "ARIA" in prompt


def test_build_system_prompt_contains_emotion():
    vision = PerceptionFrame(emotion="happy", emotion_confidence=0.9)
    prompt = build_system_prompt(vision, "hello", [], [])
    assert "happy" in prompt


def test_build_system_prompt_conflict_instruction_when_conflict():
    vision = PerceptionFrame(emotion="fearful", emotion_confidence=0.8, face_detected=True)
    prompt = build_system_prompt(vision, "I am fine", [], [])
    assert CONFLICT_INSTRUCTION in prompt


def test_build_system_prompt_no_conflict_instruction_when_aligned():
    vision = PerceptionFrame(emotion="angry", emotion_confidence=0.7)
    prompt = build_system_prompt(vision, "I am frustrated", [], [])
    assert NO_CONFLICT_INSTRUCTION in prompt


# --- _load_soul: SOUL_PATH override + repo-root fallback ---


def test_load_soul_reads_from_soul_path_env(tmp_path, monkeypatch):
    soul_file = tmp_path / "SOUL.md"
    soul_file.write_text("I am the test soul identity.")
    monkeypatch.setenv("SOUL_PATH", str(soul_file))
    monkeypatch.setattr(prompt_module, "_soul_cache", None)
    assert _load_soul() == "I am the test soul identity."


def test_load_soul_falls_back_to_repo_root_when_unset(monkeypatch):
    monkeypatch.delenv("SOUL_PATH", raising=False)
    monkeypatch.setattr(prompt_module, "_soul_cache", None)
    assert "ARIA" in _load_soul()


def test_load_soul_returns_empty_when_file_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("SOUL_PATH", str(tmp_path / "missing.md"))
    monkeypatch.setattr(prompt_module, "_soul_cache", None)
    assert _load_soul() == ""


# --- CognitionResponse schema ---

def test_symbolic_response_minimal():
    sr = CognitionResponse(
        symbolic_inference="user is focused",
        natural_language_response="Got it.",
    )
    assert sr.world_model_update is None
    assert sr.symbolic_inference == "user is focused"


def test_symbolic_response_with_world_model_update():
    triple = WorldModelTriple(subject="user", predicate="prefers", object="dark mode")
    wmu = WorldModelUpdate(triple=triple, confidence=0.9, source="explicit_statement")
    sr = CognitionResponse(
        symbolic_inference="user stated a preference",
        world_model_update=wmu,
        natural_language_response="Noted.",
    )
    assert sr.world_model_update is not None
    assert sr.world_model_update.triple.object == "dark mode"


# --- CognitionRequest gesture field contract (API-1) ---


def test_cognition_request_parses_gesture_field_from_json():
    """The inbound JSON key sent by the frontend + Go is `gesture` (API-1).

    Proves a single-hand gesture is received, not silently dropped to "none".
    """
    req = CognitionRequest.model_validate({"message": "look", "gesture": "HOLD"})
    assert req.gesture == "HOLD"


def test_cognition_request_gesture_defaults_to_none():
    req = CognitionRequest.model_validate({"message": "hi"})
    assert req.gesture == "none"


# --- cognition route: DI + gesture + owner scoping ---


def _stub_llm_client() -> MagicMock:
    stub = MagicMock()
    stub.complete = AsyncMock(
        return_value=CognitionResponse(
            symbolic_inference="user is pointing",
            natural_language_response="I see you pointing.",
        )
    )
    return stub


def _stub_memory() -> MagicMock:
    mem = MagicMock()
    mem.loaded = True
    mem.store_triple = AsyncMock()
    mem.query_relevant = AsyncMock(return_value=[])
    return mem


class _TestClock:
    """Monotonic seconds under the test's control."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _tmp_bridge(tmp_path, clock=None):
    from app.spatial.anchor_registry import AnchorRegistry
    from app.spatial.gesture_anchor_bridge import GestureAnchorBridge
    return GestureAnchorBridge(AnchorRegistry(db_path=tmp_path / "a.db"), clock=clock)


def test_cognition_route_point_gesture_produces_spatial_event(tmp_path):
    """A HELD point produces an anchor; a single passing one does not.

    The bridge is one app-scoped instance in production, so the dwell spans
    requests — which is what this override models.
    """
    from app.api.cognition_route import get_bridge, get_client, get_memory
    from app.main import app

    clock = _TestClock()
    bridge = _tmp_bridge(tmp_path, clock=clock)
    app.dependency_overrides[get_client] = lambda: _stub_llm_client()
    app.dependency_overrides[get_memory] = lambda: _stub_memory()
    app.dependency_overrides[get_bridge] = lambda: bridge
    try:
        client = TestClient(app)
        body = {
            "message": "look at that",
            "gesture": "point",
            "pointing_vector": [0.1, -0.2, 0.9],
            "session_id": "test-session-001",
        }

        first = client.post("/api/cognition", json=body)
        assert first.status_code == 200
        # One frame of pointing is not an instruction to place an anchor.
        assert first.json()["spatial_event"] is None

        clock.advance(2.0)
        resp = client.post("/api/cognition", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["spatial_event"] is not None
        assert data["spatial_event"]["event_type"] == "anchor_registered"
    finally:
        app.dependency_overrides.clear()


def test_cognition_route_no_gesture_spatial_event_is_none(tmp_path):
    """Default gesture fields → spatial_event is None."""
    from app.api.cognition_route import get_bridge, get_client, get_memory
    from app.main import app

    app.dependency_overrides[get_client] = lambda: _stub_llm_client()
    app.dependency_overrides[get_memory] = lambda: _stub_memory()
    app.dependency_overrides[get_bridge] = lambda: _tmp_bridge(tmp_path)
    try:
        resp = TestClient(app).post("/api/cognition", json={"message": "hello"})
        assert resp.status_code == 200
        assert resp.json()["spatial_event"] is None
    finally:
        app.dependency_overrides.clear()


def test_anchor_endpoints_scope_by_owner(tmp_path):
    """/api/anchors returns only the current owner's anchors."""
    from app.api.cognition_route import get_current_owner, get_registry
    from app.main import app
    from app.spatial.anchor_registry import AnchorRegistry

    reg = AnchorRegistry(db_path=tmp_path / "a.db")
    reg.register_anchor((0.0, 0.0, -1.0), "obj", owner="alice")
    app.dependency_overrides[get_registry] = lambda: reg
    try:
        client = TestClient(app)
        app.dependency_overrides[get_current_owner] = lambda: "alice"
        assert len(client.get("/api/anchors").json()["anchors"]) == 1
        app.dependency_overrides[get_current_owner] = lambda: "bob"
        assert client.get("/api/anchors").json()["anchors"] == []
    finally:
        app.dependency_overrides.clear()


def test_lifespan_populates_app_state():
    """The lifespan constructs the services once onto app.state."""
    from app.main import app

    with (
        patch("app.main.MemoryStore", return_value=MagicMock()),
        patch("app.main.LLMClient", return_value=MagicMock()),
        patch("app.main.AnchorRegistry", return_value=MagicMock()),
        patch("app.main.GestureAnchorBridge", return_value=MagicMock()),
    ):
        with TestClient(app):
            assert hasattr(app.state, "llm")
            assert hasattr(app.state, "memory")
            assert hasattr(app.state, "registry")
            assert hasattr(app.state, "bridge")
