"""R2 — vision confidence contract.

The browser's heuristic facial-affect confidence must reach the conflict
detector and the prompt unchanged, and the conflict policy must act on the
real value: high confidence + contradictory speech → conflict instruction;
low / zero / missing confidence → conservative (no conflict).
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from fastapi.testclient import TestClient
from pydantic import ValidationError
from structlog.testing import capture_logs

from app.cognition.conflict import (
    CONFLICT_MIN_VISUAL_CONFIDENCE,
    detect_conflict,
    visual_sentiment,
)
from app.cognition.llm import LLMClient
from app.cognition.prompt import (
    CONFLICT_INSTRUCTION,
    NO_CONFLICT_INSTRUCTION,
    build_system_parts,
)
from app.models.schemas import CognitionResponse, PerceptionFrame

POSITIVE_SPEECH = "I'm doing great, everything is good"
NEUTRAL_SPEECH = "let's look at the code together"
DISTINCTIVE = 0.731
PRIVATE_TRANSCRIPT = "PRIVATE_R2_TRANSCRIPT_5521"


@contextmanager
def capture_all_levels() -> Iterator[list[dict]]:
    structlog.configure(wrapper_class=structlog.BoundLogger)
    with capture_logs() as logs:
        structlog.get_logger().debug("capture_all_levels_probe")
        assert logs and logs[-1]["event"] == "capture_all_levels_probe"
        logs.pop()
        yield logs


# ── Test 5: schema validates the range ───────────────────────────────────────


@pytest.mark.parametrize("value", [-0.1, 1.1, -1.0, 2.0])
def test_schema_rejects_out_of_range_confidence(value: float) -> None:
    with pytest.raises(ValidationError):
        PerceptionFrame(emotion="happy", emotion_confidence=value)


@pytest.mark.parametrize("value", [0, 1, 0.5, DISTINCTIVE])
def test_schema_accepts_in_range_confidence(value: float) -> None:
    assert PerceptionFrame(emotion="happy", emotion_confidence=value).emotion_confidence == value


def test_schema_missing_confidence_is_none_not_a_number() -> None:
    frame = PerceptionFrame(emotion="happy")
    assert frame.emotion_confidence is None


def test_schema_has_one_canonical_confidence_field() -> None:
    assert "emotion_confidence" in PerceptionFrame.model_fields
    assert "confidence" not in PerceptionFrame.model_fields


# ── Tests 6–9: the conflict policy on real confidence ────────────────────────


def test_high_confidence_mismatch_is_a_conflict() -> None:  # Test 6
    conflict, delta = detect_conflict(POSITIVE_SPEECH, "sad", 0.82)
    assert conflict is True
    assert delta >= 0.4


def test_low_confidence_mismatch_is_suppressed() -> None:  # Test 7
    conflict, _ = detect_conflict(POSITIVE_SPEECH, "sad", 0.12)
    assert conflict is False


def test_missing_confidence_is_conservative() -> None:  # Test 8
    conflict, _ = detect_conflict(POSITIVE_SPEECH, "sad", None)
    assert conflict is False
    assert visual_sentiment("sad", None) == 0.0


def test_missing_confidence_gate_does_not_rely_on_visual_sentiment(monkeypatch) -> None:
    # The ``confidence is None`` gate must hold on its own, even if
    # visual_sentiment were changed to return a signal for None.
    from app.cognition import conflict as conflict_mod

    monkeypatch.setattr(conflict_mod, "visual_sentiment", lambda emotion, confidence: -0.9)
    assert conflict_mod.detect_conflict(POSITIVE_SPEECH, "sad", None)[0] is False


def test_zero_confidence_is_conservative() -> None:
    assert detect_conflict(POSITIVE_SPEECH, "sad", 0.0)[0] is False


def test_conflict_threshold_boundary_is_inclusive() -> None:  # Test 9
    assert CONFLICT_MIN_VISUAL_CONFIDENCE == 0.6
    assert detect_conflict(POSITIVE_SPEECH, "sad", 0.6)[0] is True  # >= : boundary fires
    assert detect_conflict(POSITIVE_SPEECH, "sad", 0.599)[0] is False
    assert detect_conflict(POSITIVE_SPEECH, "sad", 0.601)[0] is True


def test_conflict_needs_a_speech_signal() -> None:
    # A confident sad face with sentiment-free speech is not a *mismatch*.
    assert detect_conflict(NEUTRAL_SPEECH, "sad", 0.9)[0] is False


def test_conflict_needs_a_polar_visual_signal() -> None:
    # Neutral / unknown expression carries no sentiment to disagree with.
    assert detect_conflict(POSITIVE_SPEECH, "neutral", 0.95)[0] is False
    assert detect_conflict(POSITIVE_SPEECH, "confused", 0.95)[0] is False


def test_conflict_needs_opposite_polarity() -> None:
    assert detect_conflict(POSITIVE_SPEECH, "happy", 0.9)[0] is False
    assert detect_conflict("I am sad and stressed", "sad", 0.9)[0] is False


def test_conflict_no_longer_fires_on_speech_alone() -> None:
    # The pre-R2 symptom: confidence never arrived (0.0), visual sentiment was
    # always 0, and any sentiment word produced a "conflict".
    for confidence in (0.0, None):
        assert detect_conflict("I am fine", "fearful", confidence)[0] is False


# ── Prompt: the real value reaches the observation, wording stays modest ─────


def _observation(frame: PerceptionFrame, transcript: str) -> str:
    _, observation = build_system_parts(frame, transcript, [], [])
    return observation


def test_prompt_carries_the_exact_confidence() -> None:
    obs = _observation(PerceptionFrame(emotion="happy", emotion_confidence=DISTINCTIVE, face_detected=True), "hi")
    assert "happy" in obs
    assert "0.731" in obs
    assert "73.1" not in obs  # no lossy percentage rendering


def test_prompt_marks_missing_confidence_unavailable() -> None:
    obs = _observation(PerceptionFrame(emotion="happy"), "hi")
    assert "unavailable" in obs
    assert "1.0" not in obs.split("Head pose")[0]


def test_prompt_does_not_assert_emotion_as_fact() -> None:
    obs = _observation(PerceptionFrame(emotion="sad", emotion_confidence=0.62, face_detected=True), "hi")
    assert "Estimated facial affect" in obs
    assert "heuristic" in obs
    assert "Expressive state" not in obs
    assert "Face visible: yes" in obs


def test_prompt_no_conflict_when_face_not_visible() -> None:
    # Code review P2: a confident label with face_detected=False (replayed or
    # hand-rolled body) carries no usable visual signal.
    no_face = PerceptionFrame(emotion="sad", emotion_confidence=0.9, face_detected=False)
    obs = _observation(no_face, POSITIVE_SPEECH)
    assert "Face visible: no" in obs
    assert NO_CONFLICT_INSTRUCTION in obs
    assert CONFLICT_INSTRUCTION not in obs


def test_prompt_renders_negative_zero_as_zero() -> None:
    # Security P3: -0.0 passes ge=0 and must not render as "-0.000".
    obs = _observation(PerceptionFrame(emotion="neutral", emotion_confidence=-0.0, face_detected=True), "hi")
    assert "confidence 0.000" in obs
    assert "-0.000" not in obs


def test_prompt_conflict_instruction_only_with_confident_mismatch() -> None:
    confident = PerceptionFrame(emotion="sad", emotion_confidence=0.82, face_detected=True)
    weak = PerceptionFrame(emotion="sad", emotion_confidence=0.12, face_detected=True)
    missing = PerceptionFrame(emotion="sad", face_detected=True)
    assert CONFLICT_INSTRUCTION in _observation(confident, POSITIVE_SPEECH)
    assert NO_CONFLICT_INSTRUCTION in _observation(weak, POSITIVE_SPEECH)
    assert NO_CONFLICT_INSTRUCTION in _observation(missing, POSITIVE_SPEECH)


# ── Test 10 / 11: route end-to-end with the Go-shaped body ───────────────────


def _mount(app, llm, tmp_path) -> None:
    from app.api.cognition_route import get_bridge, get_client, get_memory
    from app.spatial.anchor_registry import AnchorRegistry
    from app.spatial.gesture_anchor_bridge import GestureAnchorBridge

    memory = MagicMock()
    memory.loaded = True
    memory.store_triple = AsyncMock(return_value=True)
    memory.query_relevant = AsyncMock(return_value=[])
    memory.deletion_generation = MagicMock(return_value=0)
    app.dependency_overrides[get_client] = lambda: llm
    app.dependency_overrides[get_memory] = lambda: memory
    app.dependency_overrides[get_bridge] = lambda: GestureAnchorBridge(
        AnchorRegistry(db_path=tmp_path / "a.db")
    )


def _fake_llm_response(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "end_turn"
    response.usage = MagicMock(
        input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )
    return response


# Exactly what the Go edge emits for a browser turn (see
# internal/cognition/vision_confidence_test.go): the browser's fields plus
# Go's working_memory, owner in the header only.
def _go_shaped_body(transcript: str, emotion: str, confidence: float | None) -> dict:
    vision: dict = {
        "emotion": emotion,
        "pitch": 1.0,
        "yaw": 2.0,
        "roll": 3.0,
        "face_detected": True,
        "hands_detected": False,
    }
    if confidence is not None:
        vision["emotion_confidence"] = confidence
    return {
        "message": transcript,
        "vision_state": vision,
        "conversation_history": [],
        "session_id": "s1",
        "gesture": "none",
        "two_hand_gesture": "NONE",
        "pointing_vector": None,
        "working_memory": [],
    }


def test_route_end_to_end_confidence_reaches_prompt(tmp_path) -> None:  # Test 10
    from app.main import app

    client = LLMClient(api_key="test-key")
    create = AsyncMock(
        return_value=_fake_llm_response(
            '{"symbolic_inference": "calm", "natural_language_response": "ok"}'
        )
    )
    client._client.messages.create = create
    _mount(app, client, tmp_path)
    try:
        r = TestClient(app).post(
            "/api/cognition",
            json=_go_shaped_body(POSITIVE_SPEECH, "sad", DISTINCTIVE),
            headers={"X-Aria-Owner": "o"},
        )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    observation = create.call_args.kwargs["system"][1]["text"]
    assert "0.731" in observation
    assert "sad" in observation
    assert CONFLICT_INSTRUCTION in observation  # 0.731 >= 0.6 with contradictory speech


def test_route_rejects_out_of_range_confidence(tmp_path) -> None:
    from app.main import app

    llm = MagicMock()
    llm.complete = AsyncMock(
        return_value=CognitionResponse(symbolic_inference="", natural_language_response="ok")
    )
    _mount(app, llm, tmp_path)
    try:
        c = TestClient(app)
        assert c.post("/api/cognition", json=_go_shaped_body("hi", "happy", 1.1)).status_code == 422
        assert c.post("/api/cognition", json=_go_shaped_body("hi", "happy", -0.1)).status_code == 422
        for ok in (0, 1, 0.5):
            assert c.post("/api/cognition", json=_go_shaped_body("hi", "happy", ok)).status_code == 200
        r = c.post("/api/cognition", json=_go_shaped_body("hi", "happy", 0.5))
        assert r.status_code == 200
        assert llm.complete.call_args.kwargs["vision"].emotion_confidence == 0.5
    finally:
        app.dependency_overrides.clear()


def test_route_missing_confidence_arrives_as_none(tmp_path) -> None:
    from app.main import app

    llm = MagicMock()
    llm.complete = AsyncMock(
        return_value=CognitionResponse(symbolic_inference="", natural_language_response="ok")
    )
    _mount(app, llm, tmp_path)
    try:
        r = TestClient(app).post("/api/cognition", json=_go_shaped_body("hi", "happy", None))
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    vision = llm.complete.call_args.kwargs["vision"]
    assert vision.emotion == "happy"
    assert vision.emotion_confidence is None


def test_vision_turn_logs_no_transcript_or_prompt(tmp_path) -> None:  # Test 11
    from app.main import app

    client = LLMClient(api_key="test-key")
    client._client.messages.create = AsyncMock(
        return_value=_fake_llm_response(
            '{"symbolic_inference": "calm", "natural_language_response": "ok"}'
        )
    )
    _mount(app, client, tmp_path)
    try:
        with capture_all_levels() as logs:
            r = TestClient(app).post(
                "/api/cognition",
                json=_go_shaped_body(f"{PRIVATE_TRANSCRIPT} I am fine", "sad", 0.82),
            )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    rendered = "\n".join(repr(e) for e in logs)
    assert PRIVATE_TRANSCRIPT not in rendered
    assert "Estimated facial affect" not in rendered  # the prompt is never logged
    assert "Current observation" not in rendered
