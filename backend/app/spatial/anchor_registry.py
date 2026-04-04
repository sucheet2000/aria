"""
Week 9: Spatial anchor registry.

Persists 3D spatial anchors (created from pointing-vector registration) to SQLite.
Each anchor captures a physical location in normalized 3D space.

Interface:
    register_anchor(pointing_vector, label) → anchor_id (str)
    get_anchor(anchor_id) → SpatialAnchor | None
    list_anchors() → list[SpatialAnchor]
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

_DEFAULT_DB = Path(__file__).parent.parent.parent / "data" / "anchors.db"


@dataclass
class SpatialAnchor:
    anchor_id: str
    label: str
    x: float
    y: float
    z: float
    created_at_us: int


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
    ) -> str:
        """Create and persist a new SpatialAnchor from a pointing vector.

        Returns the new anchor_id (UUID string).
        """
        anchor_id = str(uuid.uuid4())
        x, y, z = pointing_vector
        now_us = int(time.time() * 1_000_000)
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO anchors (anchor_id, label, x, y, z, created_at_us)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (anchor_id, label, x, y, z, now_us),
                )
                conn.commit()
        return anchor_id

    def get_anchor(self, anchor_id: str) -> SpatialAnchor | None:
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT anchor_id, label, x, y, z, created_at_us FROM anchors WHERE anchor_id = ?",
                    (anchor_id,),
                ).fetchone()
        if row is None:
            return None
        return SpatialAnchor(
            anchor_id=row[0], label=row[1], x=row[2], y=row[3], z=row[4],
            created_at_us=row[5],
        )

    def list_anchors(self) -> list[SpatialAnchor]:
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT anchor_id, label, x, y, z, created_at_us FROM anchors ORDER BY created_at_us"
                ).fetchall()
        return [
            SpatialAnchor(
                anchor_id=r[0], label=r[1], x=r[2], y=r[3], z=r[4], created_at_us=r[5]
            )
            for r in rows
        ]

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
                    created_at_us INTEGER NOT NULL
                )
            """)
            conn.commit()
