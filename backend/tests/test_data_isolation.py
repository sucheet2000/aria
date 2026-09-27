"""The test suite must never read, migrate, sweep or create the developer's
real stores.

``DATA_DIR`` defaults to ``backend/``, which is where a developer's local
ARIA keeps its memory. Any test that runs the real lifespan (``with
TestClient(app)``) opens ``MemoryStore`` there, and ``load()`` migrates owner
metadata and sweeps expired facts, i.e. it deletes. Running the suite once
created ``backend/memory/chroma.sqlite3`` and ``backend/data/anchors.db`` in a
clean checkout. These tests hold the isolation in place.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REAL_STORES = (_BACKEND_DIR / "memory", _BACKEND_DIR / "data")


# SQLite side files come and go while a local ARIA is running against the
# default DATA_DIR, so they are not evidence either way.
_SQLITE_SIDE_FILES = ("-journal", "-wal", "-shm")


def _real_store_files() -> set[str]:
    return {
        str(p)
        for root in _REAL_STORES
        if root.exists()
        for p in root.rglob("*")
        if p.is_file() and not p.name.endswith(_SQLITE_SIDE_FILES)
    }


def test_tests_run_against_a_throwaway_data_dir() -> None:
    data_dir = Path(settings.DATA_DIR).resolve()
    assert data_dir != _BACKEND_DIR
    assert not data_dir.is_relative_to(_BACKEND_DIR)
    assert os.environ.get("DATA_DIR") == settings.DATA_DIR


def test_lifespan_opens_stores_only_inside_the_test_data_dir() -> None:
    from app.main import app

    before = _real_store_files()
    with TestClient(app):
        memory_dir = Path(app.state.memory._persist_dir).resolve()
        anchors_db = Path(app.state.registry._db_path).resolve()
    data_dir = Path(settings.DATA_DIR).resolve()

    assert memory_dir.is_relative_to(data_dir)
    assert anchors_db.is_relative_to(data_dir)
    assert _real_store_files() == before


def test_subprocesses_inherit_the_test_data_dir() -> None:
    out = subprocess.run(
        [sys.executable, "-c", "from app.config import settings; print(settings.DATA_DIR)"],
        cwd=_BACKEND_DIR,
        env={**os.environ, "PYTHONPATH": str(_BACKEND_DIR)},
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    child_data_dir = out.stdout.strip()
    assert Path(child_data_dir).resolve() != _BACKEND_DIR
    assert child_data_dir == settings.DATA_DIR


# The two canaries below run in file order. The first leaves the shared app
# dirty on purpose; the second fails if anything the first left behind is
# still there, which is what an order-dependent suite looks like. The second
# refuses to pass on its own (under -k, --lf or a reordering plugin), because
# then it would prove nothing.
_canary_1_ran = False


def test_restoration_canary_1_dirties_the_shared_app() -> None:
    global _canary_1_ran
    from app.main import app

    app.state.canary = object()
    app.dependency_overrides[_canary_dependency] = lambda: "leaked"
    _canary_1_ran = True


def test_restoration_canary_2_sees_a_clean_shared_app() -> None:
    from app.main import app

    assert _canary_1_ran, "run canary 2 after canary 1 in the same session; alone it proves nothing"
    assert not hasattr(app.state, "canary")
    assert _canary_dependency not in app.dependency_overrides
    assert not hasattr(app.state, "memory")
    assert not hasattr(app.state, "registry")


def _canary_dependency() -> str:
    return "real"
