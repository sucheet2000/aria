from __future__ import annotations

import json
import re
import time
from typing import Any, Literal

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

# Verbatim conversation-history window: the last N role-entries (~N/2 exchanges)
# replayed word-for-word into each API call. Lives in the uncached message region,
# so widening it does not affect the cached SOUL prefix.
_MAX_HISTORY_TURNS = 16

# Native web_fetch server tool (GA, no beta header). Cap on how many times a
# paused turn may be resumed so a stuck pause_turn can never loop unboundedly.
_WEB_FETCH_TOOL_TYPE = "web_fetch_20250910"
_MAX_TURN_CONTINUATIONS = 3
_URL_RE = re.compile(r"https?://[^\s<>\"'\]\)]+", re.IGNORECASE)


def _first_url(text: str) -> str | None:
    """Return the first http(s) URL in ``text``, or None (bare domains ignored)."""
    match = _URL_RE.search(text)
    return match.group(0) if match else None


def _web_fetch_error_code(block: object) -> str | None:
    """Extract an Anthropic web_fetch error code from a result block, if present.

    A failed fetch is returned as a ``web_fetch_tool_result`` block whose inner
    content carries an ``error_code`` (e.g. ``url_not_allowed``); a successful
    fetch carries the fetched document instead.
    """
    inner = getattr(block, "content", None)
    if inner is None:
        return None
    if isinstance(inner, dict):
        code = inner.get("error_code")
    else:
        code = getattr(inner, "error_code", None)
    return code if isinstance(code, str) else None


def _extract_text_and_fetch(response: object) -> tuple[str | None, bool, str | None]:
    """Collapse a (possibly multi-block) response into cognition inputs.

    Iterates ``response.content`` and returns
    ``(last_text, used_web_fetch, fetch_error_code)``:

    - ``last_text`` — the LAST text block's text (the model's final answer),
      or None if there is no text block. For the no-tool path this is a single
      text block, so behaviour is identical to reading ``content[0]``.
    - ``used_web_fetch`` — True if a ``server_tool_use`` / ``web_fetch_tool_result``
      block is present, i.e. a fetch actually ran on this turn.
    - ``fetch_error_code`` — the error code of a failed fetch, else None.
    """
    content = getattr(response, "content", None) or []
    last_text: str | None = None
    used_web_fetch = False
    fetch_error: str | None = None
    for block in content:
        btype = getattr(block, "type", None)
        if btype == "server_tool_use":
            used_web_fetch = True
            continue
        if btype == "web_fetch_tool_result":
            used_web_fetch = True
            err = _web_fetch_error_code(block)
            if err is not None:
                fetch_error = err
            continue
        text = getattr(block, "text", None)
        if isinstance(text, str):
            last_text = text
    return last_text, used_web_fetch, fetch_error


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
        for turn in conversation_history[-_MAX_HISTORY_TURNS:]:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": message})

        # Attach the native web_fetch server tool ONLY when it is enabled, an
        # allow-list is configured, AND the message actually contains a URL.
        # When any of those is false the call is byte-for-byte as today (no
        # `tools` kwarg), so the feature is inert by default.
        create_kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": self.MAX_TOKENS,
            "system": system,
            "messages": messages,
            "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"},
        }
        if (
            settings.WEB_FETCH_ENABLED
            and settings.WEB_FETCH_ALLOWED_DOMAINS
            and _first_url(message) is not None
        ):
            create_kwargs["tools"] = [
                {
                    "type": _WEB_FETCH_TOOL_TYPE,
                    "name": "web_fetch",
                    "max_uses": settings.WEB_FETCH_MAX_USES,
                    "allowed_domains": list(settings.WEB_FETCH_ALLOWED_DOMAINS),
                    "max_content_tokens": settings.WEB_FETCH_MAX_CONTENT_TOKENS,
                }
            ]

        start = time.time()
        response = await self._client.messages.create(**create_kwargs)
        _record_token_usage(model, response)
        # A server-tool turn may pause; resume it a bounded number of times by
        # feeding the paused content back, so a stuck pause_turn cannot hang.
        continuations = 0
        while (
            getattr(response, "stop_reason", None) == "pause_turn"
            and continuations < _MAX_TURN_CONTINUATIONS
        ):
            continuations += 1
            create_kwargs["messages"] = [
                *create_kwargs["messages"],
                {"role": "assistant", "content": response.content},
            ]
            response = await self._client.messages.create(**create_kwargs)
            _record_token_usage(model, response)
        elapsed_ms = int((time.time() - start) * 1000)
        logger.debug("llm api call", tier=tier, model=model, elapsed_ms=elapsed_ms)

        text, used_web_fetch, fetch_error = _extract_text_and_fetch(response)

        if used_web_fetch:
            # URL is owner-supplied and safe to log; fetched page content is not.
            logger.info(
                "web_fetch turn",
                tier=tier,
                model=model,
                url=_first_url(message),
                outcome=fetch_error or "ok",
            )

        if text is None:
            logger.warning(
                "llm empty or non-text completion, falling back",
                tier=tier,
                model=model,
            )
            result = CognitionResponse(
                symbolic_inference="empty completion",
                world_model_update=None,
                natural_language_response="",
            )
        else:
            result = self._parse_response(text.strip())
        result.used_web_fetch = used_web_fetch
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
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.warning("failed to parse llm json", error=str(e))
            return CognitionResponse(
                symbolic_inference="parse error",
                world_model_update=None,
                natural_language_response=raw,
            )
