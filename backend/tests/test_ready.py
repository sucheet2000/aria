from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture()
def client() -> Iterator[TestClient]:
    had = hasattr(app.state, "memory")
    saved = getattr(app.state, "memory", None)
    yield TestClient(app)
    if had:
        app.state.memory = saved
    elif hasattr(app.state, "memory"):
        del app.state.memory


def test_ready_200_when_memory_loaded(client: TestClient) -> None:
    app.state.memory = SimpleNamespace(loaded=True)
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


def test_ready_503_when_memory_not_loaded(client: TestClient) -> None:
    app.state.memory = SimpleNamespace(loaded=False)
    resp = client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not ready"


def test_ready_503_when_memory_missing(client: TestClient) -> None:
    if hasattr(app.state, "memory"):
        del app.state.memory
    resp = client.get("/ready")
    assert resp.status_code == 503


def test_ready_503_when_data_dir_not_writable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.state.memory = SimpleNamespace(loaded=True)
    monkeypatch.setattr(settings, "DATA_DIR", "/nonexistent/aria/data/xyz")
    resp = client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["reason"]
