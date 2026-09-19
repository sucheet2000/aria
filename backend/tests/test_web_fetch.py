"""Single-page-reader (native Anthropic web_fetch) tests.

Guiding principle: SHIP INERT BY DEFAULT. With the feature disabled (the
default), cognition behaves EXACTLY as today — no `tools` kwarg, identical
parsing. The tool is attached only when enabled AND an allow-list is set AND
the incoming message contains an http(s) URL. Fetch turns suppress the
fact-write so a hostile page cannot poison owner memory.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import app.cognition.llm as llm_mod
from app.cognition.llm import LLMClient, _first_url
from app.models.schemas import (
    CognitionResponse,
    PerceptionFrame,
    WorldModelTriple,
    WorldModelUpdate,
)

_PAYLOAD = '{"symbolic_inference": "ok", "natural_language_response": "hi"}'


# ── mock block / response builders ────────────────────────────────────────────


def _text_block(text: str) -> MagicMock:
    b = MagicMock()
    b.type = "text"
    b.text = text
    return b


def _server_tool_use_block() -> MagicMock:
    b = MagicMock()
    b.type = "server_tool_use"
    return b


def _web_fetch_result_block(error_code: str | None = None) -> MagicMock:
    b = MagicMock()
    b.type = "web_fetch_tool_result"
    inner = MagicMock()
    inner.error_code = error_code  # None => success
    b.content = inner
    return b


def _response(blocks: list[MagicMock], *, stop_reason: str = "end_turn") -> MagicMock:
    r = MagicMock()
    r.content = blocks
    r.stop_reason = stop_reason
    usage = MagicMock()
    usage.cache_read_input_tokens = 0
    usage.cache_creation_input_tokens = 0
    usage.input_tokens = 50
    r.usage = usage
    return r


def _enable_web_fetch(monkeypatch: pytest.MonkeyPatch, domains: list[str]) -> None:
    monkeypatch.setattr(llm_mod.settings, "WEB_FETCH_ENABLED", True)
    monkeypatch.setattr(llm_mod.settings, "WEB_FETCH_ALLOWED_DOMAINS", domains)


async def _complete(client: LLMClient, message: str) -> CognitionResponse:
    return await client.complete(
        message=message,
        vision=PerceptionFrame(),
        conversation_history=[],
        working_memory=[],
        episodic_memory=[],
    )


# ── _first_url ────────────────────────────────────────────────────────────────


class TestUrlDetection:
    def test_detects_https_url(self) -> None:
        assert _first_url("read https://example.com/page please") == "https://example.com/page"

    def test_detects_http_url(self) -> None:
        assert _first_url("http://docs.python.org") == "http://docs.python.org"

    def test_no_url_returns_none(self) -> None:
        assert _first_url("just a normal question") is None

    def test_bare_domain_is_not_a_url(self) -> None:
        assert _first_url("go to example.com") is None


# ── (a) regression: INERT by default ──────────────────────────────────────────


class TestInertByDefault:
    @pytest.mark.asyncio
    async def test_disabled_default_sends_no_tools_kwarg_even_with_url(self) -> None:
        """Default (feature OFF): a URL in the message must NOT attach tools."""
        client = LLMClient(api_key="test-key")
        mock_create = AsyncMock(return_value=_response([_text_block(_PAYLOAD)]))
        client._client.messages.create = mock_create

        result = await _complete(client, "summarize https://example.com for me")

        assert "tools" not in mock_create.call_args.kwargs
        assert result.symbolic_inference == "ok"
        assert result.natural_language_response == "hi"
        assert result.used_web_fetch is False

    @pytest.mark.asyncio
    async def test_disabled_default_parse_is_byte_identical(self) -> None:
        """A normal single-text-block response parses exactly as today."""
        client = LLMClient(api_key="test-key")
        payload = (
            '{"symbolic_inference": "user is calm", '
            '"natural_language_response": "Hi there."}'
        )
        client._client.messages.create = AsyncMock(return_value=_response([_text_block(payload)]))

        result = await _complete(client, "hello")

        assert result.symbolic_inference == "user is calm"
        assert result.natural_language_response == "Hi there."
        assert result.used_web_fetch is False


# ── (b) tool attached only when enabled + allowlist + URL ─────────────────────


class TestToolAttachment:
    @pytest.mark.asyncio
    async def test_tool_attached_when_enabled_allowlist_and_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_web_fetch(monkeypatch, ["example.com"])
        client = LLMClient(api_key="test-key")
        mock_create = AsyncMock(return_value=_response([_text_block(_PAYLOAD)]))
        client._client.messages.create = mock_create

        await _complete(client, "read https://example.com/a")

        tools = mock_create.call_args.kwargs["tools"]
        assert tools == [
            {
                "type": "web_fetch_20250910",
                "name": "web_fetch",
                "max_uses": 2,
                "allowed_domains": ["example.com"],
                "max_content_tokens": 10000,
            }
        ]

    @pytest.mark.asyncio
    async def test_no_tool_when_enabled_and_allowlist_but_no_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_web_fetch(monkeypatch, ["example.com"])
        client = LLMClient(api_key="test-key")
        mock_create = AsyncMock(return_value=_response([_text_block(_PAYLOAD)]))
        client._client.messages.create = mock_create

        await _complete(client, "what is the capital of France")

        assert "tools" not in mock_create.call_args.kwargs

    @pytest.mark.asyncio
    async def test_no_tool_when_allowlist_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_web_fetch(monkeypatch, [])
        client = LLMClient(api_key="test-key")
        mock_create = AsyncMock(return_value=_response([_text_block(_PAYLOAD)]))
        client._client.messages.create = mock_create

        await _complete(client, "read https://example.com/a")

        assert "tools" not in mock_create.call_args.kwargs

    @pytest.mark.asyncio
    async def test_no_tool_when_disabled_but_allowlist_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(llm_mod.settings, "WEB_FETCH_ENABLED", False)
        monkeypatch.setattr(llm_mod.settings, "WEB_FETCH_ALLOWED_DOMAINS", ["example.com"])
        client = LLMClient(api_key="test-key")
        mock_create = AsyncMock(return_value=_response([_text_block(_PAYLOAD)]))
        client._client.messages.create = mock_create

        await _complete(client, "read https://example.com/a")

        assert "tools" not in mock_create.call_args.kwargs

    @pytest.mark.asyncio
    async def test_cached_soul_prefix_untouched_when_tool_attached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Attaching the tool must not change the cached SOUL system block."""
        import app.cognition.prompt as prompt_mod
        from app.cognition.prompt import _load_soul

        prompt_mod._soul_cache = None
        _enable_web_fetch(monkeypatch, ["example.com"])
        client = LLMClient(api_key="test-key")
        mock_create = AsyncMock(return_value=_response([_text_block(_PAYLOAD)]))
        client._client.messages.create = mock_create

        await _complete(client, "read https://example.com/a")

        system = mock_create.call_args.kwargs["system"]
        assert len(system) == 2
        assert system[0]["text"] == _load_soul()
        assert system[0]["cache_control"] == {"type": "ephemeral"}


# ── (c) multi-block response → LAST text block parsed ─────────────────────────


class TestMultiBlockParsing:
    @pytest.mark.asyncio
    async def test_final_text_block_is_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_web_fetch(monkeypatch, ["example.com"])
        client = LLMClient(api_key="test-key")
        final = (
            '{"symbolic_inference": "grounded", '
            '"natural_language_response": "The page says X."}'
        )
        blocks = [
            _text_block("Let me look that up."),
            _server_tool_use_block(),
            _web_fetch_result_block(),
            _text_block(final),
        ]
        client._client.messages.create = AsyncMock(return_value=_response(blocks))

        result = await _complete(client, "read https://example.com/a")

        assert result.symbolic_inference == "grounded"
        assert result.natural_language_response == "The page says X."
        assert result.used_web_fetch is True


# ── (d) pause_turn continuation loop is bounded ───────────────────────────────


class TestPauseTurnLoop:
    @pytest.mark.asyncio
    async def test_pause_turn_loop_is_bounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An endless pause_turn must terminate after a bounded number of calls."""
        _enable_web_fetch(monkeypatch, ["example.com"])
        client = LLMClient(api_key="test-key")
        pause = _response([_text_block(_PAYLOAD)], stop_reason="pause_turn")
        mock_create = AsyncMock(return_value=pause)
        client._client.messages.create = mock_create

        result = await _complete(client, "read https://example.com/a")

        assert mock_create.call_count == llm_mod._MAX_TURN_CONTINUATIONS + 1
        # R5: a turn still paused after the bounded continuations is incomplete;
        # its interim text is not spoken.
        assert result.response_status == "truncated"
        assert result.natural_language_response == llm_mod.SAFE_FALLBACK_RESPONSE

    @pytest.mark.asyncio
    async def test_pause_turn_resolves_and_parses_final(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_web_fetch(monkeypatch, ["example.com"])
        client = LLMClient(api_key="test-key")
        final = (
            '{"symbolic_inference": "done", "natural_language_response": "resolved"}'
        )
        pause = _response([_text_block("thinking")], stop_reason="pause_turn")
        done = _response(
            [_server_tool_use_block(), _web_fetch_result_block(), _text_block(final)]
        )
        mock_create = AsyncMock(side_effect=[pause, done])
        client._client.messages.create = mock_create

        result = await _complete(client, "read https://example.com/a")

        assert mock_create.call_count == 2
        assert result.natural_language_response == "resolved"
        assert result.used_web_fetch is True


# ── (e) fetch-error block → graceful normal answer ────────────────────────────


class TestFetchErrorDegradation:
    @pytest.mark.asyncio
    async def test_error_block_degrades_to_normal_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_web_fetch(monkeypatch, ["example.com"])
        client = LLMClient(api_key="test-key")
        answer = (
            '{"symbolic_inference": "no page", '
            '"natural_language_response": "I could not read that page."}'
        )
        blocks = [
            _server_tool_use_block(),
            _web_fetch_result_block(error_code="url_not_allowed"),
            _text_block(answer),
        ]
        client._client.messages.create = AsyncMock(return_value=_response(blocks))

        result = await _complete(client, "read https://evil.example/a")

        assert result.natural_language_response == "I could not read that page."
        assert result.used_web_fetch is True

    @pytest.mark.asyncio
    async def test_error_block_only_no_text_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fetch error with no answer text degrades to the empty-completion fallback."""
        _enable_web_fetch(monkeypatch, ["example.com"])
        client = LLMClient(api_key="test-key")
        blocks = [
            _server_tool_use_block(),
            _web_fetch_result_block(error_code="url_not_accessible"),
        ]
        client._client.messages.create = AsyncMock(return_value=_response(blocks))

        result = await _complete(client, "read https://example.com/a")

        assert result.response_status == "empty"
        assert result.symbolic_inference == ""
        assert result.used_web_fetch is True


# ── (f) fact-write suppression on fetch turns (route level) ────────────────────


def _stub_memory() -> MagicMock:
    mem = MagicMock()
    mem.loaded = True
    mem.store_triple = AsyncMock()
    mem.query_relevant = AsyncMock(return_value=[])
    return mem


def _stub_bridge() -> MagicMock:
    return MagicMock()


def _wmu() -> WorldModelUpdate:
    return WorldModelUpdate(
        triple=WorldModelTriple(subject="user", predicate="likes", object="evil"),
        confidence=0.9,
        source="behavioral_inference",
    )


def _run_cognition(used_web_fetch: bool) -> MagicMock:
    from app.api.cognition_route import get_bridge, get_client, get_memory
    from app.main import app

    stub_llm = MagicMock()
    stub_llm.complete = AsyncMock(
        return_value=CognitionResponse(
            symbolic_inference="x",
            world_model_update=_wmu(),
            natural_language_response="ok",
            used_web_fetch=used_web_fetch,
        )
    )
    mem = _stub_memory()

    app.dependency_overrides[get_client] = lambda: stub_llm
    app.dependency_overrides[get_memory] = lambda: mem
    app.dependency_overrides[get_bridge] = lambda: _stub_bridge()
    try:
        resp = TestClient(app).post(
            "/api/cognition", json={"message": "read https://example.com"}
        )
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.clear()
    return mem


class TestFactWriteSuppression:
    def test_fact_write_suppressed_on_fetch_turn(self) -> None:
        mem = _run_cognition(used_web_fetch=True)
        mem.store_triple.assert_not_called()

    def test_fact_write_persists_on_normal_turn(self) -> None:
        mem = _run_cognition(used_web_fetch=False)
        mem.store_triple.assert_awaited_once()


# ── (g) malformed envelope → graceful fallback, never a 500 ───────────────────


class TestMalformedEnvelopeDegrades:
    """A hostile/garbled response envelope must degrade to the safe raw-text
    fallback, not raise. Reachable once web_fetch is enabled (attacker-influenced
    page content), so we close it as defense-in-depth."""

    def test_non_numeric_confidence_degrades(self) -> None:
        client = LLMClient(api_key="test-key")
        raw = json.dumps(
            {
                "symbolic_inference": "grounded",
                "natural_language_response": "The page says X.",
                "world_model_update": {
                    "triple": {"subject": "user", "predicate": "likes", "object": "cats"},
                    "confidence": "very high",
                },
            }
        )

        # R5: a malformed fact is a schema failure, never spoken raw.
        with pytest.raises(llm_mod.LLMResponseSchemaError):
            client._parse_response(raw)

    def test_non_dict_triple_degrades(self) -> None:
        client = LLMClient(api_key="test-key")
        raw = json.dumps(
            {
                "symbolic_inference": "grounded",
                "natural_language_response": "The page says X.",
                "world_model_update": {
                    "triple": "not-a-dict",
                    "confidence": 0.9,
                },
            }
        )

        with pytest.raises(llm_mod.LLMResponseSchemaError):
            client._parse_response(raw)


# ── config: INERT-by-default + comma-separated env parsing ────────────────────


class TestWebFetchConfig:
    def test_defaults_are_inert(self) -> None:
        from app.config import settings

        assert settings.WEB_FETCH_ENABLED is False
        assert settings.WEB_FETCH_ALLOWED_DOMAINS == []
        assert settings.WEB_FETCH_MAX_USES == 2
        assert settings.WEB_FETCH_MAX_CONTENT_TOKENS == 10000

    def test_allowed_domains_parses_comma_separated_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.config import Settings

        monkeypatch.setenv("WEB_FETCH_ALLOWED_DOMAINS", "example.com, docs.python.org ")
        s = Settings(_env_file=None)
        assert s.WEB_FETCH_ALLOWED_DOMAINS == ["example.com", "docs.python.org"]
