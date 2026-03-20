from __future__ import annotations

import hashlib
import time
import structlog
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = structlog.get_logger()

PROFILE_COLLECTION = "aria_profile"
EPISODIC_COLLECTION = "aria_episodic"
WORKING_COLLECTION = "aria_working"

EPISODIC_TTL_DAYS = 30


class MemoryStore:
    """
    Layered ChromaDB memory store.

    Three collections:
      aria_profile  - stable user facts (permanent)
      aria_episodic - session events (30 day TTL)
      aria_working  - current session context (cleared on shutdown)
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

    def _triple_id(self, subject: str, predicate: str, obj: str) -> str:
        text = f"{subject.lower()}:{predicate.lower()}:{obj.lower()}"
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def _triple_text(self, subject: str, predicate: str, obj: str) -> str:
        return f"{subject} {predicate} {obj}"

    async def store_triple(
        self,
        subject: str,
        predicate: str,
        obj: str,
        confidence: float,
        source: str,
    ) -> None:
        if not self.loaded:
            return

        doc_id = self._triple_id(subject, predicate, obj)
        text = self._triple_text(subject, predicate, obj)
        metadata = {
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
        n_results: int = 5,
    ) -> list[str]:
        if not self.loaded:
            return []

        results = []
        now = time.time()

        try:
            for collection in [self._profile, self._episodic]:
                response = collection.query(
                    query_texts=[context],
                    n_results=min(n_results, collection.count() or 1),
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

    async def clear_working(self) -> None:
        if self._working:
            try:
                ids = self._working.get()["ids"]
                if ids:
                    self._working.delete(ids=ids)
                logger.info("working memory cleared")
            except Exception as e:
                logger.error("clear_working failed", error=str(e))

    async def get_profile_facts(self, n: int = 10) -> list[str]:
        if not self.loaded or not self._profile.count():
            return []
        try:
            result = self._profile.get(limit=n)
            return result["documents"]
        except Exception:
            return []
