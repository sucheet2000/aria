"""S2 — production logs must never carry raw user content or stored facts.

Two independent defenses are tested here:
  1. production logging filters DEBUG (and below) at the logger, and
  2. every log statement on the memory / cognition / audio / TTS paths is
     content-safe even when DEBUG is captured, so a future debug toggle cannot
     leak user data.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
from collections.abc import Iterator
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
import structlog
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from app.cognition.llm import LLMClient
from app.cognition.memory import MemoryStore
from app.models.schemas import CognitionResponse, PerceptionFrame
from app.observability.logging import configure_logging

SENSITIVE_FACT = "SENSITIVE_FACT_7f16e091"
SENSITIVE_QUERY = "SENSITIVE_QUERY_abc123"
SENSITIVE_RESULT = "SENSITIVE_RESULT_def456"
PRIVATE_USER_MESSAGE = "PRIVATE_USER_MESSAGE_8d91"
PRIVATE_MODEL_OUTPUT = "PRIVATE_MODEL_OUTPUT_61ac"
PRIVATE_TRANSCRIPT = "PRIVATE_TRANSCRIPT_f309"
PRIVATE_MEMORY = "PRIVATE_MEMORY_Y"
PRIVATE_HISTORY = "PRIVATE_TRANSCRIPT_Z"
PRIVATE_TTS_TEXT = "PRIVATE_TTS_TEXT_9c4e"


@pytest.fixture(autouse=True)
def _restore_structlog() -> Iterator[None]:
    saved = structlog.get_config()
    yield
    structlog.configure(**saved)


@contextlib.contextmanager
def capture_all_levels() -> Iterator[list[dict]]:
    """Capture every structlog event, DEBUG included, regardless of the
    production level filter — so a content leak in a debug statement fails
    the test even though production would currently drop it."""
    structlog.configure(wrapper_class=structlog.BoundLogger)
    with capture_logs() as logs:
        # Self-check: if this helper ever stops capturing DEBUG (e.g. the
        # wrapper_class line above is removed), every assertion below would
        # silently pass. Prove the probe is captured, then drop it.
        structlog.get_logger().debug("capture_all_levels_probe")
        assert logs and logs[-1]["event"] == "capture_all_levels_probe"
        logs.pop()
        yield logs


def _rendered(logs: list[dict]) -> str:
    return "\n".join(repr(e) for e in logs)


def _events(logs: list[dict], name: str) -> list[dict]:
    return [e for e in logs if e.get("event") == name]


# ── Test 1: production configuration filters DEBUG ───────────────────────────


def test_production_logging_filters_debug(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("production")
    log = structlog.get_logger()
    log.debug("debug_event_marker_q1")
    log.info("info_event_marker_q2")
    log.warning("warning_event_marker_q3")
    out = capsys.readouterr().out
    assert "debug_event_marker_q1" not in out
    assert "info_event_marker_q2" in out
    assert "warning_event_marker_q3" in out
    for line in out.strip().splitlines():
        json.loads(line)  # still structured JSON on the prod path (OBS-1)


def test_local_logging_allows_debug(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("local")
    structlog.get_logger().debug("debug_event_marker_local")
    assert "debug_event_marker_local" in capsys.readouterr().out


# ── Test 2: stored fact never logged ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_stored_fact_never_appears_in_logs(tmp_path) -> None:
    store = MemoryStore(persist_dir=str(tmp_path))
    store.load()
    with capture_all_levels() as logs:
        await store.store_triple(
            subject="user", predicate="secret_is", obj=SENSITIVE_FACT,
            confidence=0.9, source="explicit_statement", owner="o1",
        )
    assert SENSITIVE_FACT not in _rendered(logs)
    facts = await store.get_profile_facts(owner="o1")
    assert any(SENSITIVE_FACT in f for f in facts), "store must still succeed"
    stored = _events(logs, "memory stored")
    assert stored, "operational log for the store must remain"
    assert stored[0].get("collection") == "aria_profile"
    assert stored[0].get("chars", 0) > 0


# ── Test 3: memory query never logs query text or results ────────────────────


@pytest.mark.asyncio
async def test_memory_query_never_logs_query_or_results(tmp_path) -> None:
    store = MemoryStore(persist_dir=str(tmp_path))
    store.load()
    await store.store_triple(
        subject="user", predicate="likes", obj=SENSITIVE_RESULT,
        confidence=0.9, source="explicit_statement", owner="o1",
    )
    with capture_all_levels() as logs:
        results = await store.query_relevant(SENSITIVE_QUERY, owner="o1", n_results=5)
    rendered = _rendered(logs)
    assert SENSITIVE_QUERY not in rendered
    assert SENSITIVE_RESULT not in rendered
    assert any(SENSITIVE_RESULT in r for r in results), "query must still return the fact"
    done = _events(logs, "memory query completed")
    assert done, "operational log for the query must remain"
    assert done[0].get("results") == 1
    assert "latency_ms" in done[0]


# ── Tests 4/5: user message and model output never in LLM logs ───────────────


def _fake_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=42, output_tokens=7,
            cache_read_input_tokens=0, cache_creation_input_tokens=0,
        ),
    )


def _llm_with(text: str) -> LLMClient:
    client = LLMClient(api_key="test-key")
    client._client.messages.create = AsyncMock(return_value=_fake_response(text))
    return client


@pytest.mark.asyncio
async def test_user_message_never_appears_in_llm_logs() -> None:
    client = _llm_with('{"symbolic_inference": "calm", "natural_language_response": "ok"}')
    message = f"{PRIVATE_USER_MESSAGE} please explain why the sky is blue"
    with capture_all_levels() as logs:
        await client.complete(
            message=message,
            vision=PerceptionFrame(),
            conversation_history=[],
            working_memory=[],
            episodic_memory=[PRIVATE_MEMORY],
        )
    rendered = _rendered(logs)
    assert PRIVATE_USER_MESSAGE not in rendered
    assert PRIVATE_MEMORY not in rendered
    call = _events(logs, "llm api call")
    assert call, "operational log for the API call must remain"
    assert call[0].get("model")
    assert "elapsed_ms" in call[0]
    assert call[0].get("input_tokens") == 42
    assert call[0].get("output_tokens") == 7
    assert call[0].get("stop_reason") == "end_turn"


@pytest.mark.asyncio
async def test_model_response_never_appears_in_logs() -> None:
    # Non-JSON completion exercises the "not JSON" warning path.
    client = _llm_with(f"{PRIVATE_MODEL_OUTPUT} is what I think")
    with capture_all_levels() as logs:
        result = await client.complete(
            message="please explain why", vision=PerceptionFrame(),
            conversation_history=[], working_memory=[], episodic_memory=[],
        )
    assert PRIVATE_MODEL_OUTPUT in result.natural_language_response
    assert PRIVATE_MODEL_OUTPUT not in _rendered(logs)

    # A well-formed JSON completion must not be logged either.
    client = _llm_with(
        f'{{"symbolic_inference": "x", "natural_language_response": "{PRIVATE_MODEL_OUTPUT}"}}'
    )
    with capture_all_levels() as logs:
        await client.complete(
            message="please explain why", vision=PerceptionFrame(),
            conversation_history=[], working_memory=[], episodic_memory=[],
        )
    assert PRIVATE_MODEL_OUTPUT not in _rendered(logs)


# ── Test 6: transcript never logged ──────────────────────────────────────────


def test_transcript_is_not_logged(capsys: pytest.CaptureFixture[str]) -> None:
    from app.pipeline import audio_worker as aw
    from app.pipeline.vad import VADProcessor

    vad = VADProcessor()
    vad._vad = mock.Mock()
    n_speech = 10
    n_silence = (vad.MAX_SILENCE_MS // VADProcessor.CHUNK_MS) + 1
    vad._vad.is_speech.side_effect = [True] * n_speech + [False] * n_silence
    speech = np.full(VADProcessor.CHUNK_SAMPLES, 3000, dtype="<i2").tobytes()
    silence = np.zeros(VADProcessor.CHUNK_SAMPLES, dtype="<i2").tobytes()
    pcm = speech * n_speech + silence * n_silence

    transcriber = mock.Mock()
    transcriber.transcribe.return_value = (f"hey aria {PRIVATE_TRANSCRIPT}", 0.9)
    denoiser = mock.Mock()
    denoiser.enabled = False
    args = argparse.Namespace(denoise=False, max_utterance_ms=8000)

    transport = io.StringIO()
    with capture_all_levels() as logs, contextlib.redirect_stdout(transport):
        aw.process_audio_stream(aw.read_pcm_chunks(io.BytesIO(pcm)), vad, transcriber, denoiser, args)

    # stdout is the transcript transport to Go — it must carry the text …
    assert PRIVATE_TRANSCRIPT in transport.getvalue()
    # … but no log record and nothing on stderr may.
    assert PRIVATE_TRANSCRIPT not in _rendered(logs)
    assert PRIVATE_TRANSCRIPT not in capsys.readouterr().err
    done = _events(logs, "transcription complete")
    assert done and done[0].get("chars", 0) > 0 and "duration_ms" in done[0]


# ── Test 8: provider failure is logged with classification, no content ───────


def _override_route(app, llm, memory, tmp_path):
    from app.api.cognition_route import get_bridge, get_client, get_memory
    from app.spatial.anchor_registry import AnchorRegistry
    from app.spatial.gesture_anchor_bridge import GestureAnchorBridge

    app.dependency_overrides[get_client] = lambda: llm
    app.dependency_overrides[get_memory] = lambda: memory
    app.dependency_overrides[get_bridge] = lambda: GestureAnchorBridge(
        AnchorRegistry(db_path=tmp_path / "a.db")
    )


def test_provider_failure_logged_without_user_content(tmp_path) -> None:
    from app.main import app

    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=RuntimeError("provider down"))
    memory = MagicMock()
    memory.loaded = True
    memory.store_triple = AsyncMock()
    memory.query_relevant = AsyncMock(return_value=[])
    _override_route(app, llm, memory, tmp_path)
    try:
        with capture_all_levels() as logs:
            resp = TestClient(app, raise_server_exceptions=False).post(
                "/api/cognition",
                json={"message": f"{PRIVATE_USER_MESSAGE} tell me a secret"},
                headers={"X-Request-ID": "s2-err-1"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 500
    errors = [e for e in logs if e.get("log_level") == "error"]
    assert errors, "the failure must be logged"
    assert any(e.get("error_type") == "RuntimeError" for e in errors)
    assert any(e.get("request_id") == "s2-err-1" for e in errors)
    assert PRIVATE_USER_MESSAGE not in _rendered(logs)


# ── Optional: end-to-end sentinel sweep through the cognition route ──────────


def test_cognition_route_logs_carry_no_sentinels(tmp_path) -> None:
    from app.main import app

    llm = MagicMock()
    llm.complete = AsyncMock(
        return_value=CognitionResponse(
            symbolic_inference="user seems curious",
            natural_language_response=PRIVATE_MODEL_OUTPUT,
        )
    )
    memory = MagicMock()
    memory.loaded = True
    memory.store_triple = AsyncMock()
    memory.query_relevant = AsyncMock(return_value=[PRIVATE_MEMORY])
    _override_route(app, llm, memory, tmp_path)
    try:
        with capture_all_levels() as logs:
            resp = TestClient(app).post(
                "/api/cognition",
                json={
                    "message": "PRIVATE_MESSAGE_X what did I say",
                    "conversation_history": [{"role": "user", "content": PRIVATE_HISTORY}],
                    "episodic_memory": [PRIVATE_MEMORY],
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    rendered = _rendered(logs)
    for sentinel in ("PRIVATE_MESSAGE_X", PRIVATE_MEMORY, PRIVATE_HISTORY, PRIVATE_MODEL_OUTPUT):
        assert sentinel not in rendered, sentinel


# ── TTS provider error bodies are not logged verbatim ────────────────────────


@pytest.mark.asyncio
async def test_tts_provider_error_body_not_logged(monkeypatch) -> None:
    from app.api import tts_route
    from app.config import settings

    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "k")
    monkeypatch.setattr(settings, "ELEVENLABS_MAX_RETRIES", 0)

    error_body = {"detail": {"status": "invalid_request", "message": f"bad text: {PRIVATE_TTS_TEXT}"}}

    class _Resp:
        status_code = 422
        headers: dict[str, str] = {}
        text = json.dumps(error_body)

        def json(self):
            return error_body

    class _Client:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw): return _Resp()

    monkeypatch.setattr(tts_route.httpx, "AsyncClient", _Client)
    with capture_all_levels() as logs:
        resp = await tts_route.tts(tts_route.TTSRequest(text=PRIVATE_TTS_TEXT))
    assert resp.status_code == 422
    rendered = _rendered(logs)
    assert PRIVATE_TTS_TEXT not in rendered
    err = _events(logs, "elevenlabs error")
    assert err and err[0].get("status") == 422
    assert err[0].get("provider_status") == "invalid_request"


# ── Audio worker: logs must never share stdout with the transcript transport ─


def test_audio_worker_logging_goes_to_stderr_with_production_level(
    capsys: pytest.CaptureFixture[str], monkeypatch,
) -> None:
    from app.config import settings
    from app.pipeline import audio_worker as aw

    monkeypatch.setattr(settings, "ENV", "production")
    aw.configure_worker_logging()
    log = structlog.get_logger()
    log.debug("worker_debug_marker")
    log.info("worker_info_marker")
    captured = capsys.readouterr()
    assert captured.out == "", "stdout is the transcript transport; no log may be written to it"
    assert "worker_debug_marker" not in captured.err
    assert "worker_info_marker" in captured.err


# ── Local console renderer must not dump traceback locals ────────────────────


def test_local_console_traceback_does_not_print_locals(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("local")
    log = structlog.get_logger()

    def _explode() -> None:
        private_local = "PRIVATE_LOCAL_VAR_3b7d"  # noqa: F841 — must not be rendered
        raise RuntimeError("boom")

    try:
        _explode()
    except RuntimeError as exc:
        log.error("unhandled_exception", error_type=type(exc).__name__, exc_info=exc)
    out = capsys.readouterr().out
    assert "RuntimeError" in out
    assert "PRIVATE_LOCAL_VAR_3b7d" not in out


# ── Production keeps per-turn operational records at INFO ────────────────────


@pytest.mark.asyncio
async def test_production_keeps_llm_and_memory_metadata(
    capsys: pytest.CaptureFixture[str], tmp_path,
) -> None:
    configure_logging("production")
    client = _llm_with('{"symbolic_inference": "calm", "natural_language_response": "ok"}')
    await client.complete(
        message=f"{PRIVATE_USER_MESSAGE} please explain why", vision=PerceptionFrame(),
        conversation_history=[], working_memory=[], episodic_memory=[],
    )
    store = MemoryStore(persist_dir=str(tmp_path))
    store.load()
    await store.query_relevant(SENSITIVE_QUERY, owner="o1")
    out = capsys.readouterr().out
    events = [json.loads(line) for line in out.strip().splitlines()]
    names = {e.get("event") for e in events}
    assert "llm api call" in names, "per-turn LLM latency/tokens must survive the INFO floor"
    assert "memory query completed" in names, "per-turn memory result count must survive the INFO floor"
    assert PRIVATE_USER_MESSAGE not in out
    assert SENSITIVE_QUERY not in out


# ── ElevenLabs list-shaped validation bodies still yield a status code ───────


def test_provider_status_handles_list_shaped_validation_detail() -> None:
    from app.api.tts_route import _provider_status

    class _Resp:
        text = ""

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            if isinstance(self._payload, Exception):
                raise self._payload
            return self._payload

    body = {"detail": [{"type": "string_too_long", "loc": ["body", "text"], "msg": "x", "input": PRIVATE_TTS_TEXT}]}
    status = _provider_status(_Resp(body))
    assert status == "string_too_long:body.text"
    assert PRIVATE_TTS_TEXT not in status
    assert _provider_status(_Resp({"detail": {"status": "quota_exceeded"}})) == "quota_exceeded"
    assert _provider_status(_Resp(ValueError("not json"))) is None


# ── Third-party stdlib loggers are floored in production ────────────────────


def test_production_floors_third_party_stdlib_loggers() -> None:
    import logging

    for name in ("anthropic", "httpx", "httpcore", "chromadb", "faster_whisper"):
        logging.getLogger(name).setLevel(logging.DEBUG)
    configure_logging("production")
    for name in ("anthropic", "httpx", "httpcore", "chromadb", "faster_whisper"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING, name


# ── url_host: only the host of a user-pasted URL is logged ───────────────────


def test_url_host_keeps_only_the_host() -> None:
    from app.cognition.llm import _url_host

    assert _url_host("https://example.com/private/PRIVATE_PATH_5e2a?token=PRIVATE_TOKEN") == "example.com"
    assert _url_host("http://sub.example.org:8443/x") == "sub.example.org:8443"
    assert _url_host(None) is None
    assert _url_host("") is None


# ── Transcription failure is a structured record, not a raw print ────────────


def test_transcribe_failure_logged_structured_without_content(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.pipeline import audio_worker as aw
    from app.pipeline.vad import VADProcessor

    vad = VADProcessor()
    vad._vad = mock.Mock()
    n_speech = 10
    n_silence = (vad.MAX_SILENCE_MS // VADProcessor.CHUNK_MS) + 1
    vad._vad.is_speech.side_effect = [True] * n_speech + [False] * n_silence
    speech = np.full(VADProcessor.CHUNK_SAMPLES, 3000, dtype="<i2").tobytes()
    silence = np.zeros(VADProcessor.CHUNK_SAMPLES, dtype="<i2").tobytes()
    pcm = speech * n_speech + silence * n_silence

    transcriber = mock.Mock()
    transcriber.transcribe.side_effect = RuntimeError(f"decoder choked on {PRIVATE_TRANSCRIPT}")
    denoiser = mock.Mock()
    denoiser.enabled = False
    args = argparse.Namespace(denoise=False, max_utterance_ms=8000)

    with capture_all_levels() as logs, contextlib.redirect_stdout(io.StringIO()):
        aw.process_audio_stream(aw.read_pcm_chunks(io.BytesIO(pcm)), vad, transcriber, denoiser, args)

    failed = _events(logs, "transcribe failed")
    assert failed and failed[0].get("error_type") == "RuntimeError"
    assert failed[0].get("consecutive_errors") == 1
    assert PRIVATE_TRANSCRIPT not in _rendered(logs)
    assert "transcribe error" not in capsys.readouterr().err
