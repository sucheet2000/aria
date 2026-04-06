from __future__ import annotations

import json
import re
import time
from typing import Literal

import structlog
from anthropic import AsyncAnthropic

from app.cognition.prompt import build_system_prompt
from app.models.schemas import (
    SymbolicResponse,
    VisionContext,
    WorldModelTriple,
    WorldModelUpdate,
)

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


# ── LLMClient ─────────────────────────────────────────────────────────────────

class LLMClient:
    MAX_TOKENS = 512

    def __init__(self, api_key: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._last_response: str = ""

    async def complete(
        self,
        message: str,
        vision: VisionContext,
        conversation_history: list[dict],
        working_memory: list[str],
        episodic_memory: list[str],
    ) -> SymbolicResponse:
        tier: Tier = classify_tier(message)
        logger.debug("llm tier routing", tier=tier, message=message[:80])

        # ── Tier 0: local handler, no API call ─────────────────────────────
        if tier == 0:
            local_reply = _handle_local(message, self._last_response)
            return SymbolicResponse(
                symbolic_inference="local_handler",
                world_model_update=None,
                natural_language_response=local_reply,
            )

        # ── Tier 1 / 2: API call ────────────────────────────────────────────
        model = _MODEL_HAIKU if tier == 1 else _MODEL_SONNET
        system_content = build_system_prompt(
            vision, message, working_memory, episodic_memory
        )

        # Anthropic prompt caching: mark the static system prompt (SOUL.md content)
        # with cache_control so repeated calls reuse the cached KV and save ~90% of
        # system-prompt token cost. ephemeral cache TTL is 5 minutes.
        system: list[dict] = [
            {
                "type": "text",
                "text": system_content,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        messages = []
        for turn in conversation_history[-6:]:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": message})

        start = time.time()
        response = await self._client.messages.create(
            model=model,
            max_tokens=self.MAX_TOKENS,
            system=system,
            messages=messages,
            extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
        )
        elapsed_ms = int((time.time() - start) * 1000)
        logger.debug("llm api call", tier=tier, model=model, elapsed_ms=elapsed_ms)

        raw = response.content[0].text.strip()
        result = self._parse_response(raw)
        self._last_response = result.natural_language_response
        return result

    def _parse_response(self, raw: str) -> SymbolicResponse:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            logger.warning("llm response not JSON, falling back", raw=raw[:100])
            return SymbolicResponse(
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
            return SymbolicResponse(
                symbolic_inference=data.get("symbolic_inference", ""),
                world_model_update=wmu,
                natural_language_response=data.get("natural_language_response", ""),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("failed to parse llm json", error=str(e))
            return SymbolicResponse(
                symbolic_inference="parse error",
                world_model_update=None,
                natural_language_response=raw,
            )
