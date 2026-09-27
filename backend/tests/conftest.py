"""Suite-wide isolation for durable state and the shared FastAPI app.

``DATA_DIR`` defaults to ``backend/``, where a developer's local ARIA keeps
its memory. A test that runs the real lifespan opens ``MemoryStore`` there and
``load()`` migrates and sweeps (deletes) it. Every test therefore gets its own
throwaway ``DATA_DIR``, both on the live settings object and in the
environment so subprocesses inherit it.

``app`` is a module-level singleton: lifespan populates ``app.state`` and many
tests set ``app.state`` or ``app.dependency_overrides`` without undoing it, so
a later test could silently run against an earlier test's stores. Both are
restored to what they held before each test.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _isolated_data_dir(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    data_dir = tmp_path_factory.mktemp("aria-data")
    monkeypatch.setattr(settings, "DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    return data_dir


def _shared_app() -> Any:
    module = sys.modules.get("app.main")
    return getattr(module, "app", None)


@pytest.fixture(autouse=True)
def _restore_shared_app() -> Iterator[None]:
    app = _shared_app()
    state_before = dict(app.state._state) if app is not None else {}
    overrides_before = dict(app.dependency_overrides) if app is not None else {}
    yield
    app = _shared_app()
    if app is None:
        return
    app.state._state.clear()
    app.state._state.update(state_before)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(overrides_before)
