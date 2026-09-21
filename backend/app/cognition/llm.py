from __future__ import annotations

import json
import re
import time
from typing import Any, Literal
from urllib.parse import urlparse

import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, ConfigDict, ValidationError

from app.cognition.prompt import build_system_parts
from app.config import settings
from app.models.schemas import (
    CognitionResponse,
    ConversationTurn,
    PerceptionFrame,
    ResponseStatus,
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

# Keywords that push a query to Tier 2 (complex reasoning / Sonnet).
#
# Candidate utterances are casefolded before matching, so a rule carrying an
# uppercase letter could never fire — "should I" was dead for exactly that
# reason, and read as covered. Normalizing the rules at the point of definition
# keeps every rule reachable by construction rather than by review vigilance,
# and test_no_keyword_is_unreachable fails if one ever slips back in.
_TIER2_KEYWORDS = frozenset(
    kw.casefold()
    for kw in {"feel", "feeling", "emotion", "why", "explain", "remember",
               "memory", "complex", "analyze", "compare", "recommend",
               "advice", "should I", "help me", "reason", "think about",
               "understand"}
)

_TIER2_WORD_THRESHOLD = 15  # queries longer than this default to Tier 2

# Verbatim conversation-history window: the last N role-entries (~N/2 exchanges)
# replayed word-for-word into each API call. Lives in the uncached message region,
# so widening it does not affect the cached SOUL prefix.
_MAX_HISTORY_TURNS = 16

# Anthropic prompt caching (R4). The stable SOUL.md prefix carries the only
# cache breakpoint; the provider caches the whole prefix up to it and ignores
# the marker silently (no error, no write) when the prefix is shorter than the
# model's minimum. Minimums verified 2026-09-19 against
# platform.claude.com/docs/en/docs/build-with-claude/prompt-caching; the
# eligibility log below makes the live situation visible per model. Do not
# pad the prompt to cross a threshold. Note the provider hashes tools → system
# → messages, so a turn that attaches the web_fetch tool has a different
# (larger) prefix than a plain turn and would keep a separate cache entry.
_CACHE_MIN_PREFIX_TOKENS: dict[str, int] = {
    _MODEL_HAIKU: 4096,
    _MODEL_SONNET: 1024,
}
# Local estimate only. Measured 2026-09-19 with the provider's count_tokens:
# SOUL.md = 2,801 chars = 658 tokens (both models); chars/4 estimates 700.
_CHARS_PER_TOKEN_ESTIMATE = 4
_eligibility_logged: set[str] = set()

# ── Response safety (R5) ─────────────────────────────────────────────────────
# The provider's text is expected to be one JSON object matching the SOUL.md
# contract. Anything else is a typed failure and the user hears exactly one
# safe, plain sentence; the failed turn carries no inference for the Go ring
# and no fact for memory. The raw provider text is never spoken, returned or
# logged.
SAFE_FALLBACK_RESPONSE = "Sorry, I lost my train of thought for a moment. Could you say that again?"

# Provider stop reasons that mean the turn did not finish: max_tokens (output
# cap hit) and pause_turn (a server-tool turn still paused after the bounded
# continuations). ``refusal`` is its own status so a policy refusal is not
# miscounted as a parser bug. end_turn / stop_sequence / tool_use fall through
# to the parser. Verified against anthropic 0.85.0 ``StopReason``
# = (end_turn, max_tokens, stop_sequence, tool_use, pause_turn, refusal).
_INCOMPLETE_STOP_REASONS = frozenset({"max_tokens", "pause_turn"})
_REFUSAL_STOP_REASON = "refusal"


class CognitionDeadlineError(Exception):
    """The turn's total budget ran out before or between provider calls (R6).

    Deliberately NOT an ``LLMResponseError``: running out of time is not a
    malformed model response and must not become the R5 safe fallback. The
    route maps it to 504.
    """


def _now() -> float:
    """Monotonic clock, in its own function so tests can inject a fake one."""
    return time.monotonic()


def _attempt_timeout(deadline: float | None) -> float:
    """Seconds this provider attempt may take.

    The SDK applies its timeout per attempt and retries on top, so an attempt
    is additionally capped at whatever is left of the turn's budget. Retries
    and ``pause_turn`` continuations therefore drain one shared budget instead
    of each starting a fresh one.
    """
    cap = settings.ANTHROPIC_TIMEOUT_SECONDS
    if deadline is None:
        return cap
    remaining = deadline - _now()
    if remaining <= 0:
        raise CognitionDeadlineError("request budget exhausted")
    return min(cap, remaining)


class LLMResponseError(Exception):
    """A provider turn that must not be trusted; ``status`` classifies it."""

    status: ResponseStatus = "malformed"


class LLMResponseParseError(LLMResponseError):
    status: ResponseStatus = "malformed"


class LLMResponseTruncatedError(LLMResponseError):
    status: ResponseStatus = "truncated"


class LLMResponseEmptyError(LLMResponseError):
    status: ResponseStatus = "empty"


class LLMResponseSchemaError(LLMResponseError):
    status: ResponseStatus = "invalid_schema"


class LLMResponseRefusedError(LLMResponseError):
    """The provider declined the turn (``stop_reason == "refusal"``)."""

    status: ResponseStatus = "refused"


class _ModelTriple(BaseModel):
    model_config = ConfigDict(extra="ignore")
    subject: str
    predicate: str
    object: str


class _ModelWorldModelUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    triple: _ModelTriple
    confidence: float = 0.5
    source: str = "behavioral_inference"


class _ModelReply(BaseModel):
    """The structured reply contract as the model must emit it. Unknown keys
    are ignored (existing policy); ``natural_language_response`` is required
    and must be a string; ``symbolic_inference`` defaults to ""."""

    model_config = ConfigDict(extra="ignore")
    natural_language_response: str
    symbolic_inference: str | None = ""
    world_model_update: _ModelWorldModelUpdate | None = None


def _fallback_response(status: ResponseStatus) -> CognitionResponse:
    return CognitionResponse(
        symbolic_inference="",
        world_model_update=None,
        natural_language_response=SAFE_FALLBACK_RESPONSE,
        response_status=status,
    )


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


def _usage_fields(response: object) -> dict[str, int]:
    """Token counts from ``response.usage`` for structured logs (never content)."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    fields: dict[str, int] = {}
    for attr, key in (
        ("input_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
        ("cache_read_input_tokens", "cache_read_tokens"),
        ("cache_creation_input_tokens", "cache_creation_tokens"),
    ):
        try:
            fields[key] = int(getattr(usage, attr, 0) or 0)
        except (TypeError, ValueError):
            continue
    return fields


_ABSENT = object()


def cache_status(usage: object) -> str:
    """Classify a response's prompt-cache outcome from provider usage counters.

    ``"read"`` only when ``cache_read_input_tokens > 0`` (the actual hit
    signal); ``"created"`` when the cache was written but not read;
    ``"none"`` when both counters are present and zero (marker ignored, e.g.
    prefix below the model minimum); ``"unknown"`` when the fields are absent
    or malformed. Never inspects prompt content.
    """
    if usage is None:
        return "unknown"
    try:
        read: Any = getattr(usage, "cache_read_input_tokens", _ABSENT)
        created: Any = getattr(usage, "cache_creation_input_tokens", _ABSENT)
        if read is _ABSENT or created is _ABSENT:
            return "unknown"
        # The SDK types both counters Optional[int]; a null means "no cache
        # activity", the same as 0 (and the same as _usage_fields logs).
        read_n, created_n = int(read or 0), int(created or 0)
    except (TypeError, ValueError):
        return "unknown"
    if read_n > 0:
        return "read"
    if created_n > 0:
        return "created"
    return "none"


def _cache_eligibility(model: str, prefix_chars: int) -> dict[str, object]:
    """Whether the stable prefix can be cached at all for ``model``.

    ``eligible`` is ``None`` for a model whose minimum is not recorded; the
    token figure is a chars/4 estimate, labelled as such.
    """
    minimum = _CACHE_MIN_PREFIX_TOKENS.get(model)
    est = prefix_chars // _CHARS_PER_TOKEN_ESTIMATE
    return {
        "model": model,
        "stable_prefix_chars": prefix_chars,
        "stable_prefix_tokens_est": est,
        "min_cacheable_tokens": minimum,
        "eligible": (est >= minimum) if minimum is not None else None,
    }


def _log_cache_eligibility_once(model: str, prefix_chars: int) -> None:
    if model in _eligibility_logged:
        return
    _eligibility_logged.add(model)
    logger.info("prompt cache eligibility", **_cache_eligibility(model, prefix_chars))


def _url_host(url: str | None) -> str | None:
    """Host part of a user-pasted URL, for logs; never the full URL."""
    if not url:
        return None
    return urlparse(url).netloc or None


def _record_token_usage(model: str, response: object) -> None:
    """Record input-token usage into the metrics recorder, defensively.

    A metrics failure must never crash the cognition hot path, so a missing
    or malformed ``usage`` is a silent no-op. Cache reads go to the ``cached``
    bucket; fresh input plus cache-write tokens go to ``uncached`` — making
    cached/(cached+uncached) a direct input-token cache-hit ratio.
    """
    usage = getattr(response, "usage", None)
    collector = MetricsCollector()
    # Classified first so an absent/malformed usage still counts as "unknown".
    collector.record_prompt_cache(model, cache_status(usage))
    if usage is None:
        return
    try:
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_creation = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    except (TypeError, ValueError):
        return
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
        deadline: float | None = None,
    ) -> CognitionResponse:
        """``deadline`` is a monotonic instant (``time.monotonic()`` base) by
        which the whole turn must be done; every provider attempt is capped to
        the time still left before it (R6)."""
        tier: Tier = classify_tier(message)
        logger.debug("llm tier routing", tier=tier, message_chars=len(message))

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

        # Prompt caching (R4): the stable SOUL.md prefix is its own block and
        # carries the only cache breakpoint; the per-turn observation (vision,
        # transcript, working ring, retrieved facts) is a SEPARATE block after
        # it, so nothing owner- or turn-specific can enter the cached prefix.
        # Whether the provider actually caches depends on the prefix meeting
        # the model's minimum (see _CACHE_MIN_PREFIX_TOKENS); the marker is
        # ignored harmlessly below it and "prompt cache eligibility" reports
        # which case applies. The 5-minute ephemeral entry is refreshed by
        # every read.
        system: list[dict] = []
        if soul_content:
            system.append(
                {
                    "type": "text",
                    "text": soul_content,
                    "cache_control": {"type": "ephemeral"},
                }
            )
            _log_cache_eligibility_once(model, len(soul_content))
        system.append({"type": "text", "text": observation_content})

        messages = []
        for turn in conversation_history[-_MAX_HISTORY_TURNS:]:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": message})

        # Attach the native web_fetch server tool ONLY when it is enabled, an
        # allow-list is configured, AND the message actually contains a URL.
        # When any of those is false the call is byte-for-byte as today (no
        # `tools` kwarg), so the feature is inert by default.
        # Prompt caching is generally available; no beta header is needed.
        create_kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": self.MAX_TOKENS,
            "system": system,
            "messages": messages,
            # R6: bounded by whatever is left of this turn's budget.
            "timeout": _attempt_timeout(deadline),
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
            # R6: a continuation spends what is LEFT, it never resets the budget.
            create_kwargs["timeout"] = _attempt_timeout(deadline)
            response = await self._client.messages.create(**create_kwargs)
            _record_token_usage(model, response)
        elapsed_ms = int((time.time() - start) * 1000)
        # INFO so per-turn latency and token usage survive the production floor.
        logger.info(
            "llm api call",
            tier=tier,
            model=model,
            elapsed_ms=elapsed_ms,
            continuations=continuations,
            stop_reason=getattr(response, "stop_reason", None),
            cache_status=cache_status(getattr(response, "usage", None)),
            **_usage_fields(response),
        )

        text, used_web_fetch, fetch_error = _extract_text_and_fetch(response)
        stop_reason = getattr(response, "stop_reason", None)

        if used_web_fetch:
            # S2: the URL is user-supplied content (paths and query strings can
            # carry identifiers); log only its host. Fetched page content is
            # never logged.
            logger.info(
                "web_fetch turn",
                tier=tier,
                model=model,
                url_host=_url_host(_first_url(message)),
                outcome=fetch_error or "ok",
            )

        # R5: classify before trusting any content. Truncation is decided from
        # the provider's stop_reason first, so parseable-looking partial text
        # is never accepted; then empty; then parse + schema.
        try:
            if stop_reason in _INCOMPLETE_STOP_REASONS:
                raise LLMResponseTruncatedError(stop_reason)
            if stop_reason == _REFUSAL_STOP_REASON:
                raise LLMResponseRefusedError(stop_reason)
            if text is None or not text.strip():
                raise LLMResponseEmptyError()
            result = self._parse_response(text.strip())
        except LLMResponseError as e:
            cause = e.__cause__
            # S2: the type of the underlying error only — never its message
            # (a pydantic ValidationError message embeds the input values).
            logger.warning(
                "llm response rejected",
                tier=tier,
                model=model,
                stop_reason=stop_reason,
                response_status=e.status,
                error_type=type(cause).__name__ if cause is not None else type(e).__name__,
                raw_chars=len(text or ""),
            )
            MetricsCollector().record_llm_response(model, e.status)
            result = _fallback_response(e.status)
        else:
            logger.info(
                "llm response accepted",
                tier=tier,
                model=model,
                stop_reason=stop_reason,
                response_status="valid",
                has_world_model_update=result.world_model_update is not None,
            )
            MetricsCollector().record_llm_response(model, "valid")
        result.used_web_fetch = used_web_fetch
        return result

    def _parse_response(self, raw: str) -> CognitionResponse:
        """Parse the model's text into the structured contract.

        Raises ``LLMResponseParseError`` when no JSON object can be decoded and
        ``LLMResponseSchemaError`` when the object does not satisfy the
        contract. Never returns the raw text.
        """
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            raise LLMResponseParseError("no JSON object in completion")
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError as e:
            raise LLMResponseParseError("completion is not valid JSON") from e
        if not isinstance(data, dict):
            raise LLMResponseSchemaError("completion JSON is not an object")
        # Existing policy: a null/empty/false world_model_update means "no fact".
        if not data.get("world_model_update"):
            data["world_model_update"] = None
        try:
            reply = _ModelReply.model_validate(data)
        except ValidationError as e:
            raise LLMResponseSchemaError("completion does not match the reply contract") from e
        wmu = None
        if reply.world_model_update is not None:
            wmu = WorldModelUpdate(
                triple=WorldModelTriple(
                    subject=reply.world_model_update.triple.subject,
                    predicate=reply.world_model_update.triple.predicate,
                    object=reply.world_model_update.triple.object,
                ),
                confidence=reply.world_model_update.confidence,
                source=reply.world_model_update.source,
            )
        return CognitionResponse(
            symbolic_inference=reply.symbolic_inference or "",
            world_model_update=wmu,
            natural_language_response=reply.natural_language_response,
        )
