# Known Issues — v3.0.0

Tracked at time of v3.0.0 tag. All items below are LOW severity (no data
loss, no crash under normal conditions). Fix targets are noted per item.

---

## KI-001 — `get_bridge()` / `get_memory()` non-atomic lazy init (backend)

**File:** `backend/app/api/cognition_route.py`
**Severity:** LOW

The `get_bridge()` and `get_memory()` functions use a check-then-set
pattern (`if _bridge is None: _bridge = ...`) without a lock. Under a
single-worker uvicorn deployment (the current default) there is no race
because the async event loop processes requests sequentially. If the
server is ever run with `--workers N` (multiple processes), each process
gets its own global, so they still don't race. The only actual risk is a
multi-threaded WSGI deployment, which we do not use.

**Target:** Sprint 7 — refactor singletons to FastAPI `Depends()` with
`lru_cache`.

---

## KI-002 — `metrics.py` / `metrics_route.py` not yet implemented

**Severity:** LOW / N/A

The Sprint 6 review spec requested review of a `metrics.py` and
`/metrics` endpoint. Neither file exists in v3. No PII leak risk exists
because the code is absent.

**Target:** Sprint 7 — add Prometheus-compatible `/metrics` endpoint with
thread-safe Histogram behind a `threading.Lock`.

---

## KI-003 — `VRMAvatar.tsx` silent fallback on malformed vision frame (frontend)

**File:** `frontend/src/components/VRMAvatar.tsx`
**Severity:** LOW (guarded in v3.0.0 hardening commit)

`headPose` is sourced from the raw WebSocket vision frame. A null guard
(`if (head && headPose)`) was added in the v3.0.0 hardening commit. If
a malformed frame arrives with `head_pose: null`, the head bone simply
holds its last valid rotation rather than crashing. The `VRMErrorBoundary`
would catch any uncaught error and fall back to `Avatar3D`, but that
degradation path is now harder to trigger.

**Target:** Sprint 7 — add Zod validation on the incoming WebSocket frame
shape so malformed frames are rejected at the boundary.

---

## KI-004 — `AnchorMarker` tests do not cover the `useFrame` animation path

**File:** `frontend/src/spatial/AnchorMarker.tsx`
**Severity:** LOW

The `useWorldModel` store actions are tested in isolation. The `useFrame`
velocity-decay animation loop and the `useEffect` ref-sync on new
`anchor.velocity` values are not covered by any automated test.

**Target:** Sprint 7 — add vitest + `@react-three/test-renderer` tests
for the velocity decay loop using a mock RAF.

---

## KI-005 — `getLabelColor` and `AnchorMarker` component have no unit tests

**File:** `frontend/src/spatial/AnchorMarker.tsx`
**Severity:** LOW

`getLabelColor` is pure and easily testable. `AnchorMarker` needs a
Three.js render context. Both are untested.

**Target:** Sprint 7.
