"""
Week 7: Shannon-style graph memory tests.

- test_graph_store: store triple, verify node/edge created
- test_graph_query: store 3 related triples, query returns all
- test_graph_persistence: store, reload, verify data survives restart
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.memory.graph_memory import GraphMemory


@pytest.fixture
def tmp_graph(tmp_path: Path) -> GraphMemory:
    """Fresh GraphMemory backed by a temp SQLite file."""
    return GraphMemory(db_path=tmp_path / "test_graph.db")


class TestGraphStore:
    def test_store_triple_creates_nodes(self, tmp_graph: GraphMemory) -> None:
        tmp_graph.store_triple("Alice", "knows", "Bob")
        assert "Alice" in tmp_graph._graph
        assert "Bob" in tmp_graph._graph

    def test_store_triple_creates_edge(self, tmp_graph: GraphMemory) -> None:
        tmp_graph.store_triple("Alice", "likes", "coffee", confidence=0.9)
        assert tmp_graph._graph.has_edge("Alice", "coffee")
        data = tmp_graph._graph["Alice"]["coffee"]
        assert data["predicate"] == "likes"
        assert data["confidence"] == pytest.approx(0.9)

    def test_store_triple_updates_on_conflict(self, tmp_graph: GraphMemory) -> None:
        tmp_graph.store_triple("Alice", "likes", "coffee", confidence=0.5)
        tmp_graph.store_triple("Alice", "loves", "coffee", confidence=0.95)
        data = tmp_graph._graph["Alice"]["coffee"]
        assert data["predicate"] == "loves"
        assert data["confidence"] == pytest.approx(0.95)

    def test_lower_confidence_does_not_overwrite(self, tmp_graph: GraphMemory) -> None:
        tmp_graph.store_triple("Alice", "loves", "coffee", confidence=0.9)
        tmp_graph.store_triple("Alice", "likes", "coffee", confidence=0.3)
        data = tmp_graph._graph["Alice"]["coffee"]
        assert data["predicate"] == "loves"
        assert data["confidence"] == pytest.approx(0.9)


class TestGraphQuery:
    def test_query_returns_direct_facts(self, tmp_graph: GraphMemory) -> None:
        tmp_graph.store_triple("Alice", "knows", "Bob")
        facts = tmp_graph.query_related("Alice")
        assert any("Bob" in f for f in facts)

    def test_query_traverses_depth_2(self, tmp_graph: GraphMemory) -> None:
        tmp_graph.store_triple("Alice", "knows", "Bob")
        tmp_graph.store_triple("Bob", "works_at", "Acme")
        tmp_graph.store_triple("Acme", "located_in", "NewYork")

        facts = tmp_graph.query_related("Alice", depth=2)
        predicates = " ".join(facts)
        assert "knows" in predicates
        assert "works_at" in predicates

    def test_query_respects_depth_limit(self, tmp_graph: GraphMemory) -> None:
        tmp_graph.store_triple("A", "to", "B")
        tmp_graph.store_triple("B", "to", "C")
        tmp_graph.store_triple("C", "to", "D")

        facts_depth1 = tmp_graph.query_related("A", depth=1)
        facts_depth2 = tmp_graph.query_related("A", depth=2)

        # depth=1 should include A→B but not B→C
        joined1 = " ".join(facts_depth1)
        assert "B" in joined1
        # depth=2 should include B→C
        joined2 = " ".join(facts_depth2)
        assert "C" in joined2

    def test_query_unknown_entity_returns_empty(self, tmp_graph: GraphMemory) -> None:
        assert tmp_graph.query_related("NoOne") == []

    def test_get_context_returns_string(self, tmp_graph: GraphMemory) -> None:
        tmp_graph.store_triple("user", "feels", "happy")
        context = tmp_graph.get_context("session-1")
        assert "user" in context
        assert "feels" in context


class TestGraphPersistence:
    def test_data_survives_restart(self, tmp_path: Path) -> None:
        db = tmp_path / "graph.db"

        # Write
        g1 = GraphMemory(db_path=db)
        g1.store_triple("user", "prefers", "dark mode", confidence=0.8, source="stated")

        # Reload into fresh instance
        g2 = GraphMemory(db_path=db)
        assert g2._graph.has_edge("user", "dark mode")
        data = g2._graph["user"]["dark mode"]
        assert data["predicate"] == "prefers"
        assert data["confidence"] == pytest.approx(0.8)
        assert data["source"] == "stated"

    def test_multiple_triples_persist(self, tmp_path: Path) -> None:
        db = tmp_path / "graph.db"
        g1 = GraphMemory(db_path=db)
        g1.store_triple("Alice", "knows", "Bob")
        g1.store_triple("Bob", "works_at", "Acme")
        g1.store_triple("Acme", "makes", "widgets")

        g2 = GraphMemory(db_path=db)
        assert g2._graph.number_of_edges() == 3
