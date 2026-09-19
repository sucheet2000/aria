"""R4 — Anthropic prompt-cache structure and observability.

Structural proof (no provider calls): the stable SOUL prefix is byte-identical
across turns and carries the only cache breakpoint; everything per-turn or
per-owner sits after it; provider usage counters are classified honestly
(``cache_read_input_tokens > 0`` is the only "hit" signal); nothing about the
prompt or the user is logged.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from structlog.testing import capture_logs

import app.cognition.llm as llm_mod
import app.cognition.prompt as prompt_mod
from app.cognition.llm import (
    _CACHE_MIN_PREFIX_TOKENS,
    _MODEL_HAIKU,
    _MODEL_SONNET,
    LLMClient,
    _cache_eligibility,
    cache_status,
)
from app.cognition.prompt import _load_soul
from app.models.schemas import ConversationTurn, PerceptionFrame
from app.observability.metrics import MetricsCollector

USER_A_MEMORY = "USER_A_PRIVATE_MEMORY_7193"
USER_B_MEMORY = "USER_B_PRIVATE_MEMORY_4821"
PRIVATE = "PRIVATE_CACHE_TEST_2197"
PAYLOAD = '{"symbolic_inference": "calm", "natural_language_response": "ok"}'


@contextmanager
def capture_all_levels() -> Iterator[list[dict]]:
    structlog.configure(wrapper_class=structlog.BoundLogger)
    with capture_logs() as logs:
        structlog.get_logger().debug("capture_all_levels_probe")
        assert logs and logs[-1]["event"] == "capture_all_levels_probe"
        logs.pop()
        yield logs


def _response(
    text: str = PAYLOAD,
    *,
    input_tokens: int = 100,
    cache_read: int | None = 0,
    cache_creation: int | None = 0,
) -> SimpleNamespace:
    """Stand-in Anthropic message; ``None`` omits the cache field entirely."""
    usage: dict[str, int] = {"input_tokens": input_tokens, "output_tokens": 7}
    if cache_read is not None:
        usage["cache_read_input_tokens"] = cache_read
    if cache_creation is not None:
        usage["cache_creation_input_tokens"] = cache_creation
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block], stop_reason="end_turn", usage=SimpleNamespace(**usage))


def _client(response: SimpleNamespace | None = None) -> tuple[LLMClient, AsyncMock]:
    prompt_mod._soul_cache = None
    client = LLMClient(api_key="test-key")
    create = AsyncMock(return_value=response or _response())
    client._client.messages.create = create
    return client, create


async def _turn(
    client: LLMClient,
    message: str,
    *,
    vision: PerceptionFrame | None = None,
    working: list[str] | None = None,
    episodic: list[str] | None = None,
    history: list[ConversationTurn] | None = None,
):
    return await client.complete(
        message=message,
        vision=vision or PerceptionFrame(),
        conversation_history=history or [],
        working_memory=working or [],
        episodic_memory=episodic or [],
    )


def _system(create: AsyncMock, call: int = -1) -> list[dict]:
    return create.call_args_list[call].kwargs["system"]


@pytest.fixture(autouse=True)
def _reset_metrics():
    MetricsCollector()._token_cost = {}
    MetricsCollector()._prompt_cache = {}
    llm_mod._eligibility_logged.clear()
    saved = structlog.get_config()
    yield
    structlog.configure(**saved)


# ── Tests 1, 3–6, 13, 14: stable prefix vs dynamic context ───────────────────


@pytest.mark.asyncio
async def test_stable_prefix_identical_across_different_turns() -> None:  # Test 1
    client, create = _client()
    await _turn(
        client, "first message about bicycles",
        vision=PerceptionFrame(emotion="happy", emotion_confidence=0.8, pitch=12.345, face_detected=True),
        working=["user is focused on a bicycle"], episodic=["user owns a red bicycle"],
    )
    await _turn(
        client, "completely different second message",
        vision=PerceptionFrame(emotion="sad", emotion_confidence=0.2, yaw=-7.5, face_detected=True),
        working=["user seems tired"], episodic=["user lives in Tokyo"],
        history=[ConversationTurn(role="user", content="earlier"), ConversationTurn(role="assistant", content="reply")],
    )
    first, second = _system(create, 0), _system(create, 1)
    assert first[0] == second[0]                     # stable block byte-identical (incl. cache_control)
    assert first[0]["text"] == _load_soul()
    assert first[1]["text"] != second[1]["text"]     # dynamic block differs


@pytest.mark.asyncio
async def test_current_message_not_in_stable_prefix() -> None:  # Test 3
    client, create = _client()
    await _turn(client, "xyzzy_current_transcript_marker")
    stable, dynamic = _system(create)
    assert "xyzzy_current_transcript_marker" not in stable["text"]
    assert "xyzzy_current_transcript_marker" in dynamic["text"]


@pytest.mark.asyncio
async def test_vision_not_in_stable_prefix() -> None:  # Test 4
    client, create = _client()
    await _turn(
        client, "hi",
        vision=PerceptionFrame(emotion="surprised", emotion_confidence=0.731, pitch=12.345, yaw=-7.5, roll=3.25, face_detected=True),
    )
    stable, dynamic = _system(create)
    for marker in ("surprised", "0.731", "12.3", "-7.5", "3.2", "Face visible"):
        assert marker not in stable["text"], marker
        assert marker in dynamic["text"], marker


@pytest.mark.asyncio
async def test_working_memory_not_in_stable_prefix() -> None:  # Test 5
    client, create = _client()
    await _turn(client, "hi", working=["WORKING_RING_SENTINEL_5501 user is building"])
    stable, dynamic = _system(create)
    assert "WORKING_RING_SENTINEL_5501" not in stable["text"]
    assert "WORKING_RING_SENTINEL_5501" in dynamic["text"]


@pytest.mark.asyncio
async def test_retrieved_memory_not_in_stable_prefix() -> None:  # Test 6
    client, create = _client()
    await _turn(client, "hi", episodic=["user owns RETRIEVED_FACT_SENTINEL_8804"])
    stable, dynamic = _system(create)
    assert "RETRIEVED_FACT_SENTINEL_8804" not in stable["text"]
    assert "RETRIEVED_FACT_SENTINEL_8804" in dynamic["text"]


@pytest.mark.asyncio
async def test_dynamic_observation_tracks_current_vision() -> None:  # Test 13 (R2)
    client, create = _client()
    await _turn(client, "hi", vision=PerceptionFrame(emotion="happy", emotion_confidence=0.8, face_detected=True))
    await _turn(client, "hi", vision=PerceptionFrame(emotion="sad", emotion_confidence=0.2, face_detected=True))
    first, second = _system(create, 0), _system(create, 1)
    assert first[0] == second[0]
    assert "happy (confidence 0.800)" in first[1]["text"]
    assert "sad (confidence 0.200)" in second[1]["text"]
    assert "sad" not in first[1]["text"].split("Head pose")[0]


@pytest.mark.asyncio
async def test_retrieved_memory_is_current_turn_dynamic_context() -> None:  # Test 14 (R1)
    client, create = _client()
    await _turn(client, "what color is my bicycle", episodic=["user owns a red bicycle"])
    await _turn(client, "what color is my bicycle", episodic=[])
    first, second = _system(create, 0), _system(create, 1)
    assert "user owns a red bicycle" in first[1]["text"]
    assert "user owns a red bicycle" not in second[1]["text"]  # not carried over by the cache layer
    assert "user owns a red bicycle" not in first[0]["text"]
    assert first[0] == second[0]


# ── Test 2: personal data of two owners never enters the stable block ────────


@pytest.mark.asyncio
async def test_two_owners_private_memory_excluded_from_stable_block() -> None:
    client, create = _client()
    await _turn(
        client, "owner A speaking", episodic=[f"user likes {USER_A_MEMORY}"],
        working=[f"owner A ring {USER_A_MEMORY}"],
        history=[ConversationTurn(role="user", content=f"A said {USER_A_MEMORY}")],
    )
    await _turn(
        client, "owner B speaking", episodic=[f"user likes {USER_B_MEMORY}"],
        working=[f"owner B ring {USER_B_MEMORY}"],
        history=[ConversationTurn(role="user", content=f"B said {USER_B_MEMORY}")],
    )
    for call in (0, 1):
        stable = _system(create, call)[0]
        assert USER_A_MEMORY not in stable["text"]
        assert USER_B_MEMORY not in stable["text"]
        assert "cache_control" in stable
    assert _system(create, 0)[0] == _system(create, 1)[0]
    assert USER_A_MEMORY in _system(create, 0)[1]["text"]
    assert USER_B_MEMORY in _system(create, 1)[1]["text"]
    assert USER_A_MEMORY not in _system(create, 1)[1]["text"]


# ── Test 7: breakpoint placement and request shape ───────────────────────────


@pytest.mark.asyncio
async def test_cache_breakpoint_on_stable_block_only() -> None:
    client, create = _client()
    await _turn(client, "hello", episodic=["fact"], working=["ring"])
    kwargs = create.call_args.kwargs
    system = kwargs["system"]
    assert len(system) == 2
    assert system[0]["type"] == "text" and system[0]["text"] == _load_soul()
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in system[1]
    assert system[1]["text"].startswith("Current observation:")
    assert kwargs["messages"][-1] == {"role": "user", "content": "hello"}
    # Prompt caching is GA: the 2024 beta header is gone.
    assert "extra_headers" not in kwargs
    assert kwargs["model"] == _MODEL_HAIKU


# ── Tests 8–11: usage classification ─────────────────────────────────────────


def test_cache_status_created() -> None:  # Test 8
    assert cache_status(SimpleNamespace(cache_creation_input_tokens=650, cache_read_input_tokens=0)) == "created"


def test_cache_status_read_is_the_hit_signal() -> None:  # Test 9
    assert cache_status(SimpleNamespace(cache_creation_input_tokens=0, cache_read_input_tokens=650)) == "read"
    # A read alongside an incremental write is still a hit on the shared prefix.
    assert cache_status(SimpleNamespace(cache_creation_input_tokens=40, cache_read_input_tokens=650)) == "read"


def test_cache_status_missing_fields_is_unknown_and_safe() -> None:  # Test 10
    assert cache_status(SimpleNamespace(input_tokens=100, output_tokens=5)) == "unknown"
    assert cache_status(None) == "unknown"
    # Malformed counter (not absent): still unknown, never a crash.
    assert cache_status(SimpleNamespace(cache_creation_input_tokens="x", cache_read_input_tokens=5)) == "unknown"


def test_cache_status_null_counters_mean_no_cache_activity() -> None:  # code review P2
    # SDK 0.85 types both counters Optional[int]; null == 0, consistent with
    # the cache_read_tokens=0 the same log line reports.
    assert cache_status(SimpleNamespace(cache_creation_input_tokens=None, cache_read_input_tokens=None)) == "none"
    assert cache_status(SimpleNamespace(cache_creation_input_tokens=None, cache_read_input_tokens=12)) == "read"


@pytest.mark.asyncio
async def test_absent_usage_still_counts_as_unknown_in_metrics() -> None:  # code review P3
    response = _response()
    response.usage = None
    client, _ = _client(response)
    await _turn(client, "hello")
    assert MetricsCollector().snapshot()["prompt_cache"][_MODEL_HAIKU]["unknown"] == 1


def test_zero_cache_read_is_not_a_hit() -> None:  # Test 11
    assert cache_status(SimpleNamespace(cache_creation_input_tokens=0, cache_read_input_tokens=0)) == "none"


@pytest.mark.asyncio
async def test_llm_call_log_and_metrics_carry_cache_status() -> None:  # Tests 8–11 through the client
    cases = [
        (_response(cache_creation=650, cache_read=0), "created"),
        (_response(cache_creation=0, cache_read=650), "read"),
        (_response(cache_creation=0, cache_read=0), "none"),
        (_response(cache_creation=None, cache_read=None), "unknown"),
    ]
    for response, expected in cases:
        client, _ = _client(response)
        with capture_all_levels() as logs:
            await _turn(client, "hello")
        call = next(e for e in logs if e.get("event") == "llm api call")
        assert call["cache_status"] == expected, expected
        assert call["input_tokens"] == 100
    snap = MetricsCollector().snapshot()["prompt_cache"][_MODEL_HAIKU]
    assert snap == {"read": 1, "created": 1, "none": 1, "unknown": 1}


# ── Test 12: S2 privacy ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_observability_logs_no_content() -> None:
    client, _ = _client(_response(cache_creation=650, cache_read=0))
    with capture_all_levels() as logs:
        await _turn(
            client, f"{PRIVATE} what did I say", episodic=[f"user owns {PRIVATE}"],
            working=[f"ring {PRIVATE}"], history=[ConversationTurn(role="user", content=PRIVATE)],
        )
    rendered = "\n".join(repr(e) for e in logs)
    assert PRIVATE not in rendered
    assert "Current observation" not in rendered
    assert _load_soul()[:40] not in rendered
    call = next(e for e in logs if e.get("event") == "llm api call")
    assert call["cache_creation_tokens"] == 650 and call["cache_read_tokens"] == 0
    elig = next(e for e in logs if e.get("event") == "prompt cache eligibility")
    assert set(elig) >= {"model", "stable_prefix_chars", "stable_prefix_tokens_est", "min_cacheable_tokens", "eligible"}
    assert PRIVATE not in repr(elig)


# ── Test 15: the response contract lives in the stable block and still parses ─


def test_response_contract_in_stable_block_and_parsing_unchanged() -> None:
    prompt_mod._soul_cache = None
    soul = _load_soul()
    for key in ("symbolic_inference", "world_model_update", "natural_language_response", "explicit_statement"):
        assert key in soul
    client = LLMClient(api_key="test-key")
    parsed = client._parse_response(
        '{"symbolic_inference": "focused", "world_model_update": {"triple": {"subject": "user", '
        '"predicate": "owns", "object": "a bike"}, "confidence": 0.9, "source": "explicit_statement"}, '
        '"natural_language_response": "nice bike"}'
    )
    assert parsed.symbolic_inference == "focused"
    assert parsed.world_model_update is not None
    assert parsed.world_model_update.triple.object == "a bike"
    assert parsed.natural_language_response == "nice bike"


# ── Eligibility helper: provider minimums are explicit, never asserted brittly ─


def test_cache_eligibility_helper_reports_threshold_honestly() -> None:
    assert _CACHE_MIN_PREFIX_TOKENS[_MODEL_HAIKU] == 4096
    assert _CACHE_MIN_PREFIX_TOKENS[_MODEL_SONNET] == 1024
    below = _cache_eligibility(_MODEL_SONNET, prefix_chars=2800)
    assert below["eligible"] is False and below["min_cacheable_tokens"] == 1024
    assert below["stable_prefix_tokens_est"] == 700
    above = _cache_eligibility(_MODEL_SONNET, prefix_chars=8000)
    assert above["eligible"] is True
    unknown = _cache_eligibility("claude-unlisted-model", prefix_chars=8000)
    assert unknown["eligible"] is None and unknown["min_cacheable_tokens"] is None


@pytest.mark.asyncio
async def test_eligibility_logged_once_per_model() -> None:
    client, _ = _client()
    with capture_all_levels() as logs:
        await _turn(client, "hello")
        await _turn(client, "hello again")
    events = [e for e in logs if e.get("event") == "prompt cache eligibility"]
    assert len(events) == 1
    assert events[0]["model"] == _MODEL_HAIKU
    assert events[0]["stable_prefix_chars"] == len(_load_soul())
    assert events[0]["min_cacheable_tokens"] == 4096
    assert isinstance(events[0]["eligible"], bool)


def test_metrics_reset_fixture_keeps_prompt_cache_snapshot_shape() -> None:
    MetricsCollector().record_prompt_cache(_MODEL_SONNET, "read")
    MetricsCollector().record_prompt_cache(_MODEL_SONNET, "read")
    MetricsCollector().record_prompt_cache(_MODEL_SONNET, "created")
    assert MetricsCollector().snapshot()["prompt_cache"][_MODEL_SONNET] == {
        "read": 2, "created": 1, "none": 0, "unknown": 0,
    }


def test_status_only_reads_usage_never_prompt() -> None:
    usage = MagicMock()
    usage.cache_read_input_tokens = 10
    usage.cache_creation_input_tokens = 0
    assert cache_status(usage) == "read"
