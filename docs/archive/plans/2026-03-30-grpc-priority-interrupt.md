# Week 3: Bi-directional gRPC + Priority Interrupt Pattern

> **Status:** PENDING APPROVAL — do not write implementation code until approved.

---

## What we're building and why

Week 1 added a one-way perception pipe (Python vision server → Go gRPC client on port 50051). Week 3 activates the reverse channel: Go becomes a gRPC **server** for `CognitionService`, Python becomes a client that can push events *into* the Go backend — most importantly, a kill signal when the user exits the camera frame.

The hard constraint is **<100ms interrupt latency**: from the moment the vision worker decides the user is gone (500ms no-face threshold) to the moment the active Claude API HTTP stream is cancelled in Go. The design below achieves this without any polling — the gRPC signal propagates synchronously through a shared in-process cancel registry.

---

## Architecture

```
Python vision_worker (--grpc)
  │
  │  PerceptionService.StreamFrames  (Go CLIENT → Python SERVER, port 50051)
  │  [unchanged from Week 1]
  │
  └─ CognitionService.StreamCognition  (Go SERVER ← Python CLIENT, port 50052)
       │
       ▼
     Go grpc_server.go
       │  interrupt_signal=true
       ├─ StreamRegistry.Cancel(session_id)
       │       └─ ctx.cancel()  →  kills active http.Get to Python FastAPI
       └─ hub.Broadcast({"type":"aria_interrupt"})
               │
               ▼
           useWebSocket.ts
               ├─ abortCognitionRef.current()  →  AbortController.abort()
               ├─ setIsThinking(false)
               └─ setIsSpeaking(false)
```

**Port layout:**
- `50051` — Python PerceptionService server (Go is client) — **unchanged**
- `50052` — Go CognitionService server (Python is client) — **new this week**

The spec says "same port (50051)." That is not achievable: Python already holds 50051 for `PerceptionService`. Go's `CognitionService` server must bind a separate port. 50052 is the natural choice; it will be added to `config.go` so it is not a magic number.

---

## File-by-file breakdown

### Task 1 — Activate proto fields + regenerate stubs

| File | Change |
|---|---|
| `proto/perception.proto` | Remove tags 9–10 from `HandGestureEvent.reserved`; add `uint32 interrupt_priority = 9` and `string stream_id = 10` as real fields |
| `backend/gen/go/perception/v1/perception.pb.go` | Regenerated (buf generate) |
| `backend/gen/go/perception/v1/perception_grpc.pb.go` | Regenerated (buf generate) |
| `backend/gen/python/perception/v1/perception_pb2.py` | Regenerated |
| `backend/gen/python/perception/v1/perception_pb2_grpc.py` | Regenerated; verify `from perception.v1 import perception_pb2` import fix still holds |

**Why activate these fields now?** `interrupt_priority` lets the Go server route a kill signal to the highest-priority active stream when multiple sessions exist. `stream_id` carries the exact gRPC stream identifier so the registry can be precise. Both are referenced in `HandGestureEvent` payloads that Python can embed in `CognitionRequest.gesture_event`.

**Regeneration command:**
```bash
cd proto && buf generate
# fallback if BSR unavailable:
cd proto && protoc \
  --go_out=../backend/gen/go --go_opt=module=github.com/sucheet2000/aria/backend \
  --go-grpc_out=../backend/gen/go --go-grpc_opt=module=github.com/sucheet2000/aria/backend \
  perception.proto
```

Then regenerate Python stubs:
```bash
cd proto && /Users/sucheetboppana/miniconda-arm64/bin/python3 -m grpc_tools.protoc \
  -I. \
  --python_out=../backend/gen/python \
  --grpc_python_out=../backend/gen/python \
  perception.proto
# move flat output into package:
mv backend/gen/python/perception_pb2.py     backend/gen/python/perception/v1/
mv backend/gen/python/perception_pb2_grpc.py backend/gen/python/perception/v1/
# verify import fix:
grep "^from perception" backend/gen/python/perception/v1/perception_pb2_grpc.py
# if missing, re-apply:
sed -i '' 's/^import perception_pb2/from perception.v1 import perception_pb2/' \
  backend/gen/python/perception/v1/perception_pb2_grpc.py
```

---

### Task 2 — Go: `StreamRegistry` + `CognitionService` gRPC server

**New file: `backend/internal/cognition/stream_registry.go`**

A thread-safe map from `session_id → context.CancelFunc`. Rules:
- `Register(id, cancel)` — stores the cancel func; if a pending cancel exists for this id (interrupt arrived before registration), call it immediately.
- `Cancel(id)` — calls cancel if present, deletes entry.
- `Unregister(id)` — deletes entry without calling cancel (cleanup after normal completion).

The "pending cancel" slot handles the race where an interrupt arrives between the start of an HTTP request and the `Register` call (a ~microsecond window in practice, but worth closing).

**New file: `backend/internal/cognition/grpc_server.go`**

```go
// Implements perceptionv1.CognitionServiceServer
type CognitionGRPCServer struct {
    perceptionv1.UnimplementedCognitionServiceServer
    registry *StreamRegistry
    hub      Broadcaster  // same interface used by vision.GRPCClient
}
```

`StreamCognition` method:
```go
for {
    req, err := stream.Recv()
    // handle EOF / error
    switch p := req.Payload.(type) {
    case *perceptionv1.CognitionRequest_InterruptSignal:
        if p.InterruptSignal {
            s.registry.Cancel(req.SessionId)
            s.hub.Broadcast(ariaInterruptJSON)  // {"type":"aria_interrupt","session_id":"..."}
        }
    case *perceptionv1.CognitionRequest_GestureEvent:
        // marshal to {"type":"gesture_event","payload":{...}} and hub.Broadcast
    case *perceptionv1.CognitionRequest_TextInput:
        // marshal to {"type":"text_input","payload":"..."} and hub.Broadcast
    }
}
```

`RegisterAnchor` — returns the anchor unmodified (stub; spatial anchoring is Week 9).

**Broadcaster interface** — define a local `Broadcaster` interface in this package (`Broadcast([]byte)`) or import from server package. The hub already satisfies it.

**Modify `backend/internal/cognition/handler.go`**

Inject `*StreamRegistry` into `Handler`. In `ServeHTTP`:
```go
sessionID := req.SessionID  // may be empty string — treat as "default"
if sessionID == "" {
    sessionID = "default"
}
ctx, cancel := context.WithCancel(r.Context())
defer cancel()
h.registry.Register(sessionID, cancel)
defer h.registry.Unregister(sessionID)
result, err := h.client.Complete(ctx, req)
```

Also add `SessionID string \`json:"session_id,omitempty"\`` to the `CognitionRequest` struct (optional field — omitempty so existing clients sending no session_id still work and fall back to "default").

---

### Task 3 — Python: send interrupt when user exits frame

**Modify `backend/app/pipeline/vision_worker.py`**

Add to both `run_synthetic` and `run_camera` when `args.grpc` is True:

```python
# Set up CognitionService client on port 50052
import threading
import queue as _queue
from perception.v1 import perception_pb2, perception_pb2_grpc
import grpc as _grpc

_interrupt_queue: _queue.Queue = _queue.Queue()

def _cognition_request_gen(q: _queue.Queue):
    while True:
        req = q.get()
        if req is None:
            return
        yield req

_cog_channel = _grpc.insecure_channel("localhost:50052")
_cog_stub = perception_pb2_grpc.CognitionServiceStub(_cog_channel)
threading.Thread(
    target=lambda: list(_cog_stub.StreamCognition(_cognition_request_gen(_interrupt_queue))),
    daemon=True
).start()
```

Face-exit tracking variables (initialized before the frame loop):
```python
_last_face_time: float = time.time()
_face_was_detected: bool = False
_interrupt_sent: bool = False
```

In the frame loop, after face detection:
```python
face_detected = bool(face_result.face_landmarks)  # or len(face_landmarks_list) > 0

if face_detected:
    _last_face_time = time.time()
    _face_was_detected = True
    _interrupt_sent = False          # reset so next exit triggers again
elif _face_was_detected and not _interrupt_sent:
    if time.time() - _last_face_time >= 0.5:
        _interrupt_queue.put(
            perception_pb2.CognitionRequest(
                session_id="default",
                interrupt_signal=True,
            )
        )
        _interrupt_sent = True
```

`run_synthetic` always has `face_detected = True` (fake face), so it will never fire the interrupt in normal operation. For testing, we can temporarily set it to `False`.

**The `--grpc` flag default stays False** — no behaviour change unless flag is passed.

---

### Task 4 — Go: wire `CognitionService` into `main.go`

**Modify `backend/internal/config/config.go`**
- Add `CognitionGRPCAddr string` field, default `":50052"`

**Modify `backend/cmd/server/main.go`**

After creating `hub`, add:

```go
import (
    "net"
    "google.golang.org/grpc"
    perceptionv1 "github.com/sucheet2000/aria/backend/gen/go/perception/v1"
    "github.com/sucheet2000/aria/backend/internal/cognition"
)

// Shared interrupt registry — wired into both gRPC server and HTTP handler
registry := cognition.NewStreamRegistry()

// HTTP cognition handler (already exists — pass registry in)
cognitionClient := cognition.NewClient(cfg, log.Logger)
cognitionHandler := cognition.NewHandler(cognitionClient, registry, log.Logger)

// CognitionService gRPC server on 50052
grpcServer := grpc.NewServer()
cognitionGRPC := cognition.NewCognitionGRPCServer(registry, hub)
perceptionv1.RegisterCognitionServiceServer(grpcServer, cognitionGRPC)

lis, err := net.Listen("tcp", cfg.CognitionGRPCAddr)
if err != nil {
    log.Fatal().Err(err).Msg("failed to bind CognitionService gRPC port")
}
go func() {
    log.Info().Str("addr", cfg.CognitionGRPCAddr).Msg("CognitionService gRPC server started")
    if err := grpcServer.Serve(lis); err != nil && ctx.Err() == nil {
        log.Error().Err(err).Msg("CognitionService gRPC server error")
    }
}()

// Graceful shutdown
go func() {
    <-ctx.Done()
    grpcServer.GracefulStop()
}()
```

The `mux.Handle("/api/cognition", cognitionHandler)` call in `server.go` already wires the HTTP handler; the only change there is passing `registry` through.

---

### Task 5 — Frontend: handle `aria_interrupt`

**Modify `frontend/src/hooks/useCognition.ts`**

Add a module-level abort ref (same pattern as `wsSendRef` in useWebSocket):
```ts
export const abortCognitionRef: { current: (() => void) | null } = { current: null };
```

Inside `sendMessage`, before the fetch:
```ts
const controller = new AbortController();
abortCognitionRef.current = () => controller.abort();
// ... existing fetch call ...
// In finally:
abortCognitionRef.current = null;
```

Add a `useEffect` that listens for the `aria:interrupt` custom event and aborts + resets state:
```ts
useEffect(() => {
  function handleInterrupt() {
    abortCognitionRef.current?.();
    setIsLoading(false);
    setIsThinking(false);
    useAriaStore.getState().setIsSpeaking(false);
  }
  window.addEventListener("aria:interrupt", handleInterrupt);
  return () => window.removeEventListener("aria:interrupt", handleInterrupt);
}, [setIsThinking]);
```

**Modify `frontend/src/hooks/useWebSocket.ts`**

Add import of `abortCognitionRef` from useCognition. In the `ws.onmessage` handler, add before the closing `catch`:
```ts
if (msg.type === "aria_interrupt") {
  abortCognitionRef.current?.();
  window.dispatchEvent(new CustomEvent("aria:interrupt"));
  useAriaStore.getState().setIsSpeaking(false);
  useAriaStore.getState().setIsThinking(false);
  return;
}
```

**Note:** TTS playback — check `ariaStore.ts` for whether `setIsSpeaking(false)` is sufficient to stop audio or if a separate `stopTTS()` call exists. If TTS is driven by an effect that watches `isSpeaking`, setting it to false is enough. Verify during implementation.

---

### Task 6 — Tests

**New file: `backend/internal/cognition/grpc_server_test.go`**

```go
// Test 1: interrupt_signal on a registered session calls its cancel func
func TestInterruptCancelsRegisteredStream(t *testing.T) {
    // Setup StreamRegistry, register a cancel func for "test-session"
    // Create CognitionGRPCServer with registry and a mock broadcaster
    // Simulate receiving CognitionRequest{session_id:"test-session", interrupt_signal:true}
    // Assert: cancel was called, broadcaster received {"type":"aria_interrupt",...}
}

// Test 2: interrupt with no registered session is a no-op (does not panic)
func TestInterruptNoSession(t *testing.T) { ... }

// Test 3: Register-Cancel-Register sequence works correctly (no stale cancel)
func TestRegistryCancelCycle(t *testing.T) { ... }
```

Use a fake gRPC stream (implement `CognitionService_StreamCognitionServer` with a channel-backed Recv).

**New file: `backend/tests/test_vision_interrupt.py`**

```python
# Test 1: after 500ms no-face, interrupt_queue gets a CognitionRequest with interrupt_signal=True
def test_500ms_no_face_triggers_interrupt(): ...

# Test 2: face redetected before 500ms resets the timer (no interrupt sent)
def test_face_redetected_before_timeout_no_interrupt(): ...

# Test 3: after interrupt sent, subsequent no-face frames do not re-send
def test_interrupt_not_sent_twice(): ...
```

These tests extract the face-exit logic into a pure function (no real gRPC calls) for fast unit testing.

**All 80 existing tests must still pass** — run full suite as final check.

---

### Task 7 — Build verification

```bash
# Go build + vet
cd backend && go build ./... && go vet ./...

# Full Python test suite
PYTHONPATH=backend python3 -m pytest backend/tests/ -v | tail -20

# Frontend build
cd frontend && npm run build
```

---

### Task 8 — Adversarial review

```
/codex:adversarial-review --base main
```

Focus areas to flag to the reviewer:
1. **Race condition:** interrupt arrives between HTTP request start and `StreamRegistry.Register` call
2. **Cancel leak:** if HTTP handler panics before `defer Unregister`, entry stays in map
3. **Multiple streams:** two browser tabs = two "default" sessions; second `Register` overwrites first cancel func — the first stream leaks
4. **Python thread safety:** `_last_face_time` / `_interrupt_sent` touched only in the frame loop (single-threaded) — safe, but confirm `_interrupt_queue.put` is called from the correct thread

---

### Task 9 — Commit

```
feat(week3): bi-directional gRPC + priority interrupt — <100ms kill signal

- Activate interrupt_priority/stream_id in HandGestureEvent (tags 9-10)
- Go CognitionService gRPC server on :50052 (StreamRegistry + cancel propagation)
- Python vision_worker sends interrupt after 500ms no-face via CognitionService
- HTTP cognition handler wired to StreamRegistry for context cancellation
- Frontend handles aria_interrupt: aborts fetch, stops TTS, resets to idle
- Tests: Go stream cancellation, Python 500ms timeout logic
```

---

## Dependencies to add

| Dep | Where | Notes |
|---|---|---|
| None new | Go | `google.golang.org/grpc` already in go.mod from Week 1 |
| None new | Python | `grpcio` already installed from Week 1 |

---

## Risks and tradeoffs

| Risk | Severity | Mitigation |
|---|---|---|
| Port 50052 hardcoded | Low | Added to `config.go` as `CognitionGRPCAddr` |
| Single "default" session key | Medium | Sufficient for Week 3 (single user); multi-session in Week 4 |
| gRPC insecure (no TLS) | Low | Localhost-only; acceptable for dev |
| Pending-cancel race | Low | StreamRegistry stores a pending cancel and applies it on Register |
| Python thread for StreamCognition | Low | Daemon thread — killed on process exit; queue is the sync boundary |
| `--grpc` defaults to False | None | Interrupt feature inactive unless flag passed — matches Week 1 convention |
