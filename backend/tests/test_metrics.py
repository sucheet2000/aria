from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.observability.metrics import Histogram, MetricsCollector


# Reset singleton state before each test so tests are independent
@pytest.fixture(autouse=True)
def reset_metrics():
    m = MetricsCollector()
    m._cognition_latency = Histogram()
    m._interrupt_latency = Histogram()
    m._token_cost = {}
    m._anchors_created = 0
    m._gesture_events = {}
    yield


# --- Histogram ---

def test_histogram_single_record():
    h = Histogram()
    h.record(100.0)
    snap = h.snapshot()
    assert snap["count"] == 1
    assert snap["mean"] == 100.0
    assert snap["min"] == 100.0
    assert snap["max"] == 100.0


def test_histogram_multiple_records():
    h = Histogram()
    for v in [10.0, 20.0, 30.0]:
        h.record(v)
    snap = h.snapshot()
    assert snap["count"] == 3
    assert snap["mean"] == 20.0
    assert snap["min"] == 10.0
    assert snap["max"] == 30.0


def test_histogram_empty_snapshot():
    h = Histogram()
    snap = h.snapshot()
    assert snap["count"] == 0
    assert snap["mean"] == 0.0


# --- MetricsCollector singleton ---

def test_singleton_same_object():
    a = MetricsCollector()
    b = MetricsCollector()
    assert a is b


# --- record_cognition_latency ---

def test_cognition_latency_accumulates():
    m = MetricsCollector()
    m.record_cognition_latency(50.0)
    m.record_cognition_latency(150.0)
    snap = m.snapshot()
    assert snap["cognition_latency_ms"]["count"] == 2
    assert snap["cognition_latency_ms"]["mean"] == 100.0
    assert snap["cognition_latency_ms"]["min"] == 50.0
    assert snap["cognition_latency_ms"]["max"] == 150.0


# --- record_gesture_event ---

def test_gesture_events_count_by_type():
    m = MetricsCollector()
    m.record_gesture_event("HOLD")
    m.record_gesture_event("HOLD")
    m.record_gesture_event("EXPAND")
    snap = m.snapshot()
    assert snap["gesture_events"]["HOLD"] == 2
    assert snap["gesture_events"]["EXPAND"] == 1


def test_gesture_events_new_type_starts_at_one():
    m = MetricsCollector()
    m.record_gesture_event("THROW")
    assert m.snapshot()["gesture_events"]["THROW"] == 1


# --- record_anchor_created ---

def test_anchor_created_increments():
    m = MetricsCollector()
    m.record_anchor_created()
    m.record_anchor_created()
    assert m.snapshot()["anchors_created"] == 2


# --- snapshot shape ---

def test_snapshot_has_all_keys():
    snap = MetricsCollector().snapshot()
    assert "cognition_latency_ms" in snap
    assert "interrupt_latency_ms" in snap
    assert "token_cost" in snap
    assert "anchors_created" in snap
    assert "gesture_events" in snap


# --- /metrics endpoint ---

def test_metrics_endpoint_returns_200():
    from app.main import app
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200


def test_metrics_endpoint_returns_correct_keys():
    from app.main import app
    client = TestClient(app)
    MetricsCollector().record_cognition_latency(42.0)
    resp = client.get("/metrics")
    data = resp.json()
    assert "cognition_latency_ms" in data
    assert "gesture_events" in data
    assert "anchors_created" in data
    assert data["cognition_latency_ms"]["count"] >= 1
