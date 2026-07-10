from __future__ import annotations

import pathlib
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.deps import INTERNAL_AUTH_HEADER
from app.config import settings
from app.main import app
from app.spatial.anchor_registry import AnchorRegistry

SECRET = "boundary-secret"


@pytest.fixture()
def client(tmp_path: pathlib.Path) -> Iterator[TestClient]:
    from app.api.cognition_route import get_registry

    registry = AnchorRegistry(db_path=tmp_path / "anchors.db")
    app.dependency_overrides[get_registry] = lambda: registry
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_api_route_403_when_secret_set_and_header_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_AUTH_SECRET", SECRET)
    resp = client.get("/api/anchors")
    assert resp.status_code == 403


def test_api_route_403_when_secret_set_and_header_wrong(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_AUTH_SECRET", SECRET)
    resp = client.get("/api/anchors", headers={INTERNAL_AUTH_HEADER: "nope"})
    assert resp.status_code == 403


def test_api_route_200_when_secret_set_and_header_matches(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_AUTH_SECRET", SECRET)
    resp = client.get("/api/anchors", headers={INTERNAL_AUTH_HEADER: SECRET})
    assert resp.status_code == 200
    assert resp.json() == {"anchors": []}


def test_api_route_passthrough_when_secret_unset(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_AUTH_SECRET", "")
    resp = client.get("/api/anchors")
    assert resp.status_code == 200


def test_tts_route_behind_boundary_403_when_header_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_AUTH_SECRET", SECRET)
    resp = client.post("/api/tts", json={"text": "hi"})
    assert resp.status_code == 403


def test_health_stays_open_when_secret_set(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_AUTH_SECRET", SECRET)
    resp = client.get("/health")
    assert resp.status_code == 200
