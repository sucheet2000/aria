"""R5 — malformed / truncated / empty provider output must fail safely.

The Python cognition layer owns exactly one user-safe fallback. Raw provider
text never becomes ``natural_language_response``; a ``max_tokens`` (or still
paused) completion is rejected as truncated even if its text happens to parse;
failed turns write nothing to memory and push nothing into the working ring
(``symbolic_inference == ""``); only counts, types and stop reasons are logged.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

import app.cognition.prompt as prompt_mod
from app.cognition.llm import (
    _MODEL_HAIKU,
    SAFE_FALLBACK_RESPONSE,
    LLMClient,
    LLMResponseEmptyError,
    LLMResponseError,
    LLMResponseParseError,
    LLMResponseRefusedError,
    LLMResponseSchemaError,
    LLMResponseTruncatedError,
)
from app.models.schemas import (
    CognitionResponse,
    PerceptionFrame,
    WorldModelTriple,
    WorldModelUpdate,
)
from app.observability.metrics import MetricsCollector

PRIVATE = "PRIVATE_MALFORMED_OUTPUT_9417"
VALID = (
    '{"symbolic_inference": "user is focused on the bike", '
    '"world_model_update": {"triple": {"subject": "user", "predicate": "owns", "object": "a red bicycle"}, '
    '"confidence": 0.9, "source": "explicit_statement"}, '
    '"natural_language_response": "Nice bike!"}'
)
MALFORMED = '{"symbolic_inference":"x","natural_language_response":'
PROSE = "I think the answer is that you own a bicycle."


@contextmanager
def capture_all_levels() -> Iterator[list[dict]]:
    saved = structlog.get_config()
    structlog.configure(wrapper_class=structlog.BoundLogger)
    try:
        with capture_logs() as logs:
            structlog.get_logger().debug("probe")
            logs.pop()
            yield logs
    finally:
        structlog.configure(**saved)


def _response(text: str | None, *, stop_reason: str | None = "end_turn") -> SimpleNamespace:
    content = [] if text is None else [SimpleNamespace(type="text", text=text)]
    usage = SimpleNamespace(
        input_tokens=100, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage)


def _client(response: SimpleNamespace) -> LLMClient:
    prompt_mod._soul_cache = None
    client = LLMClient(api_key="test-key")
    client._client.messages.create = AsyncMock(return_value=response)
    return client


async def _turn(client: LLMClient, message: str = "hello") -> CognitionResponse:
    return await client.complete(
        message=message, vision=PerceptionFrame(), conversation_history=[],
        working_memory=[], episodic_memory=[],
    )


def _assert_safe_fallback(result: CognitionResponse, status: str) -> None:
    assert result.response_status == status
    assert result.natural_language_response == SAFE_FALLBACK_RESPONSE
    assert result.symbolic_inference == ""          # nothing for the Go ring
    assert result.world_model_update is None        # nothing for memory
    assert "{" not in result.natural_language_response
    for bad in (PRIVATE, MALFORMED, PROSE, "parse error", "empty completion", "state unclear"):
        assert bad not in result.natural_language_response
        assert bad not in result.symbolic_inference


@pytest.fixture(autouse=True)
def _reset_metrics():
    MetricsCollector()._llm_response = {}
    MetricsCollector()._prompt_cache = {}
    yield


# ── Test 1: valid JSON still works ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_json_end_turn_preserved_exactly() -> None:
    result = await _turn(_client(_response(VALID)))
    assert result.response_status == "valid"
    assert result.symbolic_inference == "user is focused on the bike"
    assert result.natural_language_response == "Nice bike!"
    assert result.world_model_update is not None
    assert result.world_model_update.triple.object == "a red bicycle"
    assert result.world_model_update.confidence == 0.9
    assert result.world_model_update.source == "explicit_statement"


@pytest.mark.asyncio
async def test_valid_json_wrapped_in_prose_still_parses() -> None:
    result = await _turn(_client(_response(f"Sure. {VALID} Done.")))
    assert result.response_status == "valid"
    assert result.natural_language_response == "Nice bike!"


# ── Tests 2, 3: malformed / non-JSON never becomes speech ────────────────────


@pytest.mark.asyncio
async def test_malformed_json_never_becomes_speech() -> None:  # Test 2
    result = await _turn(_client(_response(f'{MALFORMED} "{PRIVATE}"')))
    _assert_safe_fallback(result, "malformed")


@pytest.mark.asyncio
async def test_plain_prose_is_not_passed_through() -> None:  # Test 3
    result = await _turn(_client(_response(PROSE)))
    _assert_safe_fallback(result, "malformed")


def test_parser_raises_typed_errors() -> None:
    client = LLMClient(api_key="test-key")
    with pytest.raises(LLMResponseParseError):
        client._parse_response(MALFORMED)
    with pytest.raises(LLMResponseParseError):
        client._parse_response(PROSE)
    with pytest.raises(LLMResponseSchemaError):
        client._parse_response('{"symbolic_inference": "x"}')
    assert issubclass(LLMResponseParseError, LLMResponseError)
    assert issubclass(LLMResponseTruncatedError, LLMResponseError)
    assert issubclass(LLMResponseEmptyError, LLMResponseError)
    assert issubclass(LLMResponseSchemaError, LLMResponseError)
    assert issubclass(LLMResponseRefusedError, LLMResponseError)


# ── Tests 4, 5: max_tokens ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_max_tokens_partial_json_is_truncated() -> None:  # Test 4
    result = await _turn(_client(_response(MALFORMED, stop_reason="max_tokens")))
    _assert_safe_fallback(result, "truncated")


@pytest.mark.asyncio
async def test_max_tokens_with_parseable_json_is_still_truncated() -> None:  # Test 5
    # Policy: the provider says the turn was cut off; whatever parsed is not a
    # completed answer (the JSON may have closed on a truncated string value).
    result = await _turn(_client(_response(VALID, stop_reason="max_tokens")))
    _assert_safe_fallback(result, "truncated")


@pytest.mark.asyncio
async def test_still_paused_after_bounded_continuations_is_truncated() -> None:
    client = _client(_response(VALID, stop_reason="pause_turn"))
    result = await _turn(client)
    _assert_safe_fallback(result, "truncated")


@pytest.mark.asyncio
async def test_provider_refusal_is_its_own_status() -> None:
    # A policy refusal is a provider outcome, not a parser bug: same safe
    # fallback, but counted separately so a refusal spike is legible.
    result = await _turn(_client(_response("I can't help with that.", stop_reason="refusal")))
    _assert_safe_fallback(result, "refused")


# ── Test 6: empty content ────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [None, ""])
async def test_empty_completion_is_typed_and_safe(text: str | None) -> None:
    result = await _turn(_client(_response(text)))
    _assert_safe_fallback(result, "empty")


# ── Tests 7, 8, 9: schema ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_required_field_is_invalid_schema() -> None:  # Test 7
    result = await _turn(_client(_response('{"symbolic_inference": "x", "world_model_update": null}')))
    _assert_safe_fallback(result, "invalid_schema")


@pytest.mark.asyncio
async def test_wrong_field_type_is_invalid_schema() -> None:  # Test 8
    result = await _turn(_client(_response('{"symbolic_inference": "x", "natural_language_response": 42}')))
    _assert_safe_fallback(result, "invalid_schema")


@pytest.mark.asyncio
async def test_bad_world_model_update_is_invalid_schema() -> None:
    bad = json.dumps({
        "symbolic_inference": "x", "natural_language_response": "hi",
        "world_model_update": {"triple": "not-a-dict", "confidence": 0.9},
    })
    result = await _turn(_client(_response(bad)))
    _assert_safe_fallback(result, "invalid_schema")


@pytest.mark.asyncio
async def test_extra_fields_are_tolerated() -> None:  # Test 9 (current policy: ignore extras)
    extra = json.dumps({
        "symbolic_inference": "calm", "natural_language_response": "hi",
        "world_model_update": None, "mood": "sunny", "debug": {"x": 1},
    })
    result = await _turn(_client(_response(extra)))
    assert result.response_status == "valid"
    assert result.natural_language_response == "hi"
    assert result.symbolic_inference == "calm"


@pytest.mark.asyncio
async def test_falsy_world_model_update_is_none_as_before() -> None:
    for wmu in ("null", "{}", '""', "false"):
        raw = f'{{"symbolic_inference": "calm", "natural_language_response": "hi", "world_model_update": {wmu}}}'
        result = await _turn(_client(_response(raw)))
        assert result.response_status == "valid"
        assert result.world_model_update is None


# ── Tests 10, 16: Go-shaped boundary (nothing for the ring; emotion unchanged) ─


@pytest.mark.asyncio
async def test_failed_turn_yields_empty_symbolic_inference_for_go() -> None:  # Test 10
    for resp in (
        _response(MALFORMED), _response(PROSE), _response(None),
        _response(MALFORMED, stop_reason="max_tokens"),
    ):
        result = await _turn(_client(resp))
        assert result.symbolic_inference == ""  # Go pushes only non-empty inferences
        assert result.response_status != "valid"


# ── Tests 11, 14, 15, 18: route level ────────────────────────────────────────


def _mount(app, llm, tmp_path) -> MagicMock:
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
    return memory


def _post(app, client, tmp_path, message: str = "what do I own") -> tuple[dict, MagicMock]:
    memory = _mount(app, client, tmp_path)
    try:
        r = TestClient(app).post(
            "/api/cognition", json={"message": message, "session_id": "s1"},
            headers={"X-Aria-Owner": "o"},
        )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    return r.json(), memory


def test_route_valid_response_writes_memory_and_returns_fields(tmp_path) -> None:  # Test 14
    from app.main import app

    body, memory = _post(app, _client(_response(VALID)), tmp_path)
    assert body["natural_language_response"] == "Nice bike!"
    assert body["symbolic_inference"] == "user is focused on the bike"
    assert body["world_model_update"]["triple"]["object"] == "a red bicycle"
    memory.store_triple.assert_awaited_once()
    assert memory.store_triple.await_args.kwargs["obj"] == "a red bicycle"


@pytest.mark.parametrize(
    "resp",
    [
        _response(f'{MALFORMED} "{PRIVATE}"'),
        _response(PROSE),
        _response(VALID, stop_reason="max_tokens"),
        _response(None),
        _response('{"symbolic_inference": "x"}'),
    ],
    ids=["malformed", "prose", "max_tokens", "empty", "invalid_schema"],
)
def test_route_failed_turn_is_safe_and_writes_nothing(tmp_path, resp) -> None:  # Tests 11, 15, 18
    from app.main import app

    body, memory = _post(app, _client(resp), tmp_path)
    # TTS-facing text is the safe fallback only.
    assert body["natural_language_response"] == SAFE_FALLBACK_RESPONSE
    assert body["symbolic_inference"] == ""
    assert body["world_model_update"] is None
    memory.store_triple.assert_not_awaited()
    rendered = json.dumps(body)
    for bad in (PRIVATE, MALFORMED, PROSE, "JSONDecodeError", "Traceback", "ValidationError", "anthropic"):
        assert bad not in rendered, bad
    assert "response_status" not in body  # internal signal, not on the wire


@pytest.mark.parametrize("status", ["malformed", "truncated", "empty", "invalid_schema", "refused"])
def test_route_gate_drops_a_fact_carried_by_a_non_valid_turn(tmp_path, status) -> None:
    """Code review P2: even if a future client returned a fact alongside a
    failed status, the route must not persist it."""
    from app.main import app

    llm = MagicMock()
    llm.complete = AsyncMock(
        return_value=CognitionResponse(
            symbolic_inference="should not be trusted",
            world_model_update=WorldModelUpdate(
                triple=WorldModelTriple(subject="user", predicate="owns", object="a ghost fact"),
                confidence=0.9,
                source="explicit_statement",
            ),
            natural_language_response=SAFE_FALLBACK_RESPONSE,
            response_status=status,
        )
    )
    _, memory = _post(app, llm, tmp_path)
    memory.store_triple.assert_not_awaited()


def test_route_gate_still_persists_a_valid_turns_fact(tmp_path) -> None:
    from app.main import app

    llm = MagicMock()
    llm.complete = AsyncMock(
        return_value=CognitionResponse(
            symbolic_inference="user owns a bike",
            world_model_update=WorldModelUpdate(
                triple=WorldModelTriple(subject="user", predicate="owns", object="a real fact"),
                confidence=0.9,
                source="explicit_statement",
            ),
            natural_language_response="Noted.",
            response_status="valid",
        )
    )
    _, memory = _post(app, llm, tmp_path)
    memory.store_triple.assert_awaited_once()
    assert memory.store_triple.await_args.kwargs["obj"] == "a real fact"


# ── Tests 12, 13, 17: observability is safe and intact ───────────────────────


@pytest.mark.asyncio
async def test_failed_turn_logs_no_content() -> None:  # Test 12
    # Unterminated object: no JSON object is found at all.
    with capture_all_levels() as logs:
        await _turn(_client(_response(f'{MALFORMED} "{PRIVATE}"')), message=f"{PRIVATE} what")
    rendered = "\n".join(repr(e) for e in logs)
    assert PRIVATE not in rendered
    assert MALFORMED not in rendered
    rejected = next(e for e in logs if e.get("event") == "llm response rejected")
    assert rejected["response_status"] == "malformed"
    assert rejected["error_type"] == "LLMResponseParseError"
    assert rejected["stop_reason"] == "end_turn"
    assert "raw" not in rejected and "text" not in rendered.split("raw_chars")[0][-20:]
    assert all(k not in rejected for k in ("raw", "text", "completion", "message"))

    # Braces present but invalid JSON: the decoder's error type is logged, never its message.
    with capture_all_levels() as logs:
        await _turn(_client(_response(f'{{"symbolic_inference": "x", "natural_language_response": {PRIVATE}}}')))
    rendered = "\n".join(repr(e) for e in logs)
    assert PRIVATE not in rendered
    rejected = next(e for e in logs if e.get("event") == "llm response rejected")
    assert rejected["error_type"] == "JSONDecodeError"
    assert "Expecting" not in rendered  # JSONDecodeError message text is not logged


@pytest.mark.asyncio
async def test_schema_failure_logs_type_not_validation_message() -> None:
    with capture_all_levels() as logs:
        await _turn(_client(_response(f'{{"symbolic_inference": "{PRIVATE}", "natural_language_response": 42}}')))
    rendered = "\n".join(repr(e) for e in logs)
    assert PRIVATE not in rendered
    assert "Input should be" not in rendered  # pydantic messages carry input values
    rejected = next(e for e in logs if e.get("event") == "llm response rejected")
    assert rejected["response_status"] == "invalid_schema"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "stop_reason", "status"),
    [(VALID, "end_turn", "valid"), (MALFORMED, "max_tokens", "truncated"), (VALID, "weird_new_reason", "valid")],
)
async def test_stop_reason_and_status_logged_safely(text: str, stop_reason: str, status: str) -> None:  # Test 13
    with capture_all_levels() as logs:
        await _turn(_client(_response(text, stop_reason=stop_reason)))
    call = next(e for e in logs if e.get("event") == "llm api call")
    assert call["stop_reason"] == stop_reason
    done = next(e for e in logs if e.get("event") in ("llm response accepted", "llm response rejected"))
    assert done["response_status"] == status
    rendered = "\n".join(repr(e) for e in logs)
    assert "Nice bike" not in rendered and MALFORMED not in rendered


@pytest.mark.asyncio
async def test_r4_cache_telemetry_runs_for_every_outcome() -> None:  # Test 17
    for resp, status in (
        (_response(VALID), "valid"),
        (_response(MALFORMED), "malformed"),
        (_response(MALFORMED, stop_reason="max_tokens"), "truncated"),
        (_response(None), "empty"),
    ):
        with capture_all_levels() as logs:
            await _turn(_client(resp))
        call = next(e for e in logs if e.get("event") == "llm api call")
        assert call["cache_status"] == "none" and call["input_tokens"] == 100
    snap = MetricsCollector().snapshot()
    assert snap["prompt_cache"][_MODEL_HAIKU]["none"] == 4
    assert snap["llm_response"][_MODEL_HAIKU] == {
        "valid": 1, "malformed": 1, "truncated": 1, "empty": 1,
        "invalid_schema": 0, "refused": 0,
    }


def test_metric_buckets_follow_the_status_contract() -> None:
    from app.models.schemas import RESPONSE_STATUSES

    MetricsCollector().record_llm_response(_MODEL_HAIKU, "valid")
    assert set(MetricsCollector().snapshot()["llm_response"][_MODEL_HAIKU]) == set(RESPONSE_STATUSES)


def test_fallback_text_is_plain_and_safe() -> None:
    assert SAFE_FALLBACK_RESPONSE
    for bad in ("{", "}", "JSON", "Anthropic", "Claude", "error", "Error", "exception"):
        assert bad not in SAFE_FALLBACK_RESPONSE
