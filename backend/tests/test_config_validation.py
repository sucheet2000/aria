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
