from __future__ import annotations

import pytest


def test_memory_store_initializes_unloaded() -> None:
    from app.cognition.memory import MemoryStore
    store = MemoryStore()
    assert store.loaded is False


def test_triple_id_deterministic() -> None:
    from app.cognition.memory import MemoryStore
    store = MemoryStore()
    id1 = store._triple_id("local", "sucheet", "prefers", "Go")
    id2 = store._triple_id("local", "sucheet", "prefers", "Go")
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

    await store.store_triple("sucheet", "prefers", "Go", 0.9, "explicit_statement", owner="local")
    results = await store.query_relevant("programming language preference", owner="local")
    assert "sucheet prefers Go" in results


@pytest.mark.asyncio
async def test_clear_working(tmp_path) -> None:
    pytest.importorskip("chromadb")

    from app.cognition.memory import MemoryStore
    store = MemoryStore(persist_dir=str(tmp_path))
    store.load()
    assert store.loaded

    await store.store_triple("user", "debugging", "FastAPI endpoint", 0.8, "working", owner="local")
    ids_before = store._working.get()["ids"]
    assert len(ids_before) > 0

    await store.clear_working(owner="local")
    ids_after = store._working.get()["ids"]
    assert ids_after == []


@pytest.mark.asyncio
async def test_two_owners_isolated(tmp_path) -> None:
    pytest.importorskip("chromadb")

    from app.cognition.memory import MemoryStore
    store = MemoryStore(persist_dir=str(tmp_path))
    store.load()

    await store.store_triple("sucheet", "prefers", "Go", 0.9, "explicit_statement", owner="a")

    # owner "b" sees nothing
    assert await store.query_relevant("language preference", owner="b") == []
    assert await store.get_profile_facts(owner="b") == []

    # owner "a" sees its own fact
    assert "sucheet prefers Go" in await store.query_relevant("language preference", owner="a")
    assert "sucheet prefers Go" in await store.get_profile_facts(owner="a")


@pytest.mark.asyncio
async def test_backfill_assigns_local_owner(tmp_path) -> None:
    pytest.importorskip("chromadb")

    # Seed a legacy doc with NO owner metadata, as older versions wrote.
    import chromadb

    from app.cognition.memory import PROFILE_COLLECTION, MemoryStore
    client = chromadb.PersistentClient(path=str(tmp_path))
    profile = client.get_or_create_collection(PROFILE_COLLECTION)
    profile.add(
        ids=["legacy1"],
        documents=["sucheet likes tea"],
        metadatas=[{"subject": "sucheet", "predicate": "likes", "object": "tea"}],
    )
    del client, profile

    store = MemoryStore(persist_dir=str(tmp_path))
    store.load()  # runs the owner backfill

    # legacy doc is now queryable under the default owner "local"
    assert "sucheet likes tea" in await store.get_profile_facts(owner="local")
    assert await store.get_profile_facts(owner="someone-else") == []
