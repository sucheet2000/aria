from __future__ import annotations

import json
import re
import time
from typing import Literal

import structlog
from anthropic import AsyncAnthropic

from app.cognition.prompt import build_system_parts
from app.config import settings
from app.models.schemas import (
    CognitionResponse,
    ConversationTurn,
    PerceptionFrame,
    WorldModelTriple,
    WorldModelUpdate,
)
from app.observability.metrics import MetricsCollector

logger = structlog.get_logger()

# ── Tier definitions ─────────────────────────────────────────────────────────
_MODEL_HAIKU  = "claude-haiku-4-5-20251001"
_MODEL_SONNET = "claude-sonnet-4-6"

Tier = Literal[0, 1, 2]

# Tier 0 local handlers: exact lower-case match → canned response (no API call)
_LOCAL_HANDLERS: dict[str, str] = {
    "repeat that": "__REPLAY__",
    "stop": "__STOP__",
    "that would be all": "__STOP__",
    "what time is it": "__TIME__",
    "what's the time": "__TIME__",
}

# Keywords that push a query to Tier 2 (complex reasoning / Sonnet)
_TIER2_KEYWORDS = frozenset(
    {"feel", "feeling", "emotion", "why", "explain", "remember", "memory",
     "complex", "analyze", "compare", "recommend", "advice", "should I",
     "help me", "reason", "think about", "understand"}
)

_TIER2_WORD_THRESHOLD = 15  # queries longer than this default to Tier 2


def classify_tier(utterance: str) -> Tier:
    """Classify utterance into a routing tier using pure heuristics (no LLM call).

    Returns:
        0 — handle locally, no API call
        1 — Claude Haiku (short/factual)
        2 — Claude Sonnet (complex/nuanced)
    """
    normalized = utterance.strip().lower().rstrip("?.,!")

    if normalized in _LOCAL_HANDLERS:
        return 0

    words = normalized.split()
    word_count = len(words)

    if word_count > _TIER2_WORD_THRESHOLD:
        return 2

    for kw in _TIER2_KEYWORDS:
        if kw in normalized:
            return 2

    return 1


def _handle_local(utterance: str, last_response: str) -> str:
    """Return a canned response for Tier 0 utterances."""
    normalized = utterance.strip().lower().rstrip("?.,!")
    action = _LOCAL_HANDLERS.get(normalized, "__UNKNOWN__")
    if action == "__REPLAY__":
        return last_response or "I haven't said anything yet."
    if action == "__STOP__":
        return ""  # caller interprets empty string as stop signal
    if action == "__TIME__":
        from datetime import datetime
        return f"It's {datetime.now().strftime('%H:%M')}."
    return ""


def _record_token_usage(model: str, response: object) -> None:
    """Record input-token usage into the metrics recorder, defensively.

    A metrics failure must never crash the cognition hot path, so a missing
    or malformed ``usage`` is a silent no-op. Cache reads go to the ``cached``
    bucket; fresh input plus cache-write tokens go to ``uncached`` — making
    cached/(cached+uncached) a direct input-token cache-hit ratio.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    try:
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_creation = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    except (TypeError, ValueError):
        return
    collector = MetricsCollector()
    collector.record_token_cost(model, cached=True, tokens=cache_read)
    collector.record_token_cost(model, cached=False, tokens=input_tokens + cache_creation)


# ── LLMClient ─────────────────────────────────────────────────────────────────

class LLMClient:
    MAX_TOKENS = 512

    def __init__(
        self,
        api_key: str,
        timeout: float = settings.ANTHROPIC_TIMEOUT_SECONDS,
        max_retries: int = settings.ANTHROPIC_MAX_RETRIES,
    ) -> None:
        # The SDK does exponential-backoff retries on 408/409/429/>=500 via
        # max_retries and enforces a per-request timeout — wire both from config
        # so a transient 429/529 degrades gracefully instead of a hard 500.
        self._client = AsyncAnthropic(
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
        )

    async def complete(
        self,
        message: str,
        vision: PerceptionFrame,
        conversation_history: list[ConversationTurn],
        working_memory: list[str],
        episodic_memory: list[str],
    ) -> CognitionResponse:
        tier: Tier = classify_tier(message)
        logger.debug("llm tier routing", tier=tier, message=message[:80])

        # ── Tier 0: local handler, no API call ─────────────────────────────
        if tier == 0:
            last_response = next(
                (t.content for t in reversed(conversation_history) if t.role == "assistant"),
                "",
            )
            local_reply = _handle_local(message, last_response)
            return CognitionResponse(
                symbolic_inference="local_handler",
                world_model_update=None,
                natural_language_response=local_reply,
            )

        # ── Tier 1 / 2: API call ────────────────────────────────────────────
        model = _MODEL_HAIKU if tier == 1 else _MODEL_SONNET
        soul_content, observation_content = build_system_parts(
            vision, message, working_memory, episodic_memory
        )

        # Anthropic prompt caching: put the stable SOUL.md prefix in its own
        # cache_control block so repeated calls reuse the cached KV and save ~90%
        # of system-prompt token cost (ephemeral cache TTL is 5 minutes). The
        # per-turn observation goes in a SEPARATE uncached block so the cache
        # breakpoint sits after the stable prefix and actually hits.
        system: list[dict] = []
        if soul_content:
            system.append(
                {
                    "type": "text",
                    "text": soul_content,
                    "cache_control": {"type": "ephemeral"},
                }
            )
        system.append({"type": "text", "text": observation_content})

        messages = []
        for turn in conversation_history[-6:]:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": message})

        start = time.time()
        response = await self._client.messages.create(
            model=model,
            max_tokens=self.MAX_TOKENS,
            system=system,  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
            extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
        )
        elapsed_ms = int((time.time() - start) * 1000)
        logger.debug("llm api call", tier=tier, model=model, elapsed_ms=elapsed_ms)

        _record_token_usage(model, response)

        first_block = response.content[0] if response.content else None
        text = getattr(first_block, "text", None)
        if text is None:
            logger.warning(
                "llm empty or non-text completion, falling back",
                tier=tier,
                model=model,
            )
            return CognitionResponse(
                symbolic_inference="empty completion",
                world_model_update=None,
                natural_language_response="",
            )

        raw = text.strip()
        result = self._parse_response(raw)
        return result

    def _parse_response(self, raw: str) -> CognitionResponse:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            logger.warning("llm response not JSON, falling back", raw=raw[:100])
            return CognitionResponse(
                symbolic_inference="state unclear",
                world_model_update=None,
                natural_language_response=raw,
            )

        try:
            data = json.loads(match.group())
            wmu = None
            if data.get("world_model_update"):
                raw_wmu = data["world_model_update"]
                triple = WorldModelTriple(
                    subject=raw_wmu["triple"]["subject"],
                    predicate=raw_wmu["triple"]["predicate"],
                    object=raw_wmu["triple"]["object"],
                )
                wmu = WorldModelUpdate(
                    triple=triple,
                    confidence=float(raw_wmu.get("confidence", 0.5)),
                    source=raw_wmu.get("source", "behavioral_inference"),
                )
            return CognitionResponse(
                symbolic_inference=data.get("symbolic_inference", ""),
                world_model_update=wmu,
                natural_language_response=data.get("natural_language_response", ""),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("failed to parse llm json", error=str(e))
            return CognitionResponse(
                symbolic_inference="parse error",
                world_model_update=None,
                natural_language_response=raw,
            )
