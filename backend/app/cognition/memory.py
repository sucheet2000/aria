from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import structlog
from starlette.concurrency import run_in_threadpool

from app.config import settings

logger = structlog.get_logger()

PROFILE_COLLECTION = "aria_profile"
EPISODIC_COLLECTION = "aria_episodic"
WORKING_COLLECTION = "aria_working"

EPISODIC_TTL_DAYS = 30
SWEEP_INTERVAL_SECONDS = 3600

# Bounds one owner's export per collection so a response cannot grow without
# limit; ARIA stores at most one triple per cognition turn.
MEMORY_EXPORT_LIMIT = 500

# Stored metadata keys surfaced verbatim in an export (nothing is invented).
_EXPORT_METADATA_KEYS = (
    "subject", "predicate", "object", "confidence", "source", "timestamp", "expires_at",
)


class _OwnerLocks:
    """Per-owner mutual exclusion for storage mutations.

    One ``threading.Lock`` per owner, created on first use and dropped again
    when no thread holds or waits for it, so the registry never grows beyond
    the owners currently mutating. Different owners never contend. Locks are
    plain thread locks because every mutation runs in the threadpool; the
    asyncio loop never holds one, so there is nothing to deadlock against.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, tuple[threading.Lock, int]] = {}

    @contextmanager
    def held(self, owner: str) -> Iterator[None]:
        with self._guard:
            entry = self._locks.get(owner)
            if entry is None:
                lock, refs = threading.Lock(), 0
            else:
                lock, refs = entry
            self._locks[owner] = (lock, refs + 1)  # registered before blocking
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            with self._guard:
                _, refs = self._locks[owner]
                if refs <= 1:
                    del self._locks[owner]
                else:
                    self._locks[owner] = (lock, refs - 1)

    def active(self) -> int:
        with self._guard:
            return len(self._locks)


class MemoryStore:
    """
    Layered ChromaDB memory store, scoped by ``owner``.

    Concurrency (S3.1): every owner-initiated storage mutation — ``store_triple``,
    ``delete_all``, ``delete_entry``, ``clear_working`` — runs inside that
    owner's lock (the TTL sweep deletes already-expired documents without a
    lock; it only removes, so it cannot resurrect anything), and each delete bumps the owner's deletion generation while
    holding it. A cognition turn passes the generation it observed before
    retrieval as ``expected_generation``; the write is dropped, atomically with
    the check, if any delete completed in between. So a delete is an epoch
    boundary: writes ordered before it are deleted, writes from turns that
    started before it are dropped, and only turns that started after it can
    store. Reads are not serialised.

    SCALE-2 note (single-writer): the owner locks and the deletion generation
    are process-local. The guarantee holds for one replica; running the
    Python service with ``numReplicas > 1`` would need the generation counter
    and the mutual exclusion moved into the shared store.

    Deliberate asymmetry: ``delete_all`` and ``delete_entry`` bump the
    generation (any in-flight turn's write is dropped — conservative for
    privacy), while ``clear_working`` does not (it clears session scratch only
    and must not discard a concurrent turn's learned fact).

    Three collections:
      aria_profile  - stable user facts (permanent)
      aria_episodic - session events (30 day TTL)
      aria_working  - current session context (cleared on shutdown)

    Every document carries an ``owner`` metadata field and every read filters
    on it, so data written by one owner is never returned to another. Legacy
    documents (written before owners existed) are backfilled to DEFAULT_OWNER
    on load.

    The public methods are async but the blocking ChromaDB work runs via
    ``run_in_threadpool`` so it never blocks the FastAPI event loop.
    """

    def __init__(self, persist_dir: str | None = None) -> None:
        if persist_dir is None:
            persist_dir = str(Path(settings.DATA_DIR) / "memory")
        self._persist_dir = persist_dir
        self._client = None
        self._profile = None
        self._episodic = None
        self._working = None
        self._last_sweep: float = 0.0
        # Per-owner count of delete operations, only ever changed while that
        # owner's lock is held. A cognition turn captures it before retrieval
        # and its write is dropped (under the same lock) if it changed.
        self._deletion_gen: dict[str, int] = {}
        self._owner_locks = _OwnerLocks()

    def load(self) -> None:
        try:
            import chromadb
            Path(self._persist_dir).mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self._persist_dir)
            self._profile = self._client.get_or_create_collection(PROFILE_COLLECTION)
            self._episodic = self._client.get_or_create_collection(EPISODIC_COLLECTION)
            self._working = self._client.get_or_create_collection(WORKING_COLLECTION)
            self._migrate_owner_metadata()
            self._sweep_expired_sync()
            self._last_sweep = time.time()
            logger.info("memory store loaded",
                profile_count=self._profile.count(),
                episodic_count=self._episodic.count(),
            )
        except ImportError:
            logger.warning("chromadb not available, memory disabled")
        except Exception as e:
            logger.error("memory store failed to load", error_type=type(e).__name__, error=str(e)[:200])

    @property
    def loaded(self) -> bool:
        return self._client is not None

    def _triple_id(self, owner: str, subject: str, predicate: str, obj: str) -> str:
        text = f"{owner}:{subject.lower()}:{predicate.lower()}:{obj.lower()}"
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def _triple_text(self, subject: str, predicate: str, obj: str) -> str:
        return f"{subject} {predicate} {obj}"

    def _migrate_owner_metadata(self) -> None:
        """Backfill legacy documents (no ``owner`` metadata) to DEFAULT_OWNER.

        Re-keys each legacy doc to its owner-scoped id so later writes for the
        same triple update in place instead of creating a duplicate. Idempotent:
        docs that already carry an owner are skipped.
        """
        default = settings.DEFAULT_OWNER
        for coll in (self._profile, self._episodic, self._working):
            if coll is None:
                continue
            try:
                data = coll.get()
                ids = data["ids"]
                metas = data["metadatas"] or []
                docs = data["documents"] or []
                for i, meta in enumerate(metas):
                    if meta is None or "owner" in meta:
                        continue
                    old_id = ids[i]
                    new_meta = {**meta, "owner": default}
                    subject = str(meta.get("subject", ""))
                    predicate = str(meta.get("predicate", ""))
                    obj = str(meta.get("object", ""))
                    new_id = (
                        self._triple_id(default, subject, predicate, obj)
                        if subject
                        else old_id
                    )
                    if new_id != old_id:
                        coll.delete(ids=[old_id])
                        coll.add(ids=[new_id], documents=[docs[i]], metadatas=[new_meta])
                    else:
                        coll.update(ids=[old_id], metadatas=[new_meta])
            except Exception as e:
                logger.error("owner backfill failed", error_type=type(e).__name__, error=str(e)[:200])

    async def store_triple(
        self,
        subject: str,
        predicate: str,
        obj: str,
        confidence: float,
        source: str,
        owner: str | None = None,
        expected_generation: int | None = None,
    ) -> bool:
        """Persist a triple. Returns False when nothing was written because
        ``expected_generation`` no longer matches the owner's deletion
        generation (a delete completed since the caller observed it)."""
        if not self.loaded:
            return False
        owner = owner or settings.DEFAULT_OWNER
        return await run_in_threadpool(
            self._store_triple_sync, subject, predicate, obj, confidence, source, owner,
            expected_generation=expected_generation,
        )

    def _store_triple_sync(
        self,
        subject: str,
        predicate: str,
        obj: str,
        confidence: float,
        source: str,
        owner: str,
        expected_generation: int | None = None,
    ) -> bool:
        with self._owner_locks.held(owner):
            if (
                expected_generation is not None
                and self._deletion_gen.get(owner, 0) != expected_generation
            ):
                logger.info("fact-write suppressed after delete", owner=owner, source=source)
                return False
            return self._store_triple_locked(subject, predicate, obj, confidence, source, owner)

    def _store_triple_locked(
        self,
        subject: str,
        predicate: str,
        obj: str,
        confidence: float,
        source: str,
        owner: str,
    ) -> bool:
        """Write under the owner lock. Returns False if the storage call failed."""
        doc_id = self._triple_id(owner, subject, predicate, obj)
        text = self._triple_text(subject, predicate, obj)
        metadata = {
            "owner": owner,
            "subject": subject,
            "predicate": predicate,
            "object": obj,
            "confidence": confidence,
            "source": source,
            "timestamp": time.time(),
        }
        try:
            if source == "explicit_statement":
                collection = self._profile
                collection_name = PROFILE_COLLECTION
            elif source in ("behavioral_inference", "visual_inference"):
                collection = self._episodic
                collection_name = EPISODIC_COLLECTION
                now = time.time()
                metadata["expires_at"] = now + EPISODIC_TTL_DAYS * 86400
                if now - self._last_sweep > SWEEP_INTERVAL_SECONDS:
                    self._sweep_expired_sync()
                    self._last_sweep = now
            else:
                collection = self._working
                collection_name = WORKING_COLLECTION

            # S2: log the operation, never the fact — not even its content hash
            # (enumerable triples make a short hash guessable); ``chars`` is the
            # document length only.
            existing = collection.get(ids=[doc_id])
            if existing["ids"]:
                collection.update(ids=[doc_id], documents=[text], metadatas=[metadata])
                logger.info(
                    "memory updated",
                    collection=collection_name, source=source,
                    operation="update", chars=len(text),
                )
            else:
                collection.add(ids=[doc_id], documents=[text], metadatas=[metadata])
                logger.info(
                    "memory stored",
                    collection=collection_name, source=source,
                    operation="add", chars=len(text),
                )
        except Exception as e:
            logger.error(
                "store_triple failed",
                collection=collection_name, error_type=type(e).__name__,
                error=str(e)[:200],
            )
            return False
        return True

    async def query_relevant(
        self,
        context: str,
        owner: str | None = None,
        n_results: int = 5,
    ) -> list[str]:
        if not self.loaded:
            return []
        owner = owner or settings.DEFAULT_OWNER
        return await run_in_threadpool(self._query_relevant_sync, context, owner, n_results)

    def _query_relevant_sync(self, context: str, owner: str, n_results: int) -> list[str]:
        results: list[str] = []
        observed: list[dict[str, object]] = []
        now = time.time()
        started = time.monotonic()
        cutoff = settings.RECALL_MAX_DISTANCE
        try:
            for collection in [self._profile, self._episodic]:
                count = collection.count()
                if count == 0:
                    continue
                n_results_capped = min(n_results, count)
                response = collection.query(
                    query_texts=[context],
                    n_results=n_results_capped,
                    where={"owner": owner},
                    include=["documents", "metadatas", "distances"],
                )
                docs = response["documents"][0]
                metas = response["metadatas"][0]
                ids = response["ids"][0]
                distances_raw = response.get("distances")
                distances = distances_raw[0] if distances_raw else [None] * len(docs)
                for doc_id, doc, meta, distance in zip(ids, docs, metas, distances):
                    expires = meta.get("expires_at")
                    if expires and expires < now:
                        continue
                    # Fail open: only drop when a cutoff is active AND a real
                    # distance exceeds it. A missing/None distance keeps the fact.
                    dropped = (
                        cutoff > 0 and distance is not None and distance > cutoff
                    )
                    observed.append(
                        {"id": doc_id, "distance": distance, "kept": not dropped}
                    )
                    if dropped:
                        continue
                    results.append(doc)
        except Exception as e:
            logger.error(
                "query_relevant failed", error_type=type(e).__name__, error=str(e)[:200]
            )
        if observed:
            # ids are content hashes and distances are floats — no fact text.
            logger.debug(
                "recall distances", owner=owner, cutoff=cutoff, facts=observed
            )
        results = results[:n_results]
        # S2: query text and returned documents are never logged; counts only.
        # INFO so the per-turn recall count survives the production floor.
        logger.info(
            "memory query completed",
            owner=owner,
            query_chars=len(context),
            candidates=len(observed),
            results=len(results),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return results

    async def sweep_expired(self) -> int:
        if not self.loaded:
            return 0
        return await run_in_threadpool(self._sweep_expired_sync)

    def _sweep_expired_sync(self) -> int:
        if self._episodic is None:
            return 0
        now = time.time()
        try:
            expired = self._episodic.get(where={"expires_at": {"$lt": now}})
            ids = expired["ids"]
            if ids:
                self._episodic.delete(ids=ids)
            logger.info("episodic ttl sweep", swept=len(ids))
            return len(ids)
        except Exception as e:
            logger.error("sweep_expired failed", error_type=type(e).__name__, error=str(e)[:200])
            return 0

    async def clear_working(self, owner: str | None = None) -> None:
        owner = owner or settings.DEFAULT_OWNER
        if not self._working:
            return
        await run_in_threadpool(self._clear_working_sync, owner)

    def _clear_working_sync(self, owner: str) -> None:
        try:
            with self._owner_locks.held(owner):
                ids = self._working.get(where={"owner": owner})["ids"]
                if ids:
                    self._working.delete(ids=ids)
            logger.info("working memory cleared", owner=owner)
        except Exception as e:
            logger.error("clear_working failed", error_type=type(e).__name__, error=str(e)[:200])

    # ── owner data controls (S3): export / delete ───────────────────────────

    def _collections(self) -> list[tuple[str, object]]:
        return [
            ("profile", self._profile),
            ("episodic", self._episodic),
            ("working", self._working),
        ]

    def deletion_generation(self, owner: str | None = None) -> int:
        """How many delete operations ``owner`` has run; bumps on every delete."""
        return self._deletion_gen.get(owner or settings.DEFAULT_OWNER, 0)

    def _bump_deletion_generation(self, owner: str) -> None:
        # Caller holds the owner lock, so this read-modify-write is atomic.
        self._deletion_gen[owner] = self._deletion_gen.get(owner, 0) + 1

    async def export(self, owner: str | None = None, offset: int = 0) -> dict[str, object]:
        """Everything stored for ``owner``, grouped by collection, with the
        metadata ARIA actually persists. Each collection returns at most
        MEMORY_EXPORT_LIMIT entries starting at ``offset``; ``truncated`` lists
        the collections that have more beyond this page, so a caller pages by
        adding MEMORY_EXPORT_LIMIT to ``offset`` until it is empty. Owner is the
        verified identity from the edge; the request never chooses it."""
        owner = owner or settings.DEFAULT_OWNER
        if not self.loaded:
            return {"profile": [], "episodic": [], "working": [], "truncated": []}
        return await run_in_threadpool(self._export_sync, owner, max(0, offset))

    def _export_sync(self, owner: str, offset: int) -> dict[str, object]:
        by_label: dict[str, list[dict[str, object]]] = {}
        truncated: list[str] = []
        for label, coll in self._collections():
            # Fetch one extra row: its presence (not an exact-limit count) is
            # what marks the collection as having more pages.
            data = coll.get(  # type: ignore[attr-defined]
                where={"owner": owner},
                limit=MEMORY_EXPORT_LIMIT + 1,
                offset=offset,
                include=["documents", "metadatas"],
            )
            ids = data["ids"]
            metas = data["metadatas"] or []
            docs = data["documents"] or []
            if len(ids) > MEMORY_EXPORT_LIMIT:
                truncated.append(label)
                ids, docs, metas = ids[:MEMORY_EXPORT_LIMIT], docs[:MEMORY_EXPORT_LIMIT], metas[:MEMORY_EXPORT_LIMIT]
            entries: list[dict[str, object]] = []
            for doc_id, doc, meta in zip(ids, docs, metas):
                entry: dict[str, object] = {"id": doc_id, "collection": label, "content": doc}
                for key in _EXPORT_METADATA_KEYS:
                    if meta is not None and key in meta:
                        entry[key] = meta[key]
                entries.append(entry)
            by_label[label] = entries
        # S2: counts only, never the documents.
        logger.info(
            "memory exported",
            owner=owner,
            offset=offset,
            profile=len(by_label["profile"]),
            episodic=len(by_label["episodic"]),
            working=len(by_label["working"]),
            truncated=truncated,
        )
        out: dict[str, object] = dict(by_label)
        out["truncated"] = truncated
        return out

    async def delete_all(self, owner: str | None = None) -> dict[str, int]:
        """Delete every document ``owner`` has in every collection. Returns the
        per-collection counts. Synchronous: when this returns, the store no
        longer holds the data."""
        owner = owner or settings.DEFAULT_OWNER
        if not self.loaded:
            return {"profile": 0, "episodic": 0, "working": 0}
        return await run_in_threadpool(self._delete_all_sync, owner)

    def _delete_all_sync(self, owner: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self._owner_locks.held(owner):
            for label, coll in self._collections():
                ids = coll.get(where={"owner": owner}, include=[])["ids"]  # type: ignore[attr-defined]
                if ids:
                    coll.delete(ids=ids)  # type: ignore[attr-defined]
                counts[label] = len(ids)
            self._bump_deletion_generation(owner)
        logger.info("memory deleted", owner=owner, **counts)
        return counts

    async def delete_entry(self, owner: str | None, entry_id: str) -> bool:
        """Delete one document by id, only if it belongs to ``owner``."""
        owner = owner or settings.DEFAULT_OWNER
        if not self.loaded:
            return False
        return await run_in_threadpool(self._delete_entry_sync, owner, entry_id)

    def _delete_entry_sync(self, owner: str, entry_id: str) -> bool:
        with self._owner_locks.held(owner):
            for label, coll in self._collections():
                found = coll.get(ids=[entry_id], where={"owner": owner}, include=[])  # type: ignore[attr-defined]
                if found["ids"]:
                    coll.delete(ids=found["ids"])  # type: ignore[attr-defined]
                    self._bump_deletion_generation(owner)
                    logger.info("memory entry deleted", owner=owner, collection=label)
                    return True
        return False

    async def get_profile_facts(self, owner: str | None = None, n: int = 10) -> list[str]:
        if not self.loaded:
            return []
        owner = owner or settings.DEFAULT_OWNER
        return await run_in_threadpool(self._get_profile_facts_sync, owner, n)

    def _get_profile_facts_sync(self, owner: str, n: int) -> list[str]:
        if not self._profile.count():
            return []
        try:
            result = self._profile.get(where={"owner": owner}, limit=n)
            return result["documents"]
        except Exception:
            return []
