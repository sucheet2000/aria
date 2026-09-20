"""R6 — one request budget, propagated inward, enforced at every layer.

The browser is the outermost bound and the provider attempt the innermost:
browser 25 s > Go upstream 20 s > Python total 15 s >= provider attempt 10 s.
Go sends its remaining budget as ``X-Aria-Deadline-Ms``; Python caps it to its
own maximum and never lets a caller extend server policy. Retries and
``pause_turn`` continuations spend that one budget rather than resetting it,
and a turn whose budget has expired writes nothing — not memory, not the ring.
Cancellation is re-raised, never converted into an R5 malformed-response
fallback.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

import app.api.cognition_route as route_mod
import app.cognition.llm as llm_mod
import app.cognition.prompt as prompt_mod
from app.api.cognition_route import (
    DEADLINE_HEADER,
    WRITE_MARGIN_SECONDS,
    cognition_budget_seconds,
)
from app.cognition.llm import (
    SAFE_FALLBACK_RESPONSE,
    CognitionDeadlineError,
    LLMClient,
)
from app.config import settings
from app.models.schemas import CognitionResponse, PerceptionFrame
from app.observability.metrics import MetricsCollector

PRIVATE = "PRIVATE_TIMEOUT_TEST_6041"
VALID = (
    '{"symbolic_inference": "user is calm", '
    '"world_model_update": {"triple": {"subject": "user", "predicate": "owns", "object": "a red bicycle"}, '
    '"confidence": 0.9, "source": "explicit_statement"}, '
    '"natural_language_response": "Nice bike!"}'
)

# Mirrors of the other layers' constants so a one-sided change surfaces here.
# Go:      cognition.UpstreamTimeout        = 20 * time.Second
# Browser: COGNITION_REQUEST_TIMEOUT_MS     = 25000
GO_UPSTREAM_SECONDS = 20.0
BROWSER_TIMEOUT_MS = 25000


@contextmanager
def capture_all_levels() -> Iterator[list[dict]]:
    saved = structlog.get_config()
    structlog.configure(wrapper_class=structlog.BoundLogger)
    try:
        with capture_logs() as logs:
            structlog.get_logger().debug("probe")
            logs.pop()
            yield logs
    finally:
        structlog.configure(**saved)


def _message(text: str = VALID, *, stop_reason: str = "end_turn") -> SimpleNamespace:
    usage = SimpleNamespace(
        input_tokens=100, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)], stop_reason=stop_reason, usage=usage
    )


def _client(create: AsyncMock | None = None) -> tuple[LLMClient, AsyncMock]:
    prompt_mod._soul_cache = None
    client = LLMClient(api_key="test-key")
    create = create or AsyncMock(return_value=_message())
    client._client.messages.create = create
    return client, create


async def _turn(client: LLMClient, *, deadline: float | None = None, message: str = "hello"):
    return await client.complete(
        message=message, vision=PerceptionFrame(), conversation_history=[],
        working_memory=[], episodic_memory=[], deadline=deadline,
    )


@pytest.fixture(autouse=True)
def _reset_metrics():
    MetricsCollector()._cognition_timeout = {}
    MetricsCollector()._llm_response = {}
    MetricsCollector()._prompt_cache = {}
    yield


# ── Test 1: the hierarchy is monotonic inward ────────────────────────────────


def test_timeout_hierarchy_is_monotonic_inward() -> None:
    browser_s = BROWSER_TIMEOUT_MS / 1000.0
    python_total = settings.COGNITION_TOTAL_TIMEOUT_SECONDS
    attempt = settings.ANTHROPIC_TIMEOUT_SECONDS
    assert browser_s > GO_UPSTREAM_SECONDS > python_total >= attempt
    # Each hop keeps a real margin to serialize, proxy and return its error.
    assert browser_s - GO_UPSTREAM_SECONDS >= 5.0
    assert GO_UPSTREAM_SECONDS - python_total >= 5.0
    assert python_total - attempt >= 5.0
    # Pinned so a silent edit to one layer fails here.
    assert (python_total, attempt) == (15.0, 10.0)


def test_attempt_budget_covers_measured_latency() -> None:
    # Measured live this session: Haiku 1.433 s, Sonnet 3.642 s per turn.
    assert settings.ANTHROPIC_TIMEOUT_SECONDS >= 2 * 3.642


# ── Budget header: capped, never extended, never fatal ───────────────────────


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, 15.0),              # no header → our own maximum
        ("5000", 5.0),             # Go has less left than we allow → take the smaller
        ("900000", 15.0),          # a caller cannot extend server policy
        ("-1", 0.0),               # already expired
        ("0", 0.0),
        ("not-a-number", 15.0),    # malformed → our maximum, never a crash
        ("", 15.0),
        ("1e9", 15.0),
        ("999999999999999999999", 15.0),
    ],
)
def test_budget_header_is_capped_and_safe(header: str | None, expected: float) -> None:
    headers = {} if header is None else {DEADLINE_HEADER: header}
    assert cognition_budget_seconds(headers) == pytest.approx(expected)


# ── Tests 8, 9, 10: the provider spends one budget ───────────────────────────


@pytest.mark.asyncio
async def test_provider_attempt_bounded_by_remaining_budget() -> None:  # Test 8
    client, create = _client()
    await _turn(client, deadline=time.monotonic() + 2.0)
    passed = create.call_args.kwargs["timeout"]
    assert 0 < passed <= 2.0                       # never more than what is left
    assert passed < settings.ANTHROPIC_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_attempt_uses_the_cap_when_budget_is_large() -> None:
    client, create = _client()
    await _turn(client, deadline=time.monotonic() + 600.0)
    assert create.call_args.kwargs["timeout"] == settings.ANTHROPIC_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_expired_budget_never_calls_the_provider() -> None:
    client, create = _client()
    with pytest.raises(CognitionDeadlineError):
        await _turn(client, deadline=time.monotonic() - 0.01)
    create.assert_not_awaited()


def _fake_clock(monkeypatch, *, start: float = 100.0, step: float = 1.0) -> float:
    """Advance the llm module's clock by ``step`` on every read, so budget
    draining is exact instead of racing a real timer. Returns the start."""
    state = {"t": start}

    def now() -> float:
        state["t"] += step
        return state["t"]

    monkeypatch.setattr(llm_mod, "_now", now)
    return start


@pytest.mark.asyncio
async def test_successive_provider_calls_share_one_draining_budget(monkeypatch) -> None:  # Test 9
    # Honest scope: this measures the timeout handed to each *call*, which is
    # what the continuation loop and any caller-level retry use. The SDK's own
    # internal retries reuse one fixed per-attempt timeout within a single
    # create(), so `asyncio.timeout` in the route is their only hard bound —
    # see test_route_total_deadline_returns_504.
    start = _fake_clock(monkeypatch, step=1.0)
    client, create = _client()
    deadline = start + 5.0
    await _turn(client, deadline=deadline)
    first = create.call_args.kwargs["timeout"]
    await _turn(client, deadline=deadline)
    second = create.call_args.kwargs["timeout"]
    assert (first, second) == (4.0, 3.0)   # one shared budget, draining


@pytest.mark.asyncio
async def test_pause_turn_continuations_share_one_budget(monkeypatch) -> None:  # Test 10
    start = _fake_clock(monkeypatch, step=1.0)
    paused = _message(stop_reason="pause_turn")
    create = AsyncMock(side_effect=[paused, paused, _message()])
    client, _ = _client(create)
    await _turn(client, deadline=start + 6.0)

    timeouts = [c.kwargs["timeout"] for c in create.call_args_list]
    assert timeouts == [5.0, 4.0, 3.0]     # never reset, strictly draining


@pytest.mark.asyncio
async def test_continuation_stops_when_the_budget_runs_out(monkeypatch) -> None:
    start = _fake_clock(monkeypatch, step=1.0)
    create = AsyncMock(return_value=_message(stop_reason="pause_turn"))
    client, _ = _client(create)
    with pytest.raises(CognitionDeadlineError):
        await _turn(client, deadline=start + 2.5)
    # Budget gone after two attempts; the loop does not run to its 3-continuation cap.
    assert create.await_count == 2


# ── Test 7: cancellation is re-raised, never an R5 fallback ──────────────────


@pytest.mark.asyncio
async def test_cancelled_error_is_re_raised_not_converted() -> None:
    client, _ = _client(AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await _turn(client, deadline=time.monotonic() + 5.0)


@pytest.mark.asyncio
async def test_provider_timeout_is_not_an_r5_malformed_response() -> None:
    import anthropic

    err = anthropic.APITimeoutError(request=MagicMock())
    client, _ = _client(AsyncMock(side_effect=err))
    with pytest.raises(anthropic.APITimeoutError):
        await _turn(client, deadline=time.monotonic() + 5.0)


# ── Route: total deadline, 504, and no side effects ──────────────────────────


def _mount(app, llm, tmp_path) -> MagicMock:
    from app.api.cognition_route import get_bridge, get_client, get_memory
    from app.spatial.anchor_registry import AnchorRegistry
    from app.spatial.gesture_anchor_bridge import GestureAnchorBridge

    memory = MagicMock()
    memory.loaded = True
    memory.store_triple = AsyncMock(return_value=True)
    memory.query_relevant = AsyncMock(return_value=[])
    memory.deletion_generation = MagicMock(return_value=0)
    app.dependency_overrides[get_client] = lambda: llm
    app.dependency_overrides[get_memory] = lambda: memory
    app.dependency_overrides[get_bridge] = lambda: GestureAnchorBridge(
        AnchorRegistry(db_path=tmp_path / "a.db")
    )
    return memory


def _post(app, llm, tmp_path, *, budget_ms: int | None = 60, message: str = "hi"):
    memory = _mount(app, llm, tmp_path)
    headers = {"X-Aria-Owner": "o"}
    if budget_ms is not None:
        headers[DEADLINE_HEADER] = str(budget_ms)
    try:
        r = TestClient(app).post(
            "/api/cognition", json={"message": message, "session_id": "s1"}, headers=headers
        )
    finally:
        app.dependency_overrides.clear()
    return r, memory


def _blocking_llm(release: asyncio.Event | None = None, result: CognitionResponse | None = None):
    """An LLM whose turn blocks until released (or forever)."""
    llm = MagicMock()

    async def _complete(**kwargs):
        if release is not None:
            await release.wait()
        else:
            await asyncio.sleep(3600)
        return result or CognitionResponse(
            symbolic_inference="late", natural_language_response="late"
        )

    llm.complete = AsyncMock(side_effect=_complete)
    return llm


def test_route_total_deadline_returns_504(tmp_path) -> None:  # Test 6
    from app.main import app

    r, memory = _post(app, _blocking_llm(), tmp_path, budget_ms=50)
    assert r.status_code == 504
    body = r.json()
    assert "timed out" in str(body).lower()
    for bad in ("Traceback", "TimeoutError", "asyncio", "anthropic"):
        assert bad not in str(body)
    memory.store_triple.assert_not_awaited()


def test_route_deadline_does_not_write_memory_or_leak(tmp_path) -> None:  # Tests 11, 19
    from app.main import app

    llm = _blocking_llm()
    with capture_all_levels() as logs:
        r, memory = _post(app, llm, tmp_path, budget_ms=50, message=f"{PRIVATE} what do I own")
    assert r.status_code == 504
    memory.store_triple.assert_not_awaited()
    rendered = "\n".join(repr(e) for e in logs)
    assert PRIVATE not in rendered
    timeout_log = next(e for e in logs if e.get("event") == "cognition deadline exceeded")
    assert timeout_log["timeout_category"] == "python_total_timeout"
    assert isinstance(timeout_log["budget_ms"], int)
    assert isinstance(timeout_log["elapsed_ms"], int)
    assert "message" not in timeout_log


def test_route_records_timeout_metric(tmp_path) -> None:
    from app.main import app

    _post(app, _blocking_llm(), tmp_path, budget_ms=50)
    snap = MetricsCollector().snapshot()
    assert snap["cognition_timeout"]["python_total_timeout"] == 1


@pytest.mark.asyncio
async def test_late_completion_after_deadline_writes_nothing(tmp_path) -> None:  # Test 21
    """The provider finishes with a perfectly good fact AFTER the budget is
    gone. Deterministic: the route is released only once it has already 504'd."""
    from app.main import app

    release = asyncio.Event()
    late = CognitionResponse(
        symbolic_inference="user owns a red bicycle",
        natural_language_response="Nice bike!",
        world_model_update=__import__(
            "app.models.schemas", fromlist=["WorldModelUpdate"]
        ).WorldModelUpdate(
            triple=__import__("app.models.schemas", fromlist=["WorldModelTriple"]).WorldModelTriple(
                subject="user", predicate="owns", object="a ghost fact"
            ),
            confidence=0.9,
            source="explicit_statement",
        ),
    )
    llm = _blocking_llm(release=release, result=late)
    memory = _mount(app, llm, tmp_path)
    try:
        client = TestClient(app)
        r = client.post(
            "/api/cognition",
            json={"message": "what do I own", "session_id": "s1"},
            headers={"X-Aria-Owner": "o", DEADLINE_HEADER: "50"},
        )
        assert r.status_code == 504
        release.set()                 # the provider "returns" only now
        await asyncio.sleep(0.05)     # give any abandoned work a chance to misbehave
        memory.store_triple.assert_not_awaited()
        assert "a ghost fact" not in r.text
    finally:
        app.dependency_overrides.clear()


def test_expired_budget_header_is_refused_immediately(tmp_path) -> None:
    from app.main import app

    llm = MagicMock()
    llm.complete = AsyncMock(
        return_value=CognitionResponse(symbolic_inference="", natural_language_response="hi")
    )
    r, memory = _post(app, llm, tmp_path, budget_ms=0)
    assert r.status_code == 504
    llm.complete.assert_not_awaited()
    memory.store_triple.assert_not_awaited()


# ── Tests 12, 17, 18, 20: the healthy paths are untouched ────────────────────


def test_valid_turn_within_budget_still_writes_memory(tmp_path) -> None:  # Test 12
    from app.main import app

    client, _ = _client()
    r, memory = _post(app, client, tmp_path, budget_ms=15000)
    assert r.status_code == 200
    assert r.json()["natural_language_response"] == "Nice bike!"
    memory.store_triple.assert_awaited_once()
    assert memory.store_triple.await_args.kwargs["obj"] == "a red bicycle"


def test_valid_turn_without_a_budget_header_still_works(tmp_path) -> None:
    from app.main import app

    client, _ = _client()
    r, memory = _post(app, client, tmp_path, budget_ms=None)
    assert r.status_code == 200
    memory.store_triple.assert_awaited_once()


def test_malformed_response_is_r5_not_a_timeout(tmp_path) -> None:  # Test 17
    from app.main import app

    client, _ = _client(AsyncMock(return_value=_message("not json at all")))
    r, memory = _post(app, client, tmp_path, budget_ms=15000)
    assert r.status_code == 200                       # not 504
    assert r.json()["natural_language_response"] == SAFE_FALLBACK_RESPONSE
    memory.store_triple.assert_not_awaited()
    assert MetricsCollector().snapshot()["cognition_timeout"] == {}


@pytest.mark.asyncio
async def test_r4_telemetry_survives_and_is_not_fabricated_on_timeout() -> None:  # Test 18
    client, _ = _client()
    with capture_all_levels() as logs:
        await _turn(client, deadline=time.monotonic() + 5.0)
    call = next(e for e in logs if e.get("event") == "llm api call")
    assert call["input_tokens"] == 100 and call["cache_status"] == "none"

    MetricsCollector()._prompt_cache = {}
    blocked, _ = _client(AsyncMock(side_effect=CognitionDeadlineError("gone")))
    with pytest.raises(CognitionDeadlineError), capture_all_levels() as logs2:
        await _turn(blocked, deadline=time.monotonic() + 5.0)
    assert not [e for e in logs2 if e.get("event") == "llm api call"]
    assert MetricsCollector().snapshot()["prompt_cache"] == {}   # no invented counts


def test_deadline_error_is_not_an_r5_response_failure() -> None:
    # Code review P3 / mutation (f): if CognitionDeadlineError ever became an
    # LLMResponseError, a timeout would silently turn into the R5 safe fallback
    # with a 200 instead of a 504.
    from app.cognition.llm import LLMResponseError

    assert not issubclass(CognitionDeadlineError, LLMResponseError)


def _freeze_route_clock(monkeypatch, *, at_start: float, at_check: float) -> None:
    """Drive the route's clock only: the first read builds the deadline, every
    later read is a side-effect expiry check. The llm module is pinned to
    ``at_start`` so the provider always sees the full budget — this isolates
    the write guard from the provider guard, which has its own tests."""
    reads = iter([at_start] + [at_check] * 50)
    monkeypatch.setattr(route_mod, "_now", lambda: next(reads))
    monkeypatch.setattr(llm_mod, "_now", lambda: at_start)


def test_expired_turn_does_not_begin_the_fact_write(tmp_path, monkeypatch) -> None:  # Test 11
    """Code review P2: the previous guard was never exercised — the deadline
    always expired inside complete(). Here the provider returns a good fact and
    the budget is gone by the time the write would start."""
    from app.main import app

    _freeze_route_clock(monkeypatch, at_start=0.0, at_check=1000.0)
    client, _ = _client()
    r, memory = _post(app, client, tmp_path, budget_ms=15000)
    assert r.status_code == 200                      # the turn itself completed
    memory.store_triple.assert_not_awaited()         # but nothing durable began


def test_expired_turn_does_not_register_a_spatial_anchor(tmp_path, monkeypatch) -> None:
    """Same for the anchor write, which is durable SQLite in a threadpool."""
    from app.api.cognition_route import get_bridge, get_client, get_memory
    from app.main import app
    from app.spatial.anchor_registry import AnchorRegistry
    from app.spatial.gesture_anchor_bridge import GestureAnchorBridge

    _freeze_route_clock(monkeypatch, at_start=0.0, at_check=1000.0)
    registry = AnchorRegistry(db_path=tmp_path / "a.db")
    llm, _ = _client()
    memory = MagicMock()
    memory.loaded = True
    memory.store_triple = AsyncMock(return_value=True)
    memory.query_relevant = AsyncMock(return_value=[])
    memory.deletion_generation = MagicMock(return_value=0)
    app.dependency_overrides[get_client] = lambda: llm
    app.dependency_overrides[get_memory] = lambda: memory
    app.dependency_overrides[get_bridge] = lambda: GestureAnchorBridge(registry)
    try:
        r = TestClient(app).post(
            "/api/cognition",
            json={
                "message": "look at that", "session_id": "s1",
                "gesture": "point", "pointing_vector": [0.1, -0.2, 0.9],
            },
            headers={"X-Aria-Owner": "o", DEADLINE_HEADER: "15000"},
        )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["spatial_event"] is None
    assert registry.list_anchors("o") == []          # nothing durable landed


def test_write_margin_refuses_a_write_it_cannot_finish(tmp_path, monkeypatch) -> None:
    """Inside the margin the budget is not yet spent, but there is not enough
    left to begin a threadpool write that cannot be abandoned."""
    from app.main import app

    # 0.1s of budget left: not expired, but under WRITE_MARGIN_SECONDS.
    _freeze_route_clock(monkeypatch, at_start=0.0, at_check=15.0 - 0.1)
    assert WRITE_MARGIN_SECONDS > 0.1
    client, _ = _client()
    r, memory = _post(app, client, tmp_path, budget_ms=15000)
    assert r.status_code == 200
    memory.store_triple.assert_not_awaited()


def test_healthy_turn_with_budget_left_still_writes(tmp_path, monkeypatch) -> None:  # Test 12
    from app.main import app

    _freeze_route_clock(monkeypatch, at_start=0.0, at_check=1.0)   # 14s left
    client, _ = _client()
    r, memory = _post(app, client, tmp_path, budget_ms=15000)
    assert r.status_code == 200
    memory.store_triple.assert_awaited_once()


@pytest.mark.asyncio
async def test_caller_cancellation_is_counted_and_re_raised(tmp_path) -> None:  # Test 20
    """Cancellation is its own category AND still propagates — never swallowed,
    never turned into a response."""
    from app.api.cognition_route import cognition

    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=asyncio.CancelledError())
    memory = MagicMock()
    memory.query_relevant = AsyncMock(return_value=[])
    memory.deletion_generation = MagicMock(return_value=0)
    memory.store_triple = AsyncMock()
    req = MagicMock(
        message="hi", vision_state=PerceptionFrame(), conversation_history=[],
        working_memory=[], gesture="none", two_hand_gesture="NONE", session_id="s1",
    )
    request = SimpleNamespace(headers={DEADLINE_HEADER: "15000"})

    with pytest.raises(asyncio.CancelledError):
        await cognition(req, request, llm, memory, MagicMock(), "o")

    assert MetricsCollector().snapshot()["cognition_timeout"]["cancelled"] == 1
    memory.store_triple.assert_not_awaited()


def test_caller_cancellation_is_distinguishable_from_deadline() -> None:  # Test 20 (helper)
    from app.api.cognition_route import _timeout_category

    assert _timeout_category(asyncio.CancelledError()) == "cancelled"
    assert _timeout_category(TimeoutError()) == "python_total_timeout"
    assert _timeout_category(CognitionDeadlineError("x")) == "python_total_timeout"
