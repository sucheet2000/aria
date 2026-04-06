"""
v3 gesture-anchor bridge.

Translates raw gesture events from vision_worker into spatial anchor
operations on AnchorRegistry. Called by cognition_route when a request
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

from app.models.schemas import SpatialEvent
from app.observability.metrics import MetricsCollector
from app.spatial.anchor_registry import AnchorRegistry


class GestureAnchorBridge:
    """Stateless translator from gesture events to spatial anchor operations."""

    def __init__(self, anchor_registry: AnchorRegistry) -> None:
        self._registry = anchor_registry

    def on_gesture_event(
        self,
        gesture: str,
        two_hand_gesture: str,
        pointing_vector: list[float] | None,
        session_id: str,
    ) -> SpatialEvent | None:
        """Translate a gesture event into a spatial action dict.

        Args:
            gesture: Single-hand gesture name from vision_worker
                     ("point", "stop", "confirm", "cancel", "none").
            two_hand_gesture: Two-hand gesture type
                              ("HOLD", "EXPAND", "THROW", "BOND", "NONE").
            pointing_vector: Normalised [x, y, z] direction from index finger,
                             or None when not applicable.
            session_id: Active session ID (for future per-session anchor scoping).

        Returns:
            A dict describing the spatial event, or None when no action applies.
        """
        MetricsCollector().record_gesture_event(two_hand_gesture if two_hand_gesture != "NONE" else gesture)

        # ── single-hand: POINT registers a new anchor ─────────────────────────
        if gesture == "point" and pointing_vector is not None and len(pointing_vector) >= 3:
            vec: tuple[float, float, float] = (
                pointing_vector[0], pointing_vector[1], pointing_vector[2]
            )
            anchor_id = self._registry.register_anchor(vec, "object")
            return SpatialEvent(
                event_type="anchor_registered",
                anchor_id=anchor_id,
            )

        # ── two-hand gestures ─────────────────────────────────────────────────
        if two_hand_gesture == "BOND":
            ids = self._two_nearest_anchor_ids()
            if ids is None:
                return None
            return SpatialEvent(event_type="anchors_bonded", anchor_ids=ids)

        if two_hand_gesture == "THROW":
            anchor_id = self._nearest_anchor_id(pointing_vector)
            if anchor_id is None:
                return None
            velocity = list(pointing_vector) if pointing_vector is not None else [0.0, 0.0, -1.0]
            return SpatialEvent(event_type="anchor_thrown", anchor_id=anchor_id, velocity=velocity)

        if two_hand_gesture == "EXPAND":
            return SpatialEvent(event_type="world_expand", factor=1.5)

        return None

    # ── helpers ───────────────────────────────────────────────────────────────

    def _two_nearest_anchor_ids(self) -> list[str] | None:
        """Return the IDs of the two anchors closest to each other.

        Returns None when fewer than two anchors exist.
        """
        anchors = self._registry.list_anchors()
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

    def _nearest_anchor_id(self, pointing_vector: list[float] | None) -> str | None:
        """Return the ID of the anchor most aligned with the pointing direction.

        Falls back to the most recently registered anchor when pointing_vector
        is None or the registry is empty.
        """
        anchors = self._registry.list_anchors()
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
