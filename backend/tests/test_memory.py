from __future__ import annotations

import pytest


def test_memory_store_initializes_unloaded() -> None:
    from app.cognition.memory import MemoryStore
    store = MemoryStore()
    assert store.loaded is False


def test_triple_id_deterministic() -> None:
    from app.cognition.memory import MemoryStore
    store = MemoryStore()
    id1 = store._triple_id("sucheet", "prefers", "Go")
    id2 = store._triple_id("sucheet", "prefers", "Go")
    assert id1 == id2
    assert len(id1) == 16


def test_triple_text_format() -> None:
    from app.cognition.memory import MemoryStore
    store = MemoryStore()
    assert store._triple_text("sucheet", "prefers", "Go") == "sucheet prefers Go"


@pytest.mark.asyncio
async def test_store_and_query_profile(tmp_path) -> None:
    pytest.importorskip("chromadb")

    from app.cognition.memory import MemoryStore
    store = MemoryStore(persist_dir=str(tmp_path))
    store.load()
    assert store.loaded

    await store.store_triple("sucheet", "prefers", "Go", 0.9, "explicit_statement")
    results = await store.query_relevant("programming language preference")
    assert "sucheet prefers Go" in results


@pytest.mark.asyncio
async def test_clear_working(tmp_path) -> None:
    pytest.importorskip("chromadb")

    from app.cognition.memory import MemoryStore
    store = MemoryStore(persist_dir=str(tmp_path))
    store.load()
    assert store.loaded

    await store.store_triple("user", "debugging", "FastAPI endpoint", 0.8, "working")
    ids_before = store._working.get()["ids"]
    assert len(ids_before) > 0

    await store.clear_working()
    ids_after = store._working.get()["ids"]
    assert ids_after == []
