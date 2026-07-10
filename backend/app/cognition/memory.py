from __future__ import annotations

import hashlib
import time

import structlog

from app.config import settings

logger = structlog.get_logger()

PROFILE_COLLECTION = "aria_profile"
EPISODIC_COLLECTION = "aria_episodic"
WORKING_COLLECTION = "aria_working"

EPISODIC_TTL_DAYS = 30


class MemoryStore:
    """
    Layered ChromaDB memory store, scoped by ``owner``.

    Three collections:
      aria_profile  - stable user facts (permanent)
      aria_episodic - session events (30 day TTL)
      aria_working  - current session context (cleared on shutdown)

    Every document carries an ``owner`` metadata field and every read filters
    on it, so data written by one owner is never returned to another. Legacy
    documents (written before owners existed) are backfilled to DEFAULT_OWNER
    on load.
    """

    def __init__(self, persist_dir: str = "./memory") -> None:
        self._persist_dir = persist_dir
        self._client = None
        self._profile = None
        self._episodic = None
        self._working = None

    def load(self) -> None:
        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=self._persist_dir)
            self._profile = self._client.get_or_create_collection(PROFILE_COLLECTION)
            self._episodic = self._client.get_or_create_collection(EPISODIC_COLLECTION)
            self._working = self._client.get_or_create_collection(WORKING_COLLECTION)
            self._migrate_owner_metadata()
            logger.info("memory store loaded",
                profile_count=self._profile.count(),
                episodic_count=self._episodic.count(),
            )
        except ImportError:
            logger.warning("chromadb not available, memory disabled")
        except Exception as e:
            logger.error("memory store failed to load", error=str(e))

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
                logger.error("owner backfill failed", error=str(e))

    async def store_triple(
        self,
        subject: str,
        predicate: str,
        obj: str,
        confidence: float,
        source: str,
        owner: str | None = None,
    ) -> None:
        if not self.loaded:
            return
        owner = owner or settings.DEFAULT_OWNER

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
            elif source in ("behavioral_inference", "visual_inference"):
                collection = self._episodic
                metadata["expires_at"] = time.time() + EPISODIC_TTL_DAYS * 86400
            else:
                collection = self._working

            existing = collection.get(ids=[doc_id])
            if existing["ids"]:
                collection.update(ids=[doc_id], documents=[text], metadatas=[metadata])
                logger.debug("memory updated", id=doc_id, text=text)
            else:
                collection.add(ids=[doc_id], documents=[text], metadatas=[metadata])
                logger.debug("memory stored", id=doc_id, text=text)

        except Exception as e:
            logger.error("store_triple failed", error=str(e))

    async def query_relevant(
        self,
        context: str,
        owner: str | None = None,
        n_results: int = 5,
    ) -> list[str]:
        if not self.loaded:
            return []
        owner = owner or settings.DEFAULT_OWNER

        results = []
        now = time.time()

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
                )
                for doc, meta in zip(
                    response["documents"][0],
                    response["metadatas"][0],
                ):
                    expires = meta.get("expires_at")
                    if expires and expires < now:
                        continue
                    results.append(doc)

        except Exception as e:
            logger.error("query_relevant failed", error=str(e))

        return results[:n_results]

    async def clear_working(self, owner: str | None = None) -> None:
        owner = owner or settings.DEFAULT_OWNER
        if self._working:
            try:
                ids = self._working.get(where={"owner": owner})["ids"]
                if ids:
                    self._working.delete(ids=ids)
                logger.info("working memory cleared", owner=owner)
            except Exception as e:
                logger.error("clear_working failed", error=str(e))

    async def get_profile_facts(self, owner: str | None = None, n: int = 10) -> list[str]:
        owner = owner or settings.DEFAULT_OWNER
        if not self.loaded or not self._profile.count():
            return []
        try:
            result = self._profile.get(where={"owner": owner}, limit=n)
            return result["documents"]
        except Exception:
            return []
