from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings, settings


def _backend_dir() -> Path:
    # tests/ -> backend/
    return Path(__file__).resolve().parent.parent


def _unconfigured_data_dir(monkeypatch: pytest.MonkeyPatch) -> str:
    # What a process with no DATA_DIR configured would get. conftest points the
    # live settings at a throwaway dir for every test, so the default has to be
    # read from a fresh Settings built without the env var or a .env file.
    monkeypatch.delenv("DATA_DIR", raising=False)
    return Settings(_env_file=None).DATA_DIR  # type: ignore[call-arg]


def test_default_data_dir_is_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Path(_unconfigured_data_dir(monkeypatch)).resolve() == _backend_dir()


def test_default_paths_match_todays_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.cognition.memory import MemoryStore
    from app.spatial import anchor_registry

    backend = _backend_dir()
    # Path derivation only: MemoryStore() and _default_db_path() touch no disk.
    monkeypatch.setattr(settings, "DATA_DIR", _unconfigured_data_dir(monkeypatch))

    store = MemoryStore()
    assert Path(store._persist_dir).resolve() == (backend / "memory").resolve()

    db = anchor_registry._default_db_path().resolve()
    assert db == (backend / "data" / "anchors.db").resolve()


def test_data_dir_relocates_all_storage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.cognition.memory import MemoryStore
    from app.spatial import anchor_registry

    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    root = tmp_path.resolve()

    persist = Path(MemoryStore()._persist_dir).resolve()
    assert persist.is_relative_to(root)

    db = anchor_registry._default_db_path().resolve()
    assert db.is_relative_to(root)
