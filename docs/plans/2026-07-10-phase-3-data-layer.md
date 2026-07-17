# Phase 3 — Data Layer (owner keying, request-scoped services, off-loop) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make ARIA's data layer multi-user-ready and non-blocking without changing single-user behavior: key all persisted data (memory, anchors) by an `owner`, manage the expensive clients as lifespan singletons injected per request, and move blocking ChromaDB/SQLite work off the FastAPI event loop.

**Architecture:** Introduce one seam — `get_current_owner()` — that returns a constant `DEFAULT_OWNER="local"` today and will read the auth identity in Phase 4. Thread `owner` through `MemoryStore` (Chroma metadata + `where` filters, owner-keyed doc IDs) and `AnchorRegistry` (new SQLite `owner` column via an idempotent migration). Replace the module-global lazy singletons in `cognition_route.py` with services created once in the FastAPI `lifespan` (`app.state`) and injected via `Depends`. Wrap the synchronous Chroma/SQLite calls in `starlette.concurrency.run_in_threadpool`.

**Tech Stack:** Python 3.13, FastAPI, ChromaDB (PersistentClient), SQLite (`sqlite3`), pytest / pytest-asyncio. Python binary: `/Users/sucheetboppana/miniconda-arm64/bin/python3`. Test cmd base: `PYTHONPATH=$(pwd) python3 -m pytest tests/ -v` from `backend/`.

**Risk:** HIGH — touches runtime memory/anchor behavior + existing on-disk data (`backend/data/anchors.db`, `backend/memory/chroma.sqlite3`). Every task is TDD (red → green → commit). After the code lands: backend tests → your manual walk-through → Playwright re-verify (verify-twice) before merge. All changes are **additive with a `"local"` default**, so a rollback is a clean revert and old data keeps working.

---

## Guardrails (read first)

- **Do not** move `SOUL.md`; **do not** touch the `ignore_errors` mypy config for `app.cognition.memory`.
- **Backwards compatibility:** existing anchors default to `owner="local"`; existing Chroma docs are backfilled to `owner="local"` on load. Nothing pre-existing is lost.
- **Isolation invariant** (the property every owner test asserts): data written under owner A is never returned to owner B.
- Commit after every green task. Keep `ruff check .` and `mypy app tests` green throughout.

---

## Task 1: Owner seam (config + dependency)

**Files:** Modify `app/config.py`; Create `app/api/deps.py`; Test `tests/test_deps.py`

- **Step 1 (red):** `test_deps.py` — `get_current_owner()` returns `settings.DEFAULT_OWNER` ("local"). Run → fails (module missing).
- **Step 2 (green):** add `DEFAULT_OWNER: str = "local"` to `Settings`. Create `app/api/deps.py`:
  ```python
  from app.config import settings
  def get_current_owner() -> str:  # Phase 4 swaps this for the authenticated identity
      return settings.DEFAULT_OWNER
  ```
- **Step 3:** run test → pass. **Commit:** `feat(data): add owner seam (DEFAULT_OWNER + get_current_owner)`

## Task 2: MemoryStore owner-scoping + backfill migration

**Files:** Modify `app/cognition/memory.py`; Test `tests/test_memory.py`

Changes:
- `_triple_id(owner, subject, predicate, obj)` — **owner is part of the hash** (so the same triple for two owners gets distinct IDs → true isolation).
- `store_triple(..., owner)` — add `"owner": owner` to `metadata`.
- `query_relevant(context, owner, n_results)` — pass `where={"owner": owner}` to `collection.query`.
- `get_profile_facts(owner, n)` — `self._profile.get(where={"owner": owner}, limit=n)`.
- `clear_working(owner)` — delete only `where={"owner": owner}` ids.
- New `_migrate_owner_metadata()` called at the end of `load()`: for each collection, `get()` all docs; any doc whose metadata lacks `"owner"` is **re-keyed** to the owner-scoped id and rewritten with `owner=DEFAULT_OWNER` (delete old id, add new) so old and new writes never duplicate. Idempotent.

- **Step 1 (red):** add `test_two_owners_isolated` — store a triple under owner "a", query under owner "b" → `[]`; query under "a" → returns it. Run → fails.
- **Step 2 (green):** implement the owner-keyed id + metadata + `where` filters.
- **Step 3 (red):** add `test_backfill_assigns_local_owner` — seed a collection with a doc that has no `owner` metadata (simulate legacy), call `load()`, assert it's now queryable under `owner="local"`. Run → fails.
- **Step 4 (green):** implement `_migrate_owner_metadata()`; run both tests → pass.
- **Step 5:** update the existing `test_memory.py` cases to pass `owner="local"`. Run full file → pass.
- **Commit:** `feat(memory): key ChromaDB memory by owner + backfill legacy docs`

## Task 3: AnchorRegistry owner column + SQLite migration

**Files:** Modify `app/spatial/anchor_registry.py`; Test `tests/test_spatial_anchoring.py`

Changes:
- In `_init_db()`, after `CREATE TABLE IF NOT EXISTS`, run an **idempotent migration**: `PRAGMA table_info(anchors)`; if no `owner` column, execute
  `ALTER TABLE anchors ADD COLUMN owner TEXT NOT NULL DEFAULT 'local'`
  (SQLite backfills existing rows to `'local'` atomically).
- `register_anchor(pointing_vector, label, owner)` → INSERT includes `owner`.
- `get_anchor(anchor_id, owner)`, `list_anchors(owner)`, `delete_anchor(anchor_id, owner)`, `update_anchor(anchor_id, label, owner)` → every query gains `AND owner = ?`.

- **Step 1 (red):** `test_anchors_owner_isolated` — register under "a", `list_anchors("b")` is empty, `list_anchors("a")` has it; `delete_anchor(id, "b")` returns False (can't delete another owner's). Run → fails.
- **Step 2 (green):** implement column + migration + filtered queries.
- **Step 3 (red):** `test_migration_backfills_existing_db` — build a DB row via the OLD schema (no owner column), re-open the registry, assert the row is now `owner="local"` and listable. Run → fails.
- **Step 4 (green):** confirm the `_init_db` migration handles it; run → pass.
- **Step 5:** update existing anchor tests to pass `owner="local"`. Run → pass.
- **Commit:** `feat(anchors): add owner column + idempotent SQLite migration`

## Task 4: GestureAnchorBridge threads owner

**Files:** Modify `app/spatial/gesture_anchor_bridge.py`; Test `tests/test_gesture_anchor_bridge.py`

- `on_gesture_event(..., owner)` passes `owner` to `register_anchor` and to the `list_anchors(owner)` calls inside `_two_nearest_anchor_ids`/`_nearest_anchor_id` (make those take `owner`).
- **Step 1 (red):** `test_point_registers_under_owner` — POINT gesture with owner "a" creates an anchor listable only under "a". **Step 2 (green):** thread owner. **Step 3:** update existing bridge tests. **Commit:** `feat(spatial): scope gesture-anchor bridge by owner`

## Task 5: Make LLMClient stateless (kill cross-session leak)

**Files:** Modify `app/cognition/llm.py:94,109,151`; Test `tests/test_llm_routing.py`

- Remove `self._last_response`. The local/Ollama fallback continuity comes from `conversation_history` (already passed into `complete()`), not shared instance state. `_handle_local` takes the last assistant turn from `conversation_history` instead of `self._last_response`.
- **Step 1 (red):** `test_no_cross_session_state` — two sequential `complete()` calls with different histories don't bleed the first's reply into the second's local path. **Step 2 (green):** remove the field, derive from history. **Step 3:** run `test_llm_routing.py` → pass. **Commit:** `fix(cognition): make LLMClient stateless (no cross-session _last_response)`

## Task 6: Lifespan singletons + Depends (retire module globals)

**Files:** Modify `app/main.py` (lifespan), `app/api/cognition_route.py`; Test `tests/test_cognition.py`

- In `lifespan`: construct `LLMClient(settings.ANTHROPIC_API_KEY)`, `MemoryStore(...)` + `.load()`, `AnchorRegistry()`, `GestureAnchorBridge(registry)` **once** and store on `app.state` (`app.state.llm`, `.memory`, `.registry`, `.bridge`).
- Replace `get_client/get_memory/get_bridge/get_registry` module-global functions with `Depends` that read `request.app.state` (e.g. `def get_memory(request: Request) -> MemoryStore: return request.app.state.memory`). Delete the `_client/_memory/_bridge` globals.
- Route handlers take `memory: MemoryStore = Depends(get_memory)`, etc.
- **Step 1 (red):** `test_services_from_app_state` (TestClient) — hitting `/api/cognition` uses the app.state instances; assert a single MemoryStore instance is reused across two requests (patch/inspect). **Step 2 (green):** wire lifespan + Depends. **Step 3:** run `test_cognition.py` + `test_anchor_routes.py` → pass. **Commit:** `refactor(api): lifespan-managed services via Depends (drop module globals)`

## Task 7: Move blocking Chroma/SQLite off the event loop

**Files:** Modify `app/cognition/memory.py`, `app/api/cognition_route.py`; Test `tests/test_cognition.py`

- Keep the public `MemoryStore` methods `async`, but run the blocking body via `await run_in_threadpool(self._sync_impl, ...)` (`from starlette.concurrency import run_in_threadpool`).
- In `cognition_route.py`, the synchronous anchor calls (`bridge.on_gesture_event`, `registry.list_anchors`, `registry.delete_anchor`) are awaited via `run_in_threadpool(...)`.
- **Step 1 (red):** `test_cognition_does_not_block_loop` — fire two concurrent `/api/cognition` requests against a `TestClient`/async client with a deliberately slow stubbed embed; assert they interleave (total ≈ max, not sum). **Step 2 (green):** wrap in `run_in_threadpool`. **Step 3:** run → pass. **Commit:** `perf(api): offload ChromaDB/SQLite off the FastAPI event loop`

## Task 8: Wire owner through the routes

**Files:** Modify `app/api/cognition_route.py`; Test `tests/test_cognition.py`, `tests/test_anchor_routes.py`

- Every handler that reads/writes memory or anchors takes `owner: str = Depends(get_current_owner)` and passes it down: `/api/cognition` (store_triple, query_relevant, gesture bridge), `/api/anchors` GET/DELETE, `/api/memory/profile`, `/api/memory/episodic`, `DELETE /api/memory/working`.
- **Step 1 (red):** `test_endpoints_scope_by_owner` — anchors created via the cognition route are only listed by `/api/anchors` for the same owner. **Step 2 (green):** thread `Depends(get_current_owner)`. **Step 3:** run the API test files → pass. **Commit:** `feat(api): scope memory + anchor endpoints by owner`

## Task 9: Full verification (verify-twice)

1. **Backend gate:** from `backend/` — `ruff check . && mypy app tests && PYTHONPATH=$(pwd) python3 -m pytest tests/ -v` (all 234+ pass), and `make lint-go` unaffected. Confirm `make test-backend` green.
2. **Data migration smoke:** back up `backend/data/anchors.db` + `backend/memory/`, start the stack, confirm existing anchors still render and existing memory still recalls (they now carry `owner="local"`).
3. **Manual walk-through** (I hand you numbered steps): create an anchor by pointing, delete it, have a short conversation that stores a fact, confirm recall.
4. **Playwright re-verify:** re-run each manual step in Playwright to confirm twice.
- **Commit:** none (verification only). Then open the Phase 3 PR → `integration`.

---

## Rollback

Every change is additive behind `owner="local"`. If anything regresses: revert the PR; the `owner` SQLite column and Chroma metadata are ignored by the old code, and the data remains valid. No destructive migration is performed (no drops, no type changes).

## Out of scope (later phases)

- Real auth identity feeding `get_current_owner()` → **Phase 4**.
- Rate limiting, per-session WebSocket broadcast scoping → **Phase 4**.
- Deploy/containerization → **Phase 5**.
