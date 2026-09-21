"""
v3 gesture-anchor bridge.

Translates raw gesture events from the browser perception layer into spatial
anchor operations on AnchorRegistry. Called by cognition_route when a request
carries gesture or two_hand_gesture data.

Gesture priority (single-hand takes precedence for POINT):
  POINT + pointing_vector → register a new anchor at that direction
  BOND               → bond the two spatially nearest anchors
  THROW              → throw the nearest anchor in the pointing direction
  EXPAND             → broadcast a world-expand scale event
  anything else      → None (no spatial action)
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.config import settings
from app.models.schemas import SpatialEvent
from app.observability.metrics import MetricsCollector
from app.spatial.anchor_registry import AnchorRegistry

# ── point dwell / dedupe (Workstream D) ──────────────────────────────────────
# A point used to register an anchor on every request that carried one, so a
# user who held a point while talking collected one anchor per turn. An anchor
# now needs an intentional point: the same direction, held.
#
# DWELL is how long the direction must hold before anchoring. JITTER is how far
# the fingertip may wander and still count as the same target — hands are never
# still. COOLDOWN keeps a direction from re-anchoring while the user simply
# keeps pointing at what they already marked.
_POINT_DWELL_SECONDS = 1.0
_POINT_JITTER = 0.15
_POINT_COOLDOWN_SECONDS = 30.0
# Bounds the per-owner tracking table; an owner idle longer than this is
# forgotten, and the table is swept whenever it grows past _MAX_TRACKED_OWNERS.
_TRACK_TTL_SECONDS = 300.0
_MAX_TRACKED_OWNERS = 32


@dataclass
class _PointTrack:
    """One owner's in-flight point, and what they last anchored."""

    candidate: tuple[float, float, float] | None
    candidate_since: float
    last_seen: float
    anchored: tuple[float, float, float] | None = None
    anchored_at: float = 0.0


def _finite_vec(pointing_vector: list[float] | None) -> tuple[float, float, float] | None:
    """Return a usable 3-vector, or None when the input cannot be trusted."""
    if pointing_vector is None or len(pointing_vector) < 3:
        return None
    x, y, z = pointing_vector[0], pointing_vector[1], pointing_vector[2]
    if not all(math.isfinite(v) for v in (x, y, z)):
        return None
    return (float(x), float(y), float(z))


def _apart(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.dist(a, b)


class GestureAnchorBridge:
    """Translator from gesture events to spatial anchor operations.

    Holds a small per-owner record of the point currently being held, so a
    steady point becomes one anchor rather than one per request.
    """

    def __init__(
        self,
        anchor_registry: AnchorRegistry,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._registry = anchor_registry
        self._clock = clock or time.monotonic
        self._tracks: dict[str, _PointTrack] = {}

    # ── point tracking ────────────────────────────────────────────────────────

    def forget_owner(self, owner: str) -> None:
        """Drop an owner's point tracking, e.g. when their camera stops."""
        self._tracks.pop(owner, None)

    def tracked_owner_count(self) -> int:
        """How many owners currently have point tracking. Test-only window."""
        return len(self._tracks)

    def _sweep(self, now: float) -> None:
        if len(self._tracks) <= _MAX_TRACKED_OWNERS:
            return
        stale = [o for o, t in self._tracks.items() if now - t.last_seen > _TRACK_TTL_SECONDS]
        for o in stale:
            del self._tracks[o]
        if len(self._tracks) > _MAX_TRACKED_OWNERS:
            # Still over budget: drop the least recently active.
            for o, _ in sorted(self._tracks.items(), key=lambda kv: kv[1].last_seen)[
                : len(self._tracks) - _MAX_TRACKED_OWNERS
            ]:
                del self._tracks[o]

    def _should_anchor(self, owner: str, vec: tuple[float, float, float]) -> bool:
        """True when this point has been held long enough to mean it."""
        now = self._clock()
        track = self._tracks.get(owner)

        if track is None or track.candidate is None or _apart(track.candidate, vec) > _POINT_JITTER:
            # A new target: start the dwell over, keeping what was last anchored
            # so the cooldown still applies to it.
            self._tracks[owner] = _PointTrack(
                candidate=vec,
                candidate_since=now,
                last_seen=now,
                anchored=track.anchored if track else None,
                anchored_at=track.anchored_at if track else 0.0,
            )
            # Sweep after inserting so the table is never over budget on exit.
            self._sweep(now)
            return False

        track.last_seen = now
        if now - track.candidate_since < _POINT_DWELL_SECONDS:
            return False

        if (
            track.anchored is not None
            and _apart(track.anchored, vec) <= _POINT_JITTER
            and now - track.anchored_at < _POINT_COOLDOWN_SECONDS
        ):
            # Already marked this target recently; holding the point is not a
            # request for another anchor.
            return False

        track.anchored = vec
        track.anchored_at = now
        # Require a fresh dwell before this direction can anchor again.
        track.candidate_since = now
        return True

    def on_gesture_event(
        self,
        gesture: str,
        two_hand_gesture: str,
        pointing_vector: list[float] | None,
        session_id: str,
        owner: str | None = None,
    ) -> SpatialEvent | None:
        """Translate a gesture event into a spatial action dict.

        Args:
            gesture: Single-hand gesture name from the browser perception layer
                     ("point", "stop", "confirm", "cancel", "none").
            two_hand_gesture: Two-hand gesture type
                              ("HOLD", "EXPAND", "THROW", "BOND", "NONE").
            pointing_vector: Normalised [x, y, z] direction from index finger,
                             or None when not applicable.
            session_id: Active session ID (for future per-session anchor scoping).

        Returns:
            A dict describing the spatial event, or None when no action applies.
        """
        owner = owner or settings.DEFAULT_OWNER
        MetricsCollector().record_gesture_event(two_hand_gesture if two_hand_gesture != "NONE" else gesture)

        # ── single-hand: a HELD point registers a new anchor ──────────────────
        if gesture != "point":
            # The hand stopped pointing, so any dwell in progress is abandoned;
            # coming back to the same target must earn its dwell again.
            track = self._tracks.get(owner)
            if track is not None:
                track.candidate = None

        if gesture == "point":
            vec = _finite_vec(pointing_vector)
            if vec is None:
                return None
            if not self._should_anchor(owner, vec):
                return None
            anchor_id = self._registry.register_anchor(vec, "object", owner)
            return SpatialEvent(
                event_type="anchor_registered",
                anchor_id=anchor_id,
                label="object",
                x=vec[0],
                y=vec[1],
                z=vec[2],
            )

        # ── two-hand gestures ─────────────────────────────────────────────────
        if two_hand_gesture == "BOND":
            ids = self._two_nearest_anchor_ids(owner)
            if ids is None:
                return None
            return SpatialEvent(event_type="anchors_bonded", anchor_ids=ids)

        if two_hand_gesture == "THROW":
            throw_target = self._nearest_anchor_id(pointing_vector, owner)
            if throw_target is None:
                return None
            velocity = list(pointing_vector) if pointing_vector is not None else [0.0, 0.0, -1.0]
            return SpatialEvent(event_type="anchor_thrown", anchor_id=throw_target, velocity=velocity)

        if two_hand_gesture == "EXPAND":
            return SpatialEvent(event_type="world_expand", factor=1.5)

        return None

    # ── helpers ───────────────────────────────────────────────────────────────

    def _two_nearest_anchor_ids(self, owner: str) -> list[str] | None:
        """Return the IDs of the two anchors closest to each other.

        Returns None when fewer than two anchors exist.
        """
        anchors = self._registry.list_anchors(owner)
        if len(anchors) < 2:
            return None
        min_dist = float("inf")
        best = (anchors[0].anchor_id, anchors[1].anchor_id)
        for i in range(len(anchors)):
            for j in range(i + 1, len(anchors)):
                a, b = anchors[i], anchors[j]
                dist = math.sqrt(
                    (a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2
                )
                if dist < min_dist:
                    min_dist = dist
                    best = (a.anchor_id, b.anchor_id)
        return list(best)

    def _nearest_anchor_id(self, pointing_vector: list[float] | None, owner: str) -> str | None:
        """Return the ID of the anchor most aligned with the pointing direction.

        Falls back to the most recently registered anchor when pointing_vector
        is None or the registry is empty.
        """
        anchors = self._registry.list_anchors(owner)
        if not anchors:
            return None
        if pointing_vector is None or len(pointing_vector) < 3:
            return anchors[-1].anchor_id
        px, py, pz = pointing_vector[0], pointing_vector[1], pointing_vector[2]
        best_id = anchors[-1].anchor_id
        best_dot = -float("inf")
        for a in anchors:
            mag = math.sqrt(a.x ** 2 + a.y ** 2 + a.z ** 2)
            if mag < 1e-9:
                continue
            dot = (a.x * px + a.y * py + a.z * pz) / mag
            if dot > best_dot:
                best_dot = dot
                best_id = a.anchor_id
        return best_id
