"""
Week 6: LMCache + tiered LLM routing tests.

- test_tier_routing: verify each tier classification
- test_soul_cache: verify second call returns cached value
- test_local_handlers: "repeat that" returns without API call
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cognition.llm import LLMClient, classify_tier, _handle_local


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
        client._last_response = "prior answer"

        from app.models.schemas import VisionContext
        vision = VisionContext(
            emotion="neutral",
            confidence=0.9,
            pitch=0.0,
            yaw=0.0,
            roll=0.0,
            hands_detected=False,
        )
        result = await client.complete(
            message="repeat that",
            vision=vision,
            conversation_history=[],
            working_memory=[],
            episodic_memory=[],
        )

        mock_create.assert_not_called()
        assert result.natural_language_response == "prior answer"
        assert result.symbolic_inference == "local_handler"


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
