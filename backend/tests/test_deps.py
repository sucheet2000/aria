from app.api.deps import get_current_owner
from app.config import settings


def test_get_current_owner_returns_default_owner() -> None:
    assert get_current_owner() == settings.DEFAULT_OWNER
    assert get_current_owner() == "local"
