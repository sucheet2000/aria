from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
import structlog
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from app.main import app
from app.observability.metrics import MetricsCollector

BOOM_PATH = "/__obs_boom__"


@pytest.fixture(autouse=True)
def _restore_structlog() -> Iterator[None]:
    saved = structlog.get_config()
    yield
    structlog.configure(**saved)


@pytest.fixture()
def boom_client() -> Iterator[TestClient]:
    async def _boom() -> None:
        raise RuntimeError("intentional boom")

    app.add_api_route(BOOM_PATH, _boom, methods=["GET"])
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", None) != BOOM_PATH
        ]


# --- OBS-4: request-id middleware ---


def test_request_id_echoed_when_provided() -> None:
    client = TestClient(app)
    resp = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == "abc-123"


def test_request_id_generated_when_absent() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    generated = resp.headers.get("X-Request-ID")
    assert generated
    uuid.UUID(generated)  # must be a valid UUID


# --- OBS-5: global exception handler ---


def test_unhandled_exception_returns_error_envelope(boom_client: TestClient) -> None:
    resp = boom_client.get(BOOM_PATH, headers={"X-Request-ID": "err-9"})
    assert resp.status_code == 500
    body = resp.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "request_id"}
    assert body["error"]["request_id"] == "err-9"
    assert resp.headers["X-Request-ID"] == "err-9"


def test_unhandled_exception_increments_error_metric(boom_client: TestClient) -> None:
    m = MetricsCollector()
    before = m.snapshot()["errors"]
    boom_client.get(BOOM_PATH)
    after = m.snapshot()["errors"]
    assert after == before + 1


def test_unhandled_exception_is_logged(boom_client: TestClient) -> None:
    with capture_logs() as logs:
        boom_client.get(BOOM_PATH, headers={"X-Request-ID": "log-me"})
    error_logs = [e for e in logs if e.get("log_level") == "error"]
    assert error_logs
    assert any(e.get("request_id") == "log-me" for e in error_logs)


# --- OBS-1: configure_logging renderer selection ---


def test_configure_logging_json_when_not_local() -> None:
    from app.observability.logging import configure_logging

    configure_logging("production")
    processors = structlog.get_config()["processors"]
    assert isinstance(processors[-1], structlog.processors.JSONRenderer)


def test_configure_logging_console_when_local() -> None:
    from app.observability.logging import configure_logging

    configure_logging("local")
    processors = structlog.get_config()["processors"]
    assert isinstance(processors[-1], structlog.dev.ConsoleRenderer)
