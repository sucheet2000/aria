from __future__ import annotations

import pytest
from structlog.testing import capture_logs

from app.config import Settings
from app.main import validate_anthropic_key, validate_internal_auth


def test_validate_anthropic_key_warns_when_empty_and_not_strict() -> None:
    settings = Settings(ANTHROPIC_API_KEY="", REQUIRE_ANTHROPIC_KEY=False)
    with capture_logs() as logs:
        validate_anthropic_key(settings)
    assert any(entry["log_level"] == "warning" for entry in logs)


def test_validate_anthropic_key_raises_when_empty_and_strict() -> None:
    settings = Settings(ANTHROPIC_API_KEY="", REQUIRE_ANTHROPIC_KEY=True)
    with pytest.raises(RuntimeError):
        validate_anthropic_key(settings)


def test_validate_anthropic_key_silent_when_key_present() -> None:
    settings = Settings(ANTHROPIC_API_KEY="sk-ant-test", REQUIRE_ANTHROPIC_KEY=True)
    with capture_logs() as logs:
        validate_anthropic_key(settings)
    assert not any(entry["log_level"] == "warning" for entry in logs)


def test_validate_internal_auth_raises_when_empty_and_non_local() -> None:
    settings = Settings(INTERNAL_AUTH_SECRET="", ENV="production")
    with pytest.raises(RuntimeError):
        validate_internal_auth(settings)


def test_validate_internal_auth_warns_when_empty_and_local() -> None:
    settings = Settings(INTERNAL_AUTH_SECRET="", ENV="local")
    with capture_logs() as logs:
        validate_internal_auth(settings)
    assert any(entry["log_level"] == "warning" for entry in logs)


def test_validate_internal_auth_silent_when_secret_set_non_local() -> None:
    settings = Settings(INTERNAL_AUTH_SECRET="boundary-secret", ENV="production")
    with capture_logs() as logs:
        validate_internal_auth(settings)
    assert not any(entry["log_level"] == "warning" for entry in logs)


def test_validate_internal_auth_silent_when_secret_set_local() -> None:
    settings = Settings(INTERNAL_AUTH_SECRET="boundary-secret", ENV="local")
    with capture_logs() as logs:
        validate_internal_auth(settings)
    assert not any(entry["log_level"] == "warning" for entry in logs)


def test_env_defaults_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENV", raising=False)
    assert Settings(_env_file=None).ENV == "local"


def test_env_loads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    assert Settings().ENV == "production"


def test_anthropic_reliability_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("ANTHROPIC_MAX_RETRIES", raising=False)
    settings = Settings(_env_file=None)
    assert settings.ANTHROPIC_TIMEOUT_SECONDS == 30.0
    assert settings.ANTHROPIC_MAX_RETRIES == 3


def test_anthropic_reliability_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("ANTHROPIC_MAX_RETRIES", "7")
    settings = Settings(_env_file=None)
    assert settings.ANTHROPIC_TIMEOUT_SECONDS == 12.5
    assert settings.ANTHROPIC_MAX_RETRIES == 7


# The link between the two, which neither end covers.
#
# The predicate above is tested directly, and require_internal_auth is tested
# against a missing or wrong header. What nothing tested is that the app
# actually CONSULTS the predicate at startup: the call lives inside `lifespan`
# (app/main.py), and every other test builds TestClient(app) without the
# context manager, so lifespan never runs. Deleting the call left ruff clean
# and 276 tests passing.
#
# It matters more since /metrics joined the internal boundary. When
# INTERNAL_AUTH_SECRET is empty, require_internal_auth returns early
# (deps.py) — so the startup guard is the only thing making "the Python
# metrics route is internally gated" true in production. Before /metrics was
# gated, this guard did not bear on metrics at all.
def test_startup_refuses_to_boot_with_an_open_trust_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.config import settings as live_settings

    monkeypatch.setattr(live_settings, "INTERNAL_AUTH_SECRET", "")
    monkeypatch.setattr(live_settings, "ENV", "production")

    from app.main import app

    with pytest.raises(RuntimeError, match="INTERNAL_AUTH_SECRET"):
        # Entering the context manager is what runs lifespan.
        with TestClient(app):
            pass


def test_startup_proceeds_when_the_boundary_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.config import settings as live_settings

    monkeypatch.setattr(live_settings, "INTERNAL_AUTH_SECRET", "a-configured-secret")
    monkeypatch.setattr(live_settings, "ENV", "production")

    from app.main import app

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
