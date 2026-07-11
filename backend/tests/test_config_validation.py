from __future__ import annotations

import pytest
from structlog.testing import capture_logs

from app.config import Settings
from app.main import validate_anthropic_key


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
