from __future__ import annotations

import hashlib
import time

import structlog

from app.models.schemas import WorldModelTriple

logger = structlog.get_logger()


class MemoryStore:
    def __init__(self, collection_name: str = "aria_memory") -> None:
        self._client = None
        self._collection = None
        self._collection_name = collection_name

    def initialize(self, persist_directory: str = "./chroma_db") -> None:
        try:
            import chromadb

            self._client = chromadb.PersistentClient(path=persist_directory)
            self._collection = self._client.get_or_create_collection(self._collection_name)
            logger.info("MemoryStore initialized", collection=self._collection_name)
        except ImportError:
            logger.warning("chromadb not available, MemoryStore running in stub mode")

    def add(self, text: str, metadata: dict | None = None, doc_id: str | None = None) -> None:
        if self._collection is None:
            logger.warning("MemoryStore not initialized, skipping add")
            return
        import uuid

        self._collection.add(
            documents=[text],
            metadatas=[metadata or {}],
            ids=[doc_id or str(uuid.uuid4())],
        )

    def query(self, query_text: str, n_results: int = 5) -> list[str]:
        if self._collection is None:
            return []
        results = self._collection.query(query_texts=[query_text], n_results=n_results)
        docs = results.get("documents", [[]])
        return docs[0] if docs else []

    async def store_triple(self, triple: WorldModelTriple, confidence: float, source: str) -> None:
        if self._collection is None:
            logger.warning("MemoryStore not initialized, skipping store_triple")
            return
        text = f"{triple.subject} {triple.predicate} {triple.object}"
        doc_id = hashlib.sha256(text.encode()).hexdigest()[:16]
        metadata = {
            "subject": triple.subject,
            "predicate": triple.predicate,
            "object": triple.object,
            "confidence": confidence,
            "source": source,
            "timestamp": time.time(),
        }
        self._collection.add(
            documents=[text],
            metadatas=[metadata],
            ids=[doc_id],
        )

    async def query_relevant(self, context: str, n_results: int = 5) -> list[str]:
        if self._collection is None:
            return []
        results = self._collection.query(query_texts=[context], n_results=n_results)
        docs = results.get("documents", [[]])
        return docs[0] if docs else []
