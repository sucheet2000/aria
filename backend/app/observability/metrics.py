from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
import time


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
                inst._anchors_created: int = 0
                inst._gesture_events: dict[str, int] = {}
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

    def record_anchor_created(self) -> None:
        with self._data_lock:
            self._anchors_created += 1

    def record_gesture_event(self, gesture_type: str) -> None:
        with self._data_lock:
            self._gesture_events[gesture_type] = self._gesture_events.get(gesture_type, 0) + 1

    def snapshot(self) -> dict:
        with self._data_lock:
            return {
                "cognition_latency_ms": self._cognition_latency.snapshot(),
                "interrupt_latency_ms": self._interrupt_latency.snapshot(),
                "token_cost": {k: dict(v) for k, v in self._token_cost.items()},
                "anchors_created": self._anchors_created,
                "gesture_events": dict(self._gesture_events),
            }
