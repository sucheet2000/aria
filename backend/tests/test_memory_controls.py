"""S3 — owner-scoped memory export/delete, and deleted memory stays deleted.

Every test that touches storage uses the real MemoryStore on a real ChromaDB
directory (tmp_path); only the Anthropic network call is mocked.
"""
from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from app.cognition.memory import MemoryStore
from app.models.schemas import CognitionResponse

DELETED_SENTINEL = "DELETED_MEMORY_SENTINEL_9137"
PRIVATE_SENTINEL = "PRIVATE_MEMORY_DELETE_5b21"


@pytest.fixture(autouse=True)
def _restore_structlog() -> Iterator[None]:
    saved = structlog.get_config()
    yield
    structlog.configure(**saved)


@contextlib.contextmanager
def capture_all_levels() -> Iterator[list[dict]]:
    structlog.configure(wrapper_class=structlog.BoundLogger)
    with capture_logs() as logs:
        structlog.get_logger().debug("capture_all_levels_probe")
        assert logs and logs[-1]["event"] == "capture_all_levels_probe"
        logs.pop()
        yield logs


def _store(tmp_path) -> MemoryStore:
    pytest.importorskip("chromadb")
    s = MemoryStore(persist_dir=str(tmp_path))
    s.load()
    assert s.loaded
    return s


async def _seed(store: MemoryStore, owner: str, obj: str, source: str = "explicit_statement") -> None:
    await store.store_triple("user", "owns", obj, 0.9, source, owner=owner)


def _contents(export: dict, collection: str) -> list[str]:
    return [e["content"] for e in export[collection]]


# ── Test 1: export is owner scoped ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_is_owner_scoped(tmp_path) -> None:
    store = _store(tmp_path)
    await _seed(store, "a", "a red bicycle")
    await _seed(store, "b", "a blue bicycle")

    a = await store.export(owner="a")
    assert any("red bicycle" in c for c in _contents(a, "profile"))
    assert not any("blue bicycle" in c for c in _contents(a, "profile"))

    b = await store.export(owner="b")
    assert any("blue bicycle" in c for c in _contents(b, "profile"))
    assert not any("red bicycle" in c for c in _contents(b, "profile"))


@pytest.mark.asyncio
async def test_export_shape_and_stored_metadata_only(tmp_path) -> None:
    store = _store(tmp_path)
    await _seed(store, "a", "a red bicycle", source="explicit_statement")
    await _seed(store, "a", "a helmet", source="behavioral_inference")
    await _seed(store, "a", "a bell", source="working")

    export = await store.export(owner="a")
    assert set(export) == {"profile", "episodic", "working", "truncated"}
    assert len(export["profile"]) == 1 and len(export["episodic"]) == 1 and len(export["working"]) == 1

    profile = export["profile"][0]
    assert set(profile) >= {"id", "collection", "content", "subject", "predicate", "object", "confidence", "source", "timestamp"}
    assert profile["collection"] == "profile" and profile["source"] == "explicit_statement"
    assert "expires_at" not in profile
    episodic = export["episodic"][0]
    assert episodic["collection"] == "episodic" and isinstance(episodic["expires_at"], float)


# ── Tests 2, 3, 9: delete-all removes the owner's memory, immediately, only theirs ─


@pytest.mark.asyncio
async def test_delete_all_removes_every_collection_immediately(tmp_path) -> None:
    store = _store(tmp_path)
    await _seed(store, "a", "a red bicycle", "explicit_statement")
    await _seed(store, "a", "a helmet", "behavioral_inference")
    await _seed(store, "a", "a bell", "working")

    counts = await store.delete_all(owner="a")
    assert counts == {"profile": 1, "episodic": 1, "working": 1}

    export = await store.export(owner="a")  # no sleep: response means done
    assert export == {"profile": [], "episodic": [], "working": [], "truncated": []}


@pytest.mark.asyncio
async def test_delete_all_for_a_leaves_b_untouched(tmp_path) -> None:
    store = _store(tmp_path)
    await _seed(store, "a", "a red bicycle")
    await _seed(store, "a", "a helmet", "behavioral_inference")
    await _seed(store, "b", "a blue bicycle")
    await _seed(store, "b", "a bell", "behavioral_inference")

    await store.delete_all(owner="a")

    assert await store.export(owner="a") == {"profile": [], "episodic": [], "working": [], "truncated": []}
    b = await store.export(owner="b")
    assert _contents(b, "profile") == ["user owns a blue bicycle"]
    assert _contents(b, "episodic") == ["user owns a bell"]
    assert "user owns a blue bicycle" in await store.query_relevant("bicycle", owner="b")


# ── Test 4: deleted memory does not come back from a query ───────────────────


@pytest.mark.asyncio
async def test_deleted_fact_absent_from_query(tmp_path) -> None:
    store = _store(tmp_path)
    await _seed(store, "a", DELETED_SENTINEL)
    assert any(DELETED_SENTINEL in r for r in await store.query_relevant("what do I own", owner="a"))

    await store.delete_all(owner="a")
    assert await store.query_relevant("what do I own", owner="a") == []


@pytest.mark.asyncio
async def test_delete_entry_is_owner_scoped(tmp_path) -> None:
    store = _store(tmp_path)
    await _seed(store, "a", "a red bicycle")
    await _seed(store, "b", "a blue bicycle")
    a_id = (await store.export(owner="a"))["profile"][0]["id"]
    b_id = (await store.export(owner="b"))["profile"][0]["id"]

    # b cannot delete a's entry, even knowing its id
    assert await store.delete_entry(owner="b", entry_id=a_id) is False
    assert _contents(await store.export(owner="a"), "profile") == ["user owns a red bicycle"]

    assert await store.delete_entry(owner="a", entry_id=a_id) is True
    assert await store.export(owner="a") == {"profile": [], "episodic": [], "working": [], "truncated": []}
    assert await store.delete_entry(owner="a", entry_id=a_id) is False
    assert _contents(await store.export(owner="b"), "profile") == ["user owns a blue bicycle"]
    assert b_id != a_id


# ── Test 5: deleted memory never reaches cognition ───────────────────────────


def _mount(app, memory: MemoryStore, llm, tmp_path) -> None:
    from app.api.cognition_route import get_bridge, get_client, get_memory
    from app.spatial.anchor_registry import AnchorRegistry
    from app.spatial.gesture_anchor_bridge import GestureAnchorBridge

    app.dependency_overrides[get_client] = lambda: llm
    app.dependency_overrides[get_memory] = lambda: memory
    app.dependency_overrides[get_bridge] = lambda: GestureAnchorBridge(
        AnchorRegistry(db_path=tmp_path / "a.db")
    )


def _llm_stub() -> MagicMock:
    llm = MagicMock()
    llm.complete = AsyncMock(
        return_value=CognitionResponse(symbolic_inference="calm", natural_language_response="ok")
    )
    return llm


@pytest.mark.asyncio
async def test_deleted_memory_never_reaches_cognition(tmp_path) -> None:
    from app.main import app

    store = _store(tmp_path)
    await _seed(store, "a", DELETED_SENTINEL)
    llm = _llm_stub()
    _mount(app, store, llm, tmp_path)
    try:
        client = TestClient(app)
        headers = {"X-Aria-Owner": "a"}

        # Before deletion the fact is retrieved on the SAME turn it is needed.
        r = client.post("/api/cognition", json={"message": "what do I own"}, headers=headers)
        assert r.status_code == 200
        kwargs = llm.complete.call_args.kwargs
        assert any(DELETED_SENTINEL in m for m in kwargs["episodic_memory"])
        assert any(DELETED_SENTINEL in m for m in r.json()["episodic_memory"])

        assert client.delete("/api/memory", headers=headers).status_code == 200

        llm.complete.reset_mock()
        r = client.post("/api/cognition", json={"message": "what do I own"}, headers=headers)
        assert r.status_code == 200
        kwargs = llm.complete.call_args.kwargs
        assert DELETED_SENTINEL not in repr(kwargs)
        assert kwargs["episodic_memory"] == []
        assert r.json()["episodic_memory"] == []
    finally:
        app.dependency_overrides.clear()


# ── Routes: export/delete are owner scoped from the verified header only ─────


@pytest.mark.asyncio
async def test_routes_export_and_delete_use_verified_owner_only(tmp_path) -> None:
    from app.main import app

    store = _store(tmp_path)
    await _seed(store, "a", "a red bicycle")
    await _seed(store, "b", "a blue bicycle")
    _mount(app, store, _llm_stub(), tmp_path)
    try:
        client = TestClient(app)
        as_b = {"X-Aria-Owner": "b"}

        # Test 8: client-supplied owner in query/body must not cross tenants.
        r = client.get("/api/memory/export?owner=a", headers=as_b)
        assert r.status_code == 200
        assert _contents(r.json(), "profile") == ["user owns a blue bicycle"]

        r = client.request("DELETE", "/api/memory?owner=a", headers=as_b, json={"owner": "a"})
        assert r.status_code == 200
        assert r.json()["deleted"] == {"profile": 1, "episodic": 0, "working": 0}

        # a is untouched; b is gone. Test 9: visible immediately.
        assert _contents(client.get("/api/memory/export", headers={"X-Aria-Owner": "a"}).json(), "profile") == ["user owns a red bicycle"]
        assert client.get("/api/memory/export", headers=as_b).json() == {"profile": [], "episodic": [], "working": [], "truncated": []}

        # single-entry delete: b cannot delete a's entry by id → 404, a unchanged
        a_id = client.get("/api/memory/export", headers={"X-Aria-Owner": "a"}).json()["profile"][0]["id"]
        assert client.delete(f"/api/memory/{a_id}", headers=as_b).status_code == 404
        assert client.delete(f"/api/memory/{a_id}", headers={"X-Aria-Owner": "a"}).status_code == 200
        assert client.delete(f"/api/memory/{a_id}", headers={"X-Aria-Owner": "a"}).status_code == 404
    finally:
        app.dependency_overrides.clear()


# ── Test 10: S2 privacy regression during export/delete ──────────────────────


@pytest.mark.asyncio
async def test_export_and_delete_do_not_log_memory_content(tmp_path) -> None:
    from app.main import app

    store = _store(tmp_path)
    await _seed(store, "a", PRIVATE_SENTINEL)
    _mount(app, store, _llm_stub(), tmp_path)
    try:
        client = TestClient(app)
        headers = {"X-Aria-Owner": "a"}
        with capture_all_levels() as logs:
            assert client.get("/api/memory/export", headers=headers).status_code == 200
            assert client.delete("/api/memory", headers=headers).status_code == 200
        rendered = "\n".join(repr(e) for e in logs)
        assert PRIVATE_SENTINEL not in rendered
        deleted = [e for e in logs if e.get("event") == "memory deleted"]
        assert deleted and deleted[0].get("profile") == 1
    finally:
        app.dependency_overrides.clear()


# ── Test 11: Chroma working memory is write-only for cognition, but delete-all clears it ─


@pytest.mark.asyncio
async def test_working_collection_cleared_by_delete_all(tmp_path) -> None:
    store = _store(tmp_path)
    await _seed(store, "a", "a bell", source="working")
    assert len((await store.export(owner="a"))["working"]) == 1
    await store.delete_all(owner="a")
    assert (await store.export(owner="a"))["working"] == []


# ── Test 12: backend failure → non-2xx, no content in logs ───────────────────


def test_export_and_delete_return_503_when_store_unavailable(tmp_path) -> None:
    from app.main import app

    store = MemoryStore(persist_dir=str(tmp_path))  # never load()ed
    assert not store.loaded
    _mount(app, store, _llm_stub(), tmp_path)
    try:
        client = TestClient(app)
        headers = {"X-Aria-Owner": "a"}
        with capture_all_levels() as logs:
            assert client.get("/api/memory/export", headers=headers).status_code == 503
            assert client.delete("/api/memory", headers=headers).status_code == 503
            assert client.delete("/api/memory/some-id", headers=headers).status_code == 503
        assert any(e.get("event") == "memory store unavailable" for e in logs)
    finally:
        app.dependency_overrides.clear()


# ── Review P2: a turn already in flight cannot re-persist after delete-all ───


@pytest.mark.asyncio
async def test_in_flight_turn_does_not_repersist_after_delete(tmp_path) -> None:
    from app.main import app
    from app.models.schemas import WorldModelTriple, WorldModelUpdate

    store = _store(tmp_path)
    await _seed(store, "a", DELETED_SENTINEL)

    llm = MagicMock()

    async def _complete(**kwargs):
        # The user clicks "delete all" while this turn is still generating.
        await store.delete_all(owner="a")
        return CognitionResponse(
            symbolic_inference="calm",
            natural_language_response="ok",
            world_model_update=WorldModelUpdate(
                triple=WorldModelTriple(subject="user", predicate="owns", object=DELETED_SENTINEL),
                confidence=0.9,
                source="explicit_statement",
            ),
        )

    llm.complete = AsyncMock(side_effect=_complete)
    _mount(app, store, llm, tmp_path)
    try:
        with capture_all_levels() as logs:
            r = TestClient(app).post(
                "/api/cognition", json={"message": "what do I own"}, headers={"X-Aria-Owner": "a"}
            )
        assert r.status_code == 200
        assert await store.export(owner="a") == {"profile": [], "episodic": [], "working": [], "truncated": []}
        assert any(e.get("event") == "fact-write suppressed after delete" for e in logs)
        assert DELETED_SENTINEL not in "\n".join(repr(e) for e in logs)
    finally:
        app.dependency_overrides.clear()


# ── Review P3: export reports which collections hit the limit ───────────────


@pytest.mark.asyncio
async def test_export_flags_truncated_collections(tmp_path, monkeypatch) -> None:
    import app.cognition.memory as mem_mod

    store = _store(tmp_path)
    await _seed(store, "a", "a red bicycle")
    await _seed(store, "a", "a green bicycle")
    export = await store.export(owner="a")
    assert export["truncated"] == []

    monkeypatch.setattr(mem_mod, "MEMORY_EXPORT_LIMIT", 1)
    export = await store.export(owner="a")
    assert len(export["profile"]) == 1
    assert export["truncated"] == ["profile"]


# ── API-6: the new routes declare typed response models ─────────────────────


def test_memory_control_routes_declare_response_models() -> None:
    from fastapi.routing import APIRoute
    from pydantic import BaseModel

    from app.main import app

    want = {
        ("GET", "/api/memory/export"),
        ("DELETE", "/api/memory"),
        ("DELETE", "/api/memory/{entry_id}"),
    }
    seen = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                if (method, route.path) in want:
                    model = route.response_model
                    assert isinstance(model, type) and issubclass(model, BaseModel), (
                        f"{method} {route.path} response_model is {model!r}, want a pydantic model (API-6)"
                    )
                    seen.add((method, route.path))
    assert seen == want


# ── Review P2/P3: export pages with `offset`; exact-limit is not "truncated" ─


@pytest.mark.asyncio
async def test_export_pages_with_offset_and_exact_limit_not_truncated(tmp_path, monkeypatch) -> None:
    import app.cognition.memory as mem_mod

    store = _store(tmp_path)
    for obj in ("a red bicycle", "a green bicycle", "a blue bicycle"):
        await _seed(store, "a", obj)
    monkeypatch.setattr(mem_mod, "MEMORY_EXPORT_LIMIT", 2)

    page0 = await store.export(owner="a", offset=0)
    assert len(page0["profile"]) == 2 and page0["truncated"] == ["profile"]
    page1 = await store.export(owner="a", offset=2)
    assert len(page1["profile"]) == 1 and page1["truncated"] == []
    assert {e["id"] for e in page0["profile"]}.isdisjoint({e["id"] for e in page1["profile"]})

    # exactly at the limit → nothing left → not truncated
    monkeypatch.setattr(mem_mod, "MEMORY_EXPORT_LIMIT", 3)
    exact = await store.export(owner="a")
    assert len(exact["profile"]) == 3 and exact["truncated"] == []


def test_export_route_accepts_only_non_negative_int_offset(tmp_path) -> None:
    from app.main import app

    store = _store(tmp_path)
    _mount(app, store, _llm_stub(), tmp_path)
    try:
        client = TestClient(app)
        headers = {"X-Aria-Owner": "a"}
        assert client.get("/api/memory/export?offset=0", headers=headers).status_code == 200
        assert client.get("/api/memory/export?offset=500", headers=headers).status_code == 200
        assert client.get("/api/memory/export?offset=-1", headers=headers).status_code == 422
        assert client.get("/api/memory/export?offset=abc", headers=headers).status_code == 422
    finally:
        app.dependency_overrides.clear()


# ═════════════════════════════════════════════════════════════════════════════
# S3.1 — delete-all is linearizable with concurrent writes for the same owner
# ═════════════════════════════════════════════════════════════════════════════


CONCURRENT_SENTINEL = "CONCURRENT_DELETE_SENTINEL_4812"
HOOK_TIMEOUT = 1.0  # bounds a wait whose expected outcome (with the fix) is "never"


class _CollectionProxy:
    """Wraps a real ChromaDB collection so a test can run a hook exactly once
    at the moment a delete has ENUMERATED the owner's ids (the ``where`` get)
    but has not yet deleted them — the window the S3 report left open."""

    def __init__(self, real, on_enumerate=None):
        self._real = real
        self._on_enumerate = on_enumerate

    def __getattr__(self, name):
        return getattr(self._real, name)

    def get(self, *args, **kwargs):
        result = self._real.get(*args, **kwargs)
        hook, self._on_enumerate = self._on_enumerate, None
        if hook is not None and "where" in kwargs:
            hook()
        return result


def _run_in_thread(fn, *args, **kwargs):
    done = threading.Event()
    box: dict[str, object] = {}

    def target():
        try:
            box["result"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — surfaced by the test
            box["error"] = exc
        finally:
            done.set()

    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t, done, box


# ── Test 1: the exact old race, forced deterministically ─────────────────────


@pytest.mark.asyncio
async def test_write_that_overlaps_delete_cannot_survive(tmp_path) -> None:
    store = _store(tmp_path)
    await _seed(store, "a", "an old fact")
    turn_gen = store.deletion_generation("a")  # a turn captured this before retrieving

    writer: dict[str, object] = {}

    def late_write_from_old_turn():
        # Runs on its own thread the instant the delete has enumerated ids.
        _t, done, box = _run_in_thread(
            store._store_triple_sync,
            "user", "owns", CONCURRENT_SENTINEL, 0.9, "explicit_statement", "a",
            expected_generation=turn_gen,
        )
        writer["done"], writer["box"] = done, box
        # With the fix the writer is held out until the delete finishes, so this
        # wait times out; without the fix it completes and the doc lands in the
        # gap between enumerate and delete.
        done.wait(HOOK_TIMEOUT)

    store._profile = _CollectionProxy(store._profile, on_enumerate=late_write_from_old_turn)

    counts = await store.delete_all(owner="a")
    assert counts["profile"] == 1
    assert writer["done"].wait(HOOK_TIMEOUT), "late writer never finished"  # type: ignore[union-attr]
    assert "error" not in writer["box"], writer["box"]  # type: ignore[operator]
    assert writer["box"]["result"] is False, "old-turn write must report it was dropped"  # type: ignore[index]

    # Test 9: immediately, no sleeps.
    assert await store.export(owner="a") == {"profile": [], "episodic": [], "working": [], "truncated": []}
    assert await store.query_relevant("what do I own", owner="a") == []


# ── Tests 2 + 10: overlapping cognition turn cannot repersist; S2 logs ───────


@pytest.mark.asyncio
async def test_overlapping_turn_cannot_repersist_after_delete(tmp_path) -> None:
    from app.main import app
    from app.models.schemas import WorldModelTriple, WorldModelUpdate

    store = _store(tmp_path)
    await _seed(store, "a", "an old fact")

    route_stored = threading.Event()
    real_store_sync = store._store_triple_sync

    def tracking_store_sync(*args, **kwargs):
        try:
            return real_store_sync(*args, **kwargs)
        finally:
            route_stored.set()

    store._store_triple_sync = tracking_store_sync  # type: ignore[method-assign]

    delete_done = threading.Event()
    enumerated = threading.Event()
    delete_box: dict[str, object] = {}

    def start_delete_now():
        # Delete-all begins while the LLM "is generating"; when it has
        # enumerated ids it waits for the route's write to happen first (the
        # old race). With the fix that write cannot proceed until the delete
        # finishes, so the wait times out and the delete completes first.
        def gated():
            enumerated.set()
            route_stored.wait(HOOK_TIMEOUT)

        store._profile = _CollectionProxy(store._profile, on_enumerate=gated)
        _t, done, box = _run_in_thread(store._delete_all_sync, "a")
        delete_box["done"] = done
        delete_box["box"] = box

    llm = MagicMock()

    async def _complete(**kwargs):
        start_delete_now()
        # Do not let the turn reach its write until the delete is inside the
        # enumerate→delete window, so the old race is exercised every run.
        assert enumerated.wait(HOOK_TIMEOUT), "delete never reached the enumerate hook"
        return CognitionResponse(
            symbolic_inference="calm",
            natural_language_response="ok",
            world_model_update=WorldModelUpdate(
                triple=WorldModelTriple(subject="user", predicate="owns", object=CONCURRENT_SENTINEL),
                confidence=0.9,
                source="explicit_statement",
            ),
        )

    llm.complete = AsyncMock(side_effect=_complete)
    _mount(app, store, llm, tmp_path)
    try:
        with capture_all_levels() as logs:
            r = TestClient(app).post(
                "/api/cognition", json={"message": "what do I own"}, headers={"X-Aria-Owner": "a"}
            )
        assert r.status_code == 200
        assert delete_box["done"].wait(HOOK_TIMEOUT * 2), "delete never finished"  # type: ignore[union-attr]
        assert "error" not in delete_box["box"], delete_box["box"]  # type: ignore[operator]
        delete_done.set()

        export = await store.export(owner="a")
        assert CONCURRENT_SENTINEL not in repr(export) and export["profile"] == []
        assert await store.query_relevant("what do I own", owner="a") == []

        # A following turn must see nothing either.
        llm.complete = AsyncMock(
            return_value=CognitionResponse(symbolic_inference="calm", natural_language_response="ok")
        )
        r = TestClient(app).post(
            "/api/cognition", json={"message": "what do I own"}, headers={"X-Aria-Owner": "a"}
        )
        assert CONCURRENT_SENTINEL not in repr(llm.complete.call_args.kwargs)

        # Test 10: S2 — the fact text never reaches a log at any level.
        assert CONCURRENT_SENTINEL not in "\n".join(repr(e) for e in logs)
    finally:
        app.dependency_overrides.clear()


# ── Test 3: a genuinely new turn after the delete can still learn ────────────


@pytest.mark.asyncio
async def test_new_turn_after_delete_can_store(tmp_path) -> None:
    from app.main import app
    from app.models.schemas import WorldModelTriple, WorldModelUpdate

    store = _store(tmp_path)
    await _seed(store, "a", "an old fact")
    await store.delete_all(owner="a")

    llm = MagicMock()
    llm.complete = AsyncMock(
        return_value=CognitionResponse(
            symbolic_inference="calm",
            natural_language_response="ok",
            world_model_update=WorldModelUpdate(
                triple=WorldModelTriple(subject="user", predicate="owns", object="a brand new fact"),
                confidence=0.9,
                source="explicit_statement",
            ),
        )
    )
    _mount(app, store, llm, tmp_path)
    try:
        r = TestClient(app).post("/api/cognition", json={"message": "hi"}, headers={"X-Aria-Owner": "a"})
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()
    assert _contents(await store.export(owner="a"), "profile") == ["user owns a brand new fact"]


# ── Tests 4 + 8: owner-scoped coordination; B is unaffected by A's delete ────


@pytest.mark.asyncio
async def test_delete_for_a_does_not_block_b(tmp_path) -> None:
    store = _store(tmp_path)
    await _seed(store, "a", "a red bicycle")
    await _seed(store, "b", "a blue bicycle")

    release_a = threading.Event()
    a_paused = threading.Event()

    def hold_a_mid_delete():
        a_paused.set()
        release_a.wait(HOOK_TIMEOUT * 2)

    store._profile = _CollectionProxy(store._profile, on_enumerate=hold_a_mid_delete)
    _ta, a_done, a_box = _run_in_thread(store._delete_all_sync, "a")
    assert a_paused.wait(HOOK_TIMEOUT), "A's delete never reached the enumerate hook"

    # While A's delete holds A's mutation boundary, B writes, queries and exports.
    _tb, b_done, b_box = _run_in_thread(
        store._store_triple_sync, "user", "owns", "a bell", 0.9, "explicit_statement", "b",
    )
    assert b_done.wait(HOOK_TIMEOUT), "B's write was blocked behind A's delete"
    assert "error" not in b_box
    assert "user owns a bell" in await store.query_relevant("bell", owner="b")
    assert len((await store.export(owner="b"))["profile"]) == 2

    release_a.set()
    assert a_done.wait(HOOK_TIMEOUT)
    assert (await store.export(owner="a"))["profile"] == []
    assert len((await store.export(owner="b"))["profile"]) == 2


# ── Test 5: concurrent delete-all for one owner is safe and idempotent ───────


@pytest.mark.asyncio
async def test_concurrent_deletes_same_owner(tmp_path) -> None:
    store = _store(tmp_path)
    await _seed(store, "a", "a red bicycle")
    await _seed(store, "a", "a helmet", "behavioral_inference")
    gen0 = store.deletion_generation("a")

    threads = [_run_in_thread(store._delete_all_sync, "a") for _ in range(2)]
    for _t, done, box in threads:
        assert done.wait(HOOK_TIMEOUT)
        assert "error" not in box, box
        assert set(box["result"]) == {"profile", "episodic", "working"}  # type: ignore[arg-type]
    total = sum(box["result"]["profile"] + box["result"]["episodic"] for _t, _d, box in threads)  # type: ignore[index]
    assert total == 2, "each document is deleted exactly once"
    assert store.deletion_generation("a") == gen0 + 2
    assert (await store.export(owner="a"))["profile"] == []


# ── Test 6: delete-by-id uses the same boundary ──────────────────────────────


@pytest.mark.asyncio
async def test_write_overlapping_delete_entry_cannot_survive(tmp_path) -> None:
    store = _store(tmp_path)
    await _seed(store, "a", "an old fact")
    entry_id = (await store.export(owner="a"))["profile"][0]["id"]
    turn_gen = store.deletion_generation("a")

    writer: dict[str, object] = {}

    def late_write():
        _t, done, box = _run_in_thread(
            store._store_triple_sync,
            "user", "owns", CONCURRENT_SENTINEL, 0.9, "explicit_statement", "a",
            expected_generation=turn_gen,
        )
        writer["done"], writer["box"] = done, box
        done.wait(HOOK_TIMEOUT)

    store._profile = _CollectionProxy(store._profile, on_enumerate=late_write)
    assert await store.delete_entry(owner="a", entry_id=entry_id) is True
    assert writer["done"].wait(HOOK_TIMEOUT)  # type: ignore[union-attr]
    assert "error" not in writer["box"], writer["box"]  # type: ignore[operator]
    assert writer["box"]["result"] is False  # type: ignore[index]
    assert (await store.export(owner="a"))["profile"] == []


# ── Test 7: generation is monotonic and never loses a delete ─────────────────


@pytest.mark.asyncio
async def test_generation_monotonic_under_concurrent_delete_and_write(tmp_path) -> None:
    store = _store(tmp_path)
    await _seed(store, "a", "seed")
    gen0 = store.deletion_generation("a")
    observed: list[int] = []
    lock = threading.Lock()

    def delete_and_observe():
        store._delete_all_sync("a")
        with lock:
            observed.append(store.deletion_generation("a"))

    def write():
        store._store_triple_sync("user", "owns", "x", 0.9, "explicit_statement", "a")

    workers = [_run_in_thread(delete_and_observe) for _ in range(6)] + [_run_in_thread(write) for _ in range(6)]
    for _t, done, box in workers:
        assert done.wait(HOOK_TIMEOUT)
        assert "error" not in box, box
    assert store.deletion_generation("a") == gen0 + 6
    assert observed == sorted(observed)


# ── Lock registry lifecycle: nothing lingers once mutations finish ───────────


@pytest.mark.asyncio
async def test_owner_lock_registry_does_not_leak(tmp_path) -> None:
    store = _store(tmp_path)
    for owner in ("a", "b", "c"):
        await _seed(store, owner, "a fact")
        await store.delete_all(owner=owner)
        await store.clear_working(owner=owner)
    assert store._owner_locks.active() == 0


# ── store_triple reports False when the storage write itself failed ─────────


@pytest.mark.asyncio
async def test_store_triple_reports_false_when_chroma_write_fails(tmp_path) -> None:
    store = _store(tmp_path)

    class _Broken:
        def get(self, *a, **kw):
            return {"ids": []}

        def add(self, *a, **kw):
            raise RuntimeError("disk full")

    store._profile = _Broken()  # type: ignore[assignment]
    with capture_all_levels() as logs:
        stored = await store.store_triple("user", "owns", "x", 0.9, "explicit_statement", owner="a")
    assert stored is False
    assert any(e.get("event") == "store_triple failed" and e.get("error_type") == "RuntimeError" for e in logs)
