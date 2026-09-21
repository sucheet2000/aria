"""
Week 6: LMCache + tiered LLM routing tests.

- test_tier_routing: verify each tier classification
- test_soul_cache: verify second call returns cached value
- test_local_handlers: "repeat that" returns without API call
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cognition.llm import (
    SAFE_FALLBACK_RESPONSE,
    LLMClient,
    _handle_local,
    classify_tier,
)
from app.models.schemas import ConversationTurn

# ── tier classification ───────────────────────────────────────────────────────

class TestTierRouting:
    def test_tier0_repeat_that(self) -> None:
        assert classify_tier("repeat that") == 0

    def test_tier0_stop(self) -> None:
        assert classify_tier("stop") == 0

    def test_tier0_that_would_be_all(self) -> None:
        assert classify_tier("that would be all") == 0

    def test_tier0_what_time_is_it(self) -> None:
        assert classify_tier("what time is it") == 0

    def test_tier1_short_factual(self) -> None:
        assert classify_tier("hello") == 1

    def test_tier1_simple_question(self) -> None:
        assert classify_tier("what is your name") == 1

    def test_tier2_emotion_keyword(self) -> None:
        assert classify_tier("I feel really anxious today") == 2

    def test_tier2_complex_reasoning(self) -> None:
        assert classify_tier("can you explain why I am struggling with this") == 2

    def test_tier2_long_utterance(self) -> None:
        long = " ".join(["word"] * 20)
        assert classify_tier(long) == 2

    def test_tier2_memory_keyword(self) -> None:
        assert classify_tier("do you remember what I said before") == 2

    def test_tier1_punctuation_stripped(self) -> None:
        # Trailing punctuation should not affect tier
        assert classify_tier("hi there.") == 1


# ── local handlers ────────────────────────────────────────────────────────────

class TestLocalHandlers:
    def test_repeat_that_returns_last_response(self) -> None:
        result = _handle_local("repeat that", "Hello world")
        assert result == "Hello world"

    def test_repeat_that_no_prior_response(self) -> None:
        result = _handle_local("repeat that", "")
        assert "haven't" in result.lower()

    def test_stop_returns_empty(self) -> None:
        assert _handle_local("stop", "anything") == ""

    def test_that_would_be_all_returns_empty(self) -> None:
        assert _handle_local("that would be all", "anything") == ""

    def test_time_returns_time_string(self) -> None:
        result = _handle_local("what time is it", "")
        assert ":" in result  # HH:MM format

    @pytest.mark.asyncio
    async def test_tier0_complete_no_api_call(self) -> None:
        """Tier 0 complete() must not invoke the Anthropic client."""
        client = LLMClient(api_key="test-key")

        mock_create = AsyncMock()
        client._client.messages.create = mock_create

        from app.models.schemas import ConversationTurn, PerceptionFrame
        vision = PerceptionFrame(emotion="neutral", emotion_confidence=0.9, hands_detected=False)
        result = await client.complete(
            message="repeat that",
            vision=vision,
            conversation_history=[ConversationTurn(role="assistant", content="prior answer")],
            working_memory=[],
            episodic_memory=[],
        )

        mock_create.assert_not_called()
        assert result.natural_language_response == "prior answer"
        assert result.symbolic_inference == "local_handler"

    @pytest.mark.asyncio
    async def test_replay_reads_history_not_shared_state(self) -> None:
        """Replay comes from conversation_history, not shared instance state (no cross-session leak)."""
        from app.models.schemas import ConversationTurn, PerceptionFrame

        client = LLMClient(api_key="test-key")
        client._client.messages.create = AsyncMock()

        async def replay(history: list[ConversationTurn]) -> str:
            r = await client.complete("repeat that", PerceptionFrame(), history, [], [])
            return r.natural_language_response

        assert await replay([ConversationTurn(role="assistant", content="A reply")]) == "A reply"
        # a different "session" must not leak the previous reply
        assert await replay([ConversationTurn(role="assistant", content="B reply")]) == "B reply"
        # no assistant history → default, never a leaked prior reply
        assert await replay([]) == "I haven't said anything yet."
        assert not hasattr(client, "_last_response")


# ── soul cache ────────────────────────────────────────────────────────────────

class TestSoulCache:
    def test_second_call_returns_cached_value(self) -> None:
        """_load_soul() must cache after first read — the file is only read once."""
        import app.cognition.prompt as prompt_mod

        # Reset cache so test is isolated.
        prompt_mod._soul_cache = None

        first = prompt_mod._load_soul()

        # Poison the path so if it reads again it would fail.
        with patch.object(prompt_mod.pathlib.Path, "read_text", side_effect=RuntimeError("should not read again")):
            second = prompt_mod._load_soul()

        assert first == second

    def test_cache_persists_empty_string_on_missing_file(self) -> None:
        """If SOUL.md is missing, cache stores '' and does not retry the read."""
        import app.cognition.prompt as prompt_mod

        prompt_mod._soul_cache = None

        with patch.object(prompt_mod.pathlib.Path, "exists", return_value=False):
            result = prompt_mod._load_soul()

        assert result == ""
        assert prompt_mod._soul_cache == ""


# ── REL-2: timeout, bounded retry, empty-completion guard ─────────────────────

def _fake_response(
    text: str | None,
    *,
    cache_read: int = 0,
    cache_creation: int = 0,
    input_tokens: int = 100,
) -> MagicMock:
    """Build a stand-in Anthropic message response.

    ``text=None`` yields an empty ``content`` list (empty completion).
    """
    response = MagicMock()
    if text is None:
        response.content = []
    else:
        block = MagicMock()
        block.text = text
        response.content = [block]
    usage = MagicMock()
    usage.cache_read_input_tokens = cache_read
    usage.cache_creation_input_tokens = cache_creation
    usage.input_tokens = input_tokens
    response.usage = usage
    return response


class TestAnthropicReliability:
    def test_client_uses_settings_defaults(self) -> None:
        """No explicit timeout/retries → the client is wired from settings."""
        from app.config import settings

        client = LLMClient(api_key="test-key")
        assert client._client.timeout == settings.ANTHROPIC_TIMEOUT_SECONDS
        assert client._client.max_retries == settings.ANTHROPIC_MAX_RETRIES

    def test_client_accepts_injected_timeout_and_retries(self) -> None:
        """Explicit values are passed straight through to AsyncAnthropic."""
        client = LLMClient(api_key="test-key", timeout=12.5, max_retries=7)
        assert client._client.timeout == 12.5
        assert client._client.max_retries == 7

    @pytest.mark.asyncio
    async def test_empty_completion_returns_fallback_not_indexerror(self) -> None:
        """An empty ``content`` list must not raise IndexError."""
        from app.models.schemas import PerceptionFrame

        client = LLMClient(api_key="test-key")
        client._client.messages.create = AsyncMock(return_value=_fake_response(None))

        result = await client.complete(
            message="hello",
            vision=PerceptionFrame(),
            conversation_history=[],
            working_memory=[],
            episodic_memory=[],
        )

        assert result.response_status == "empty"
        assert result.symbolic_inference == ""
        assert result.world_model_update is None
        assert result.natural_language_response == SAFE_FALLBACK_RESPONSE

    @pytest.mark.asyncio
    async def test_non_text_block_returns_fallback(self) -> None:
        """A first block without a ``.text`` attribute falls back, not AttributeError."""
        from app.models.schemas import PerceptionFrame

        client = LLMClient(api_key="test-key")
        block = MagicMock(spec=[])  # no .text attribute
        response = MagicMock()
        response.content = [block]
        client._client.messages.create = AsyncMock(return_value=response)

        result = await client.complete(
            message="hello",
            vision=PerceptionFrame(),
            conversation_history=[],
            working_memory=[],
            episodic_memory=[],
        )

        assert result.response_status == "empty"
        assert result.symbolic_inference == ""

    @pytest.mark.asyncio
    async def test_wellformed_completion_parses(self) -> None:
        """A normal completion still parses content[0].text (no regression)."""
        from app.models.schemas import PerceptionFrame

        client = LLMClient(api_key="test-key")
        payload = (
            '{"symbolic_inference": "user is calm", '
            '"natural_language_response": "Hi there."}'
        )
        client._client.messages.create = AsyncMock(return_value=_fake_response(payload))

        result = await client.complete(
            message="hello",
            vision=PerceptionFrame(),
            conversation_history=[],
            working_memory=[],
            episodic_memory=[],
        )

        assert result.symbolic_inference == "user is calm"
        assert result.natural_language_response == "Hi there."


# ── prompt caching: stable SOUL prefix must be its own cached block ────────────


class TestPromptCachingBreakpoint:
    @pytest.mark.asyncio
    async def test_system_splits_cached_soul_from_uncached_observation(self) -> None:
        """The cache breakpoint must sit after the stable SOUL prefix, not after
        the per-turn observation — otherwise the ephemeral cache never hits.

        Expect two system blocks:
          block[0] = SOUL (cached, no per-turn content)
          block[1] = dynamic observation (uncached)
        """
        import app.cognition.prompt as prompt_mod
        from app.cognition.prompt import _load_soul
        from app.models.schemas import PerceptionFrame

        # Force a fresh read of the real (non-empty) SOUL.md so this test is
        # isolated from any prior test that poisoned the module cache.
        prompt_mod._soul_cache = None

        client = LLMClient(api_key="test-key")
        payload = (
            '{"symbolic_inference": "ok", "natural_language_response": "hi"}'
        )
        mock_create = AsyncMock(return_value=_fake_response(payload))
        client._client.messages.create = mock_create

        transcript = "xyzzy_unique_transcript_marker"
        await client.complete(
            message=transcript,
            vision=PerceptionFrame(emotion="neutral", emotion_confidence=0.5),
            conversation_history=[],
            working_memory=[],
            episodic_memory=[],
        )

        system = mock_create.call_args.kwargs["system"]
        assert isinstance(system, list)
        assert len(system) == 2

        soul_block, obs_block = system

        # block[0]: the stable SOUL prefix, cached, with no per-turn content.
        assert soul_block["text"] == _load_soul()
        assert soul_block["cache_control"] == {"type": "ephemeral"}
        assert "Current observation" not in soul_block["text"]
        assert transcript not in soul_block["text"]

        # block[1]: the per-turn observation, NOT cached.
        assert "Current observation" in obs_block["text"]
        assert transcript in obs_block["text"]
        assert "cache_control" not in obs_block


# ── OBS-3: token-usage → cost metrics recording ───────────────────────────────


class TestTokenUsageRecording:
    @pytest.mark.asyncio
    async def test_cache_hit_records_to_cached_and_uncached_buckets(self) -> None:
        """A cache-hit completion splits usage into cached vs uncached buckets."""
        from app.cognition.llm import _MODEL_HAIKU
        from app.models.schemas import PerceptionFrame
        from app.observability.metrics import MetricsCollector

        MetricsCollector()._token_cost = {}

        client = LLMClient(api_key="test-key")
        payload = (
            '{"symbolic_inference": "ok", "natural_language_response": "hi"}'
        )
        client._client.messages.create = AsyncMock(
            return_value=_fake_response(
                payload, cache_read=900, cache_creation=100, input_tokens=20
            )
        )

        await client.complete(
            message="hello",
            vision=PerceptionFrame(),
            conversation_history=[],
            working_memory=[],
            episodic_memory=[],
        )

        snap = MetricsCollector().snapshot()
        assert snap["token_cost"][_MODEL_HAIKU] == {"cached": 900, "uncached": 120}

    @pytest.mark.asyncio
    async def test_missing_usage_is_silent_noop(self) -> None:
        """A response with ``usage=None`` records nothing and never raises."""
        from app.models.schemas import PerceptionFrame
        from app.observability.metrics import MetricsCollector

        MetricsCollector()._token_cost = {}

        client = LLMClient(api_key="test-key")
        payload = (
            '{"symbolic_inference": "ok", "natural_language_response": "hi"}'
        )
        response = _fake_response(payload)
        response.usage = None
        client._client.messages.create = AsyncMock(return_value=response)

        result = await client.complete(
            message="hello",
            vision=PerceptionFrame(),
            conversation_history=[],
            working_memory=[],
            episodic_memory=[],
        )

        assert result.natural_language_response == "hi"
        assert MetricsCollector().snapshot()["token_cost"] == {}

    @pytest.mark.asyncio
    async def test_non_int_usage_field_is_silent_noop(self) -> None:
        """A non-integer usage field records nothing (no partial record, no raise)."""
        from app.models.schemas import PerceptionFrame
        from app.observability.metrics import MetricsCollector

        MetricsCollector()._token_cost = {}

        client = LLMClient(api_key="test-key")
        payload = (
            '{"symbolic_inference": "ok", "natural_language_response": "hi"}'
        )
        response = _fake_response(payload)
        response.usage.cache_read_input_tokens = "not-a-number"
        client._client.messages.create = AsyncMock(return_value=response)

        result = await client.complete(
            message="hello",
            vision=PerceptionFrame(),
            conversation_history=[],
            working_memory=[],
            episodic_memory=[],
        )

        assert result.natural_language_response == "hi"
        assert MetricsCollector().snapshot()["token_cost"] == {}

    @pytest.mark.asyncio
    async def test_tier0_records_no_token_cost(self) -> None:
        """Tier 0 makes no API call, so nothing is recorded."""
        from app.models.schemas import ConversationTurn, PerceptionFrame
        from app.observability.metrics import MetricsCollector

        MetricsCollector()._token_cost = {}

        client = LLMClient(api_key="test-key")
        client._client.messages.create = AsyncMock()

        await client.complete(
            message="repeat that",
            vision=PerceptionFrame(),
            conversation_history=[ConversationTurn(role="assistant", content="prior")],
            working_memory=[],
            episodic_memory=[],
        )

        assert MetricsCollector().snapshot()["token_cost"] == {}


# ── conversation-history window: keep the last 16 verbatim role-entries ────────


class TestConversationHistoryWindow:
    @staticmethod
    def _history(n: int) -> list[ConversationTurn]:
        return [
            ConversationTurn(
                role="user" if i % 2 == 0 else "assistant",
                content=f"turn-{i}",
            )
            for i in range(n)
        ]

    @pytest.mark.asyncio
    async def test_more_than_16_entries_keeps_only_last_16(self) -> None:
        """With >16 prior role-entries, only the last 16 are sent verbatim
        (plus the current user message appended)."""
        from app.models.schemas import PerceptionFrame

        client = LLMClient(api_key="test-key")
        payload = '{"symbolic_inference": "ok", "natural_language_response": "hi"}'
        mock_create = AsyncMock(return_value=_fake_response(payload))
        client._client.messages.create = mock_create

        history = self._history(20)  # 20 > 16
        await client.complete(
            message="hello",
            vision=PerceptionFrame(),
            conversation_history=history,
            working_memory=[],
            episodic_memory=[],
        )

        messages = mock_create.call_args.kwargs["messages"]
        # last 16 history turns + the current user message
        assert len(messages) == 17
        assert messages[:-1] == [
            {"role": t.role, "content": t.content} for t in history[-16:]
        ]
        # oldest kept entry is turn-4 (indices 4..19); turn-3 is dropped
        assert messages[0] == {"role": "user", "content": "turn-4"}
        assert {"role": "assistant", "content": "turn-3"} not in messages
        # the current user message is appended last
        assert messages[-1] == {"role": "user", "content": "hello"}

    @pytest.mark.asyncio
    async def test_16_or_fewer_entries_all_kept(self) -> None:
        """With ≤16 prior role-entries, all are sent verbatim."""
        from app.models.schemas import PerceptionFrame

        client = LLMClient(api_key="test-key")
        payload = '{"symbolic_inference": "ok", "natural_language_response": "hi"}'
        mock_create = AsyncMock(return_value=_fake_response(payload))
        client._client.messages.create = mock_create

        history = self._history(10)  # 10 <= 16
        await client.complete(
            message="hello",
            vision=PerceptionFrame(),
            conversation_history=history,
            working_memory=[],
            episodic_memory=[],
        )

        messages = mock_create.call_args.kwargs["messages"]
        assert len(messages) == 11
        assert messages[:-1] == [
            {"role": t.role, "content": t.content} for t in history
        ]
        assert messages[-1] == {"role": "user", "content": "hello"}


# ── Workstream J: every rule must be reachable ───────────────────────────────


class TestTierKeywordsAreReachable:
    """A rule that can never fire is worse than a missing rule: it reads as
    covered. The candidate utterance is lowercased before matching, so any
    keyword carrying an uppercase letter is dead on arrival — which is what
    happened to "should I", the one rule meant to catch advice-seeking.
    """

    def test_no_keyword_is_unreachable(self) -> None:
        from app.cognition.llm import _TIER2_KEYWORDS

        unreachable = sorted(k for k in _TIER2_KEYWORDS if k != k.casefold())
        assert unreachable == [], (
            f"these keywords can never match lowercased input: {unreachable}"
        )

    @pytest.mark.parametrize(
        "utterance",
        [
            "should I take the job",
            "Should I take the job",
            "SHOULD I TAKE THE JOB",
        ],
    )
    def test_advice_seeking_reaches_tier_two(self, utterance: str) -> None:
        assert classify_tier(utterance) == 2

    def test_every_keyword_routes_its_own_phrase_to_tier_two(self) -> None:
        from app.cognition.llm import _TIER2_KEYWORDS

        # Each keyword, used in a short utterance, must reach tier 2 on its own
        # merit rather than via the long-query threshold.
        failed = []
        for kw in sorted(_TIER2_KEYWORDS):
            if classify_tier(kw) != 2:
                failed.append(kw)
        assert failed == [], f"keywords that did not route to tier 2: {failed}"
