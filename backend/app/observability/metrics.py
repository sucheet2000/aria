from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from app.models.schemas import RESPONSE_STATUSES

# The gesture names this metric will count, and the single bucket everything
# else lands in.
#
# Both halves restate a contract owned elsewhere, because neither is importable
# here: the single-hand wire names are produced by a TypeScript map
# (frontend/src/lib/perception/gesture.ts), and the two-hand names come from the
# protobuf enum, whose generated Python spells them with a
# TWO_HAND_GESTURE_TYPE_ prefix the wire does not carry. Restating a vocabulary
# is how this codebase ended up with several that disagree, so
# tests/test_gesture_metric_cardinality.py reads both producers and fails if
# either can emit something this list would silently bucket as unknown.
KNOWN_GESTURE_EVENTS: frozenset[str] = frozenset(
    {
        # single-hand, from GESTURE_NAMES in gesture.ts
        "none",
        "confirm",
        "stop",
        "cancel",
        "point",
        # two-hand, from TwoHandGestureType in perception.proto
        "NONE",
        "HOLD",
        "EXPAND",
        "THROW",
        "BOND",
    }
)

GESTURE_EVENT_UNKNOWN = "unknown"


@dataclass
class Histogram:
    """Tracks count, sum, min, max of a measurement."""
    count: int = 0
    total: float = 0.0
    min_val: float = float("inf")
    max_val: float = 0.0

    def record(self, value: float) -> None:
        self.count += 1
        self.total += value
        if value < self.min_val:
            self.min_val = value
        if value > self.max_val:
            self.max_val = value

    def snapshot(self) -> dict:
        return {
            "count": self.count,
            "mean": round(self.total / self.count, 3) if self.count else 0.0,
            "min": self.min_val if self.count else 0.0,
            "max": self.max_val,
        }


class MetricsCollector:
    """Thread-safe singleton metrics store."""
    _instance: MetricsCollector | None = None
    _lock: Lock = Lock()

    def __new__(cls) -> MetricsCollector:
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._cognition_latency = Histogram()
                inst._interrupt_latency = Histogram()
                inst._token_cost: dict[str, dict[str, int]] = {}
                inst._prompt_cache: dict[str, dict[str, int]] = {}
                inst._llm_response: dict[str, dict[str, int]] = {}
                inst._cognition_timeout: dict[str, int] = {}
                inst._anchors_created: int = 0
                inst._gesture_events: dict[str, int] = {}
                inst._errors: int = 0
                inst._data_lock = Lock()
                cls._instance = inst
        return cls._instance

    def record_cognition_latency(self, ms: float) -> None:
        with self._data_lock:
            self._cognition_latency.record(ms)

    def record_interrupt_latency(self, ms: float) -> None:
        with self._data_lock:
            self._interrupt_latency.record(ms)

    def record_token_cost(self, model: str, cached: bool, tokens: int) -> None:
        with self._data_lock:
            bucket = self._token_cost.setdefault(model, {"cached": 0, "uncached": 0})
            key = "cached" if cached else "uncached"
            bucket[key] += tokens

    def record_prompt_cache(self, model: str, status: str) -> None:
        """Count prompt-cache outcomes per model: read (hit), created, none, unknown."""
        with self._data_lock:
            bucket = self._prompt_cache.setdefault(
                model, {"read": 0, "created": 0, "none": 0, "unknown": 0}
            )
            bucket[status if status in bucket else "unknown"] += 1

    def record_llm_response(self, model: str, status: str) -> None:
        """Count how each provider turn was classified (R5). Buckets follow
        ``schemas.ResponseStatus``. Never carries content."""
        with self._data_lock:
            bucket = self._llm_response.setdefault(
                model, dict.fromkeys(RESPONSE_STATUSES, 0)
            )
            if status in bucket:
                bucket[status] += 1

    def record_cognition_timeout(self, category: str) -> None:
        """Count how a cognition turn ran out of budget (R6): which layer gave
        up, never why in content terms."""
        with self._data_lock:
            self._cognition_timeout[category] = self._cognition_timeout.get(category, 0) + 1

    def record_anchor_created(self) -> None:
        with self._data_lock:
            self._anchors_created += 1

    def record_gesture_event(self, gesture_type: object) -> None:
        """Count one gesture, under a name from the fixed vocabulary.

        The caller is not trusted. This value originates in a request body and
        reaches here before anything has decided whether it means anything, so
        an unrecognised one is counted as "unknown" rather than given a key of
        its own. Without that, the dict grew one permanent entry per distinct
        string a caller chose to send, and /metrics published them.
        """
        name = gesture_type if isinstance(gesture_type, str) else None
        bucket = name if name in KNOWN_GESTURE_EVENTS else GESTURE_EVENT_UNKNOWN
        with self._data_lock:
            self._gesture_events[bucket] = self._gesture_events.get(bucket, 0) + 1

    def record_error(self) -> None:
        with self._data_lock:
            self._errors += 1

    def snapshot(self) -> dict:
        with self._data_lock:
            return {
                "cognition_latency_ms": self._cognition_latency.snapshot(),
                "interrupt_latency_ms": self._interrupt_latency.snapshot(),
                "token_cost": {k: dict(v) for k, v in self._token_cost.items()},
                "prompt_cache": {k: dict(v) for k, v in self._prompt_cache.items()},
                "llm_response": {k: dict(v) for k, v in self._llm_response.items()},
                "cognition_timeout": dict(self._cognition_timeout),
                "anchors_created": self._anchors_created,
                "gesture_events": dict(self._gesture_events),
                "errors": self._errors,
            }
