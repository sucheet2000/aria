"""M1 - /metrics sits behind the internal trust boundary like the other data
routes.

The Go edge is the only legitimate caller and already sends X-Internal-Auth, so
leaving the Python route open made the edge's scrape credential the single wall
in front of operational counters and Claude token spend - and left the data
readable outright by anything that could reach :8000 directly.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import INTERNAL_AUTH_HEADER
from app.config import settings


@pytest.fixture
def secret(monkeypatch: pytest.MonkeyPatch) -> str:
    value = "internal-boundary-secret-for-tests"
    monkeypatch.setattr(settings, "INTERNAL_AUTH_SECRET", value)
    return value


def _client() -> TestClient:
    from app.main import app

    return TestClient(app)


class TestMetricsRouteIsBehindTheInternalBoundary:
    def test_no_internal_credential_is_refused(self, secret: str) -> None:
        assert _client().get("/metrics").status_code == 403

    def test_wrong_internal_credential_is_refused(self, secret: str) -> None:
        resp = _client().get("/metrics", headers={INTERNAL_AUTH_HEADER: "wrong-" + secret})
        assert resp.status_code == 403

    def test_the_edge_credential_is_accepted(self, secret: str) -> None:
        resp = _client().get("/metrics", headers={INTERNAL_AUTH_HEADER: secret})
        assert resp.status_code == 200
        assert "gesture_events" in resp.json()

    def test_health_stays_open_for_the_platform_probe(self, secret: str) -> None:
        """Railway probes /health; it must not need the internal credential."""
        assert _client().get("/health").status_code == 200
