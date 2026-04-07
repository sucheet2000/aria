"""
Shannon-style knowledge graph memory layer.

NetworkX directed graph backed by SQLite persistence.
Replaces the flat working-memory list for symbolic inference context.
ChromaDB remains for episodic (raw conversation) storage.

Interface:
    store_triple(subject, predicate, object, confidence, source)
    query_related(entity, depth=2) → list[str]  (human-readable facts)
    get_context(session_id) → str               (formatted for cognition)
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

import networkx as nx

_DEFAULT_DB = Path(__file__).parent.parent.parent / "data" / "graph_memory.db"


@dataclass
class Triple:
    subject: str
    predicate: str
    object: str
    confidence: float = 1.0
    source: str = "observation"
    timestamp_us: int = field(default_factory=lambda: int(time.time() * 1_000_000))


class GraphMemory:
    """
    Knowledge graph backed by an in-memory NetworkX DiGraph and a SQLite store.

    Nodes represent entities (people, places, concepts, preferences).
    Edges represent relationships with confidence scores and timestamps.
    Traversal is BFS up to depth=2 for context retrieval.
    """

    def __init__(self, db_path: Path = _DEFAULT_DB) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._graph: nx.DiGraph = nx.DiGraph()
        self._lock = Lock()
        self._init_db()
        self._load_from_db()

    # ── public API ────────────────────────────────────────────────────────────

    def store_triple(
        self,
        subject: str,
        predicate: str,
        obj: str,
        confidence: float = 1.0,
        source: str = "observation",
    ) -> None:
        """Add or update a (subject, predicate, object) triple in the graph."""
        t = Triple(
            subject=subject,
            predicate=predicate,
            object=obj,
            confidence=confidence,
            source=source,
        )
        with self._lock:
            self._upsert_edge(t)
            self._persist_triple(t)

    def query_related(self, entity: str, depth: int = 2) -> list[str]:
        """Return human-readable facts related to entity up to BFS depth."""
        with self._lock:
            if entity not in self._graph:
                return []
            visited: set[str] = set()
            facts: list[str] = []
            queue: list[tuple[str, int]] = [(entity, 0)]
            while queue:
                node, d = queue.pop(0)
                if d > depth or node in visited:
                    continue
                visited.add(node)
                for _, nbr, data in self._graph.out_edges(node, data=True):
                    facts.append(
                        f"{node} {data['predicate']} {nbr} "
                        f"(confidence={data['confidence']:.2f})"
                    )
                    if d + 1 <= depth:
                        queue.append((nbr, d + 1))
            return facts

    def get_context(self, session_id: str) -> str:  # noqa: ARG002
        """Return a concise formatted context string for the cognition layer."""
        all_facts: list[str] = []
        with self._lock:
            for u, v, data in self._graph.edges(data=True):
                all_facts.append(
                    f"{u} {data['predicate']} {v} "
                    f"(conf={data['confidence']:.2f})"
                )
        if not all_facts:
            return "No relational context available."
        return "Known relationships:\n" + "\n".join(f"  - {f}" for f in all_facts[:20])

    # ── internal ─────────────────────────────────────────────────────────────

    def _upsert_edge(self, t: Triple) -> None:
        self._graph.add_node(t.subject)
        self._graph.add_node(t.object)
        if self._graph.has_edge(t.subject, t.object):
            existing = self._graph[t.subject][t.object]
            # Keep highest confidence; update timestamp
            if t.confidence >= existing["confidence"]:
                self._graph[t.subject][t.object].update(
                    predicate=t.predicate,
                    confidence=t.confidence,
                    source=t.source,
                    timestamp_us=t.timestamp_us,
                )
        else:
            self._graph.add_edge(
                t.subject,
                t.object,
                predicate=t.predicate,
                confidence=t.confidence,
                source=t.source,
                timestamp_us=t.timestamp_us,
            )

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS triples (
                    subject      TEXT NOT NULL,
                    predicate    TEXT NOT NULL,
                    object       TEXT NOT NULL,
                    confidence   REAL NOT NULL DEFAULT 1.0,
                    source       TEXT NOT NULL DEFAULT 'observation',
                    timestamp_us INTEGER NOT NULL,
                    PRIMARY KEY (subject, object)
                )
            """)
            conn.commit()

    def _persist_triple(self, t: Triple) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO triples (subject, predicate, object, confidence, source, timestamp_us)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(subject, object) DO UPDATE SET
                    predicate    = excluded.predicate,
                    confidence   = excluded.confidence,
                    source       = excluded.source,
                    timestamp_us = excluded.timestamp_us
                """,
                (t.subject, t.predicate, t.object, t.confidence, t.source, t.timestamp_us),
            )
            conn.commit()

    def _load_from_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "SELECT subject, predicate, object, confidence, source, timestamp_us FROM triples"
            )
            for row in cursor.fetchall():
                subj, pred, obj, conf, src, ts = row
                t = Triple(subject=subj, predicate=pred, object=obj,
                           confidence=conf, source=src, timestamp_us=ts)
                self._upsert_edge(t)
