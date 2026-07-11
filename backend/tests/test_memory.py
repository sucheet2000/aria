from __future__ import annotations

import time
from unittest import mock

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
async def test_store_triple_offloads_to_threadpool(tmp_path, monkeypatch) -> None:
    pytest.importorskip("chromadb")

    from app.cognition import memory as mem_mod
    store = mem_mod.MemoryStore(persist_dir=str(tmp_path))
    store.load()

    called: dict[str, str] = {}
    orig = mem_mod.run_in_threadpool

    async def spy(fn, *args, **kwargs):
        called["fn"] = fn.__name__
        return await orig(fn, *args, **kwargs)

    monkeypatch.setattr(mem_mod, "run_in_threadpool", spy)
    await store.store_triple("s", "p", "o", 0.9, "explicit_statement", owner="x")

    # the blocking ChromaDB work ran off the event loop, not inline
    assert called["fn"] == "_store_triple_sync"


@pytest.mark.asyncio
async def test_query_relevant_empty_collection_returns_empty(tmp_path) -> None:
    pytest.importorskip("chromadb")

    from app.cognition.memory import MemoryStore
    store = MemoryStore(persist_dir=str(tmp_path))
    store.load()
    assert store.loaded

    # Both collections are empty: the guard must short-circuit and return []
    # deterministically, never reaching (or depending on an error from) query().
    with mock.patch.object(
        store._profile, "query", side_effect=AssertionError("query on empty")
    ) as profile_query, mock.patch.object(
        store._episodic, "query", side_effect=AssertionError("query on empty")
    ) as episodic_query:
        result = await store.query_relevant("anything at all", owner="local")

    assert result == []
    profile_query.assert_not_called()
    episodic_query.assert_not_called()


@pytest.mark.asyncio
async def test_store_triple_dedup(tmp_path) -> None:
    pytest.importorskip("chromadb")

    from app.cognition.memory import MemoryStore
    store = MemoryStore(persist_dir=str(tmp_path))
    store.load()

    await store.store_triple("sucheet", "prefers", "Go", 0.9, "explicit_statement", owner="local")
    await store.store_triple("sucheet", "prefers", "Go", 0.95, "explicit_statement", owner="local")

    ids = store._profile.get(where={"owner": "local"})["ids"]
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_query_relevant_excludes_expired_episodic(tmp_path) -> None:
    pytest.importorskip("chromadb")

    from app.cognition.memory import MemoryStore
    store = MemoryStore(persist_dir=str(tmp_path))
    store.load()

    await store.store_triple(
        "user", "likes", "tea", 0.8, "behavioral_inference", owner="local"
    )
    # Fresh episodic fact is returned.
    fresh = await store.query_relevant("what does the user like", owner="local")
    assert "user likes tea" in fresh

    # Force its TTL into the past; it must now be filtered out of results.
    doc_id = store._episodic.get(where={"owner": "local"})["ids"][0]
    meta = store._episodic.get(ids=[doc_id])["metadatas"][0]
    meta["expires_at"] = time.time() - 10
    store._episodic.update(ids=[doc_id], metadatas=[meta])

    expired = await store.query_relevant("what does the user like", owner="local")
    assert "user likes tea" not in expired


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
