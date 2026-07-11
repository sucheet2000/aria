from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings


def _backend_dir() -> Path:
    # tests/ -> backend/
    return Path(__file__).resolve().parent.parent


def test_default_data_dir_is_backend() -> None:
    assert Path(settings.DATA_DIR).resolve() == _backend_dir()


def test_default_paths_match_todays_layout() -> None:
    from app.cognition.memory import MemoryStore
    from app.spatial import anchor_registry

    backend = _backend_dir()

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
