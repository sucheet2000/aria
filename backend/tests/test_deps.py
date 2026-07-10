from starlette.requests import Request

from app.api.deps import get_current_owner
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
