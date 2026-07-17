from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import tts_route
from app.config import Settings
from app.main import app


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient that returns queued responses and counts POSTs."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self.calls: list[dict] = []

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(self, *args: object, **kwargs: object) -> httpx.Response:
        index = min(len(self.calls), len(self._responses) - 1)
        self.calls.append({"args": args, "kwargs": kwargs})
        return self._responses[index]


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch, responses: list[httpx.Response]
) -> dict[str, _FakeAsyncClient]:
    """Patch tts_route.httpx.AsyncClient with a factory and expose the created instance."""
    created: dict[str, _FakeAsyncClient] = {}

    def factory(*args: object, **kwargs: object) -> _FakeAsyncClient:
        instance = _FakeAsyncClient(responses)
        created["client"] = instance
        return instance

    monkeypatch.setattr(tts_route.httpx, "AsyncClient", factory)
    return created


def _install_sleep_spy(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Neutralize real sleeping and record every requested delay."""
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(tts_route.asyncio, "sleep", fake_sleep)
    return delays


def _pin_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the API key on so the route does not early-return 503."""
    monkeypatch.setattr(tts_route.settings, "ELEVENLABS_API_KEY", "test-key")


def _pin_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make equal-jitter backoff deterministic (uniform -> 0.0)."""
    monkeypatch.setattr(tts_route.random, "uniform", lambda a, b: 0.0)


def _audio_response() -> httpx.Response:
    return httpx.Response(200, content=b"x" * 200)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# --- Retry behavior (new — RED until the bounded-retry wrapper exists) ---

def test_retries_on_429_then_succeeds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_key(monkeypatch)
    _pin_jitter(monkeypatch)
    _install_sleep_spy(monkeypatch)
    created = _install_fake_client(
        monkeypatch,
        [httpx.Response(429, content=b""), _audio_response()],
    )

    resp = client.post(
        "/api/tts", json={"text": "hello there friend", "emotion": "happy"}
    )

    assert resp.status_code == 200
    assert resp.content == b"x" * 200
    assert len(created["client"].calls) == 2


def test_5xx_exhausts_and_returns_last_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_key(monkeypatch)
    _pin_jitter(monkeypatch)
    _install_sleep_spy(monkeypatch)
    created = _install_fake_client(
        monkeypatch,
        [httpx.Response(500, content=b"") for _ in range(4)],
    )

    resp = client.post(
        "/api/tts", json={"text": "hello there friend", "emotion": "happy"}
    )

    assert resp.status_code == 500
    assert len(created["client"].calls) == tts_route.settings.ELEVENLABS_MAX_RETRIES + 1


def test_honors_retry_after_within_budget(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_key(monkeypatch)
    delays = _install_sleep_spy(monkeypatch)
    created = _install_fake_client(
        monkeypatch,
        [
            httpx.Response(429, headers={"Retry-After": "0.5"}, content=b""),
            _audio_response(),
        ],
    )

    resp = client.post(
        "/api/tts", json={"text": "hello there friend", "emotion": "happy"}
    )

    assert resp.status_code == 200
    assert len(created["client"].calls) == 2
    assert 0.5 in delays


def test_retry_after_beyond_budget_stops(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_key(monkeypatch)
    _install_sleep_spy(monkeypatch)
    created = _install_fake_client(
        monkeypatch,
        [
            httpx.Response(429, headers={"Retry-After": "100"}, content=b""),
            _audio_response(),
        ],
    )

    resp = client.post(
        "/api/tts", json={"text": "hello there friend", "emotion": "happy"}
    )

    assert resp.status_code == 429
    assert len(created["client"].calls) == 1


def test_worst_case_budget_under_frontend_abort() -> None:
    assert tts_route._worst_case_budget_seconds() < 15.0
    assert tts_route._RETRY_BUDGET_SECONDS < 15.0


# --- Preserved behavior (regression guards — should already hold) ---

def test_402_returns_503_with_zero_retries(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_key(monkeypatch)
    created = _install_fake_client(monkeypatch, [httpx.Response(402, content=b"")])

    resp = client.post(
        "/api/tts", json={"text": "hello there friend", "emotion": "happy"}
    )

    assert resp.status_code == 503
    assert resp.content == b""
    assert len(created["client"].calls) == 1


@pytest.mark.parametrize("status", [400, 401, 404])
def test_non_429_4xx_not_retried(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    _pin_key(monkeypatch)
    created = _install_fake_client(monkeypatch, [httpx.Response(status, content=b"")])

    resp = client.post(
        "/api/tts", json={"text": "hello there friend", "emotion": "happy"}
    )

    assert resp.status_code == status
    assert len(created["client"].calls) == 1


def test_200_first_try_single_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_key(monkeypatch)
    created = _install_fake_client(monkeypatch, [_audio_response()])

    resp = client.post(
        "/api/tts", json={"text": "hello there friend", "emotion": "happy"}
    )

    assert resp.status_code == 200
    assert len(created["client"].calls) == 1


def test_emotion_payload_preserved(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_key(monkeypatch)
    _install_fake_client(monkeypatch, [_audio_response()])

    spy = MagicMock(
        return_value={
            "text": "hello there friend",
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {},
        }
    )
    monkeypatch.setattr(tts_route.voice_engine, "build_request_payload", spy)

    resp = client.post(
        "/api/tts", json={"text": "hello there friend", "emotion": "happy"}
    )

    assert resp.status_code == 200
    spy.assert_called_once()
    kwargs = spy.call_args.kwargs
    assert kwargs["text"] == "hello there friend"
    assert kwargs["emotion"] == "happy"
    assert kwargs["use_turbo"] is True
    assert "voice_id" in kwargs


def test_402_fallback_body_unchanged(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_key(monkeypatch)
    _install_fake_client(monkeypatch, [httpx.Response(402, content=b"")])

    resp = client.post(
        "/api/tts", json={"text": "hello there friend", "emotion": "happy"}
    )

    assert resp.status_code == 503
    assert resp.content == b""


# --- Config (new — RED until the reliability settings exist) ---

def test_elevenlabs_reliability_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("ELEVENLABS_MAX_RETRIES", raising=False)
    settings = Settings(_env_file=None)
    assert settings.ELEVENLABS_TIMEOUT_SECONDS == 4.0
    assert settings.ELEVENLABS_MAX_RETRIES == 2


def test_elevenlabs_reliability_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVENLABS_TIMEOUT_SECONDS", "6.5")
    monkeypatch.setenv("ELEVENLABS_MAX_RETRIES", "1")
    settings = Settings(_env_file=None)
    assert settings.ELEVENLABS_TIMEOUT_SECONDS == 6.5
    assert settings.ELEVENLABS_MAX_RETRIES == 1
