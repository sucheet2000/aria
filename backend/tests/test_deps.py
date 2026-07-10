import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.deps import (
    INTERNAL_AUTH_HEADER,
    get_current_owner,
    require_internal_auth,
)
from app.config import settings


def _make_request(headers: dict[str, str]) -> Request:
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in headers.items()
    ]
    scope = {"type": "http", "headers": raw_headers}
    return Request(scope)


def test_get_current_owner_returns_header_value() -> None:
    request = _make_request({"X-Aria-Owner": "user_123"})
    assert get_current_owner(request) == "user_123"


def test_get_current_owner_falls_back_to_default_owner() -> None:
    request = _make_request({})
    assert get_current_owner(request) == settings.DEFAULT_OWNER
    assert get_current_owner(request) == "local"


def test_require_internal_auth_passthrough_when_secret_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_AUTH_SECRET", "")
    # No header present, but no secret configured -> pass-through (no raise).
    assert require_internal_auth(_make_request({})) is None


def test_require_internal_auth_rejects_missing_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_AUTH_SECRET", "s3cr3t")
    with pytest.raises(HTTPException) as exc:
        require_internal_auth(_make_request({}))
    assert exc.value.status_code == 403


def test_require_internal_auth_rejects_wrong_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_AUTH_SECRET", "s3cr3t")
    with pytest.raises(HTTPException) as exc:
        require_internal_auth(_make_request({INTERNAL_AUTH_HEADER: "nope"}))
    assert exc.value.status_code == 403


def test_require_internal_auth_accepts_matching_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_AUTH_SECRET", "s3cr3t")
    assert require_internal_auth(_make_request({INTERNAL_AUTH_HEADER: "s3cr3t"})) is None
