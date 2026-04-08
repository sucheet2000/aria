from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.spatial.anchor_registry import AnchorRegistry


@pytest.fixture()
def registry(tmp_path: pathlib.Path) -> AnchorRegistry:
    return AnchorRegistry(db_path=tmp_path / "test_anchors.db")


@pytest.fixture()
def client(registry: AnchorRegistry) -> TestClient:
    with patch("app.api.cognition_route.get_registry", return_value=registry):
        yield TestClient(app)


# --- GET /api/anchors ---

def test_list_anchors_empty(client: TestClient) -> None:
    resp = client.get("/api/anchors")
    assert resp.status_code == 200
    assert resp.json() == {"anchors": []}


def test_list_anchors_returns_registered(client: TestClient, registry: AnchorRegistry) -> None:
    registry.register_anchor((0.1, 0.2, 0.3), "lamp")
    registry.register_anchor((0.4, 0.5, 0.6), "chair")

    resp = client.get("/api/anchors")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["anchors"]) == 2
    labels = {a["label"] for a in data["anchors"]}
    assert labels == {"lamp", "chair"}


def test_list_anchors_response_has_anchor_id_field(client: TestClient, registry: AnchorRegistry) -> None:
    registry.register_anchor((0.1, 0.2, 0.3), "mug")
    resp = client.get("/api/anchors")
    data = resp.json()
    assert "anchor_id" in data["anchors"][0]


def test_list_anchors_returns_correct_coordinates(client: TestClient, registry: AnchorRegistry) -> None:
    registry.register_anchor((0.11, 0.22, 0.33), "desk")
    resp = client.get("/api/anchors")
    anchor = resp.json()["anchors"][0]
    assert anchor["x"] == pytest.approx(0.11, abs=1e-5)
    assert anchor["y"] == pytest.approx(0.22, abs=1e-5)
    assert anchor["z"] == pytest.approx(0.33, abs=1e-5)


def test_list_anchors_ordered_by_created_at(client: TestClient, registry: AnchorRegistry) -> None:
    id_a = registry.register_anchor((0.1, 0.0, 0.0), "first")
    id_b = registry.register_anchor((0.2, 0.0, 0.0), "second")

    resp = client.get("/api/anchors")
    anchors = resp.json()["anchors"]
    assert anchors[0]["anchor_id"] == id_a
    assert anchors[1]["anchor_id"] == id_b


# --- DELETE /api/anchors/{anchor_id} ---

def test_delete_anchor_returns_200(client: TestClient, registry: AnchorRegistry) -> None:
    anchor_id = registry.register_anchor((0.1, 0.2, 0.3), "lamp")
    resp = client.delete(f"/api/anchors/{anchor_id}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": anchor_id}


def test_delete_removes_from_list(client: TestClient, registry: AnchorRegistry) -> None:
    anchor_id = registry.register_anchor((0.1, 0.2, 0.3), "lamp")
    client.delete(f"/api/anchors/{anchor_id}")

    resp = client.get("/api/anchors")
    ids = [a["anchor_id"] for a in resp.json()["anchors"]]
    assert anchor_id not in ids


def test_delete_nonexistent_returns_404(client: TestClient) -> None:
    resp = client.delete("/api/anchors/does-not-exist")
    assert resp.status_code == 404


def test_delete_twice_second_is_404(client: TestClient, registry: AnchorRegistry) -> None:
    anchor_id = registry.register_anchor((0.1, 0.2, 0.3), "lamp")
    client.delete(f"/api/anchors/{anchor_id}")
    resp = client.delete(f"/api/anchors/{anchor_id}")
    assert resp.status_code == 404
