"""
Week 9: Spatial anchor registry.

Persists 3D spatial anchors (created from pointing-vector registration) to SQLite.
Each anchor captures a physical location in normalized 3D space.

Anchors are scoped by ``owner`` (defaults to settings.DEFAULT_OWNER). Every read
filters on it, so one owner never sees another's anchors. Legacy databases are
migrated to add the ``owner`` column (existing rows backfill to 'local').

Interface:
    register_anchor(pointing_vector, label, owner=None) → anchor_id (str)
    get_anchor(anchor_id, owner=None) → SpatialAnchor | None
    list_anchors(owner=None) → list[SpatialAnchor]
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from app.config import settings

_DEFAULT_DB = Path(__file__).parent.parent.parent / "data" / "anchors.db"

_SELECT_COLS = "anchor_id, label, x, y, z, created_at_us"


@dataclass
class SpatialAnchor:
    anchor_id: str
    label: str
    x: float
    y: float
    z: float
    created_at_us: int


def _row_to_anchor(row: tuple) -> SpatialAnchor:
    return SpatialAnchor(
        anchor_id=row[0], label=row[1], x=row[2], y=row[3], z=row[4], created_at_us=row[5]
    )


class AnchorRegistry:
    """
    Thread-safe registry of 3D spatial anchors backed by SQLite.

    Anchors are registered from a pointing vector (normalized x, y, z direction).
    The registry persists across restarts.
    """

    def __init__(self, db_path: Path = _DEFAULT_DB) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = Lock()
        self._init_db()

    # ── public API ────────────────────────────────────────────────────────────

    def register_anchor(
        self,
        pointing_vector: tuple[float, float, float],
        label: str,
        owner: str | None = None,
    ) -> str:
        """Create and persist a new SpatialAnchor from a pointing vector.

        Returns the new anchor_id (UUID string).
        """
        owner = owner or settings.DEFAULT_OWNER
        anchor_id = str(uuid.uuid4())
        x, y, z = pointing_vector
        now_us = int(time.time() * 1_000_000)
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO anchors (anchor_id, label, x, y, z, created_at_us, owner)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (anchor_id, label, x, y, z, now_us, owner),
                )
                conn.commit()
        return anchor_id

    def get_anchor(self, anchor_id: str, owner: str | None = None) -> SpatialAnchor | None:
        owner = owner or settings.DEFAULT_OWNER
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    f"SELECT {_SELECT_COLS} FROM anchors WHERE anchor_id = ? AND owner = ?",
                    (anchor_id, owner),
                ).fetchone()
        return _row_to_anchor(row) if row is not None else None

    def delete_anchor(self, anchor_id: str, owner: str | None = None) -> bool:
        """Delete the anchor with the given ID for the given owner.

        Returns True if a row was deleted, False if no such anchor existed.
        """
        owner = owner or settings.DEFAULT_OWNER
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute(
                    "DELETE FROM anchors WHERE anchor_id = ? AND owner = ?",
                    (anchor_id, owner),
                )
                conn.commit()
        return cursor.rowcount > 0

    def update_anchor(
        self, anchor_id: str, label: str, owner: str | None = None
    ) -> SpatialAnchor | None:
        """Update the label of an existing anchor owned by ``owner``.

        Returns the updated SpatialAnchor, or None if no such anchor exists.
        """
        owner = owner or settings.DEFAULT_OWNER
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute(
                    "UPDATE anchors SET label = ? WHERE anchor_id = ? AND owner = ?",
                    (label, anchor_id, owner),
                )
                conn.commit()
                if cursor.rowcount == 0:
                    return None
                row = conn.execute(
                    f"SELECT {_SELECT_COLS} FROM anchors WHERE anchor_id = ? AND owner = ?",
                    (anchor_id, owner),
                ).fetchone()
        return _row_to_anchor(row) if row is not None else None

    def list_anchors(self, owner: str | None = None) -> list[SpatialAnchor]:
        owner = owner or settings.DEFAULT_OWNER
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    f"SELECT {_SELECT_COLS} FROM anchors WHERE owner = ? ORDER BY created_at_us",
                    (owner,),
                ).fetchall()
        return [_row_to_anchor(r) for r in rows]

    # ── internal ─────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS anchors (
                    anchor_id     TEXT PRIMARY KEY,
                    label         TEXT NOT NULL,
                    x             REAL NOT NULL,
                    y             REAL NOT NULL,
                    z             REAL NOT NULL,
                    created_at_us INTEGER NOT NULL,
                    owner         TEXT NOT NULL DEFAULT 'local'
                )
            """)
            # Migrate legacy DBs that predate the owner column (backfills to 'local').
            columns = [r[1] for r in conn.execute("PRAGMA table_info(anchors)").fetchall()]
            if "owner" not in columns:
                conn.execute(
                    "ALTER TABLE anchors ADD COLUMN owner TEXT NOT NULL DEFAULT 'local'"
                )
            conn.commit()
