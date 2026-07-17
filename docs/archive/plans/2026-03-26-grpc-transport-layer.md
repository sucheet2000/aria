# Week 1: gRPC Transport Layer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the Python vision worker's stdout JSON pipe with a typed gRPC stream so Go connects as a gRPC client streaming `PerceptionFrame` protos.

**Architecture:** Python `vision_worker.py` (when `--grpc` flag is set) starts a gRPC server on port 50051 and pushes `PerceptionFrame` protos to a queue; a new Go `GRPCClient` in `backend/internal/vision/grpc_client.go` connects, receives frames, and converts them to the existing `{"type":"vision_state","payload":{...}}` JSON format before broadcasting to the hub. The existing subprocess `Worker` in `worker.go` is untouched this sprint.

**Tech Stack:** protobuf v3, buf CLI (code gen), grpcio + grpcio-tools (Python), protoc-gen-go + protoc-gen-go-grpc (Go), structlog (Python logging)

---

## Critical Notes Before Starting

### Proto vs. Spec Discrepancy
The existing `proto/perception.proto` only defines `CognitionService`. The spec requires a separate **`PerceptionService`** with a server-streaming `StreamFrames` RPC. New messages (`PerceptionFrame`, `HandData`, `StreamRequest`) must be added to the proto in Task 1.

### go_package Must Change
The current `go_package` in `perception.proto` is `github.com/sucheet2000/aria/proto/perception/v1;perceptionv1`. This path is **outside** the Go module (`github.com/sucheet2000/aria/backend`) and cannot be imported. It must be changed to `github.com/sucheet2000/aria/backend/gen/go/perception/v1;perceptionv1`.

### Protoc `module=` Flag
To get output at `backend/gen/go/perception/v1/`, use `--go_opt=module=github.com/sucheet2000/aria/backend`. This strips the module prefix from the go_package import path to derive the output subdirectory.

### Go Code Generation Precedes Tests
Generated `.pb.go` files must exist before the Go package will compile, so the TDD cycle here is: add proto → generate stubs → write failing test → implement → pass.

### Do NOT Touch
- `backend/internal/vision/worker.go` — subprocess manager stays untouched
- Hub, WebSocket, or any frontend code
- Existing tests must all continue to pass

---

## Task 1: Extend proto — add PerceptionService messages

**Files:**
- Modify: `proto/perception.proto`

### Step 1: Add new messages and service to the proto

Open `proto/perception.proto`. Make two changes:

**a) Update `go_package`** (line 7). Change from:
```proto
option go_package = "github.com/sucheet2000/aria/proto/perception/v1;perceptionv1";
```
To:
```proto
option go_package = "github.com/sucheet2000/aria/backend/gen/go/perception/v1;perceptionv1";
```

**b) Append the following block at the end of the file** (after the closing `}` of `CognitionService`):

```proto
// ─── PerceptionService (Week 1 gRPC Transport) ───────────────────────────────

// HandData carries the 21 MediaPipe landmarks for a single detected hand.
// Separated from HandGestureEvent so the raw transport layer (PerceptionService)
// can stream all landmark data without requiring a gesture classification.
message HandData {
  Handedness hand           = 1;
  repeated Point3D landmarks = 2; // exactly 21 per MediaPipe standard
}

// PerceptionFrame is the per-frame payload streamed from the Python vision worker
// to the Go backend over PerceptionService.StreamFrames.
// It replaces the stdout JSON pipe introduced in Week 0.
//
// Tag budget (mirrors HandGestureEvent discipline):
//   1 : hands      — repeated HandData; primary payload, lowest tag for 1-byte header
//   2 : timestamp_us — int64 µs; consistent with HandGestureEvent.timestamp_us
//   3 : session_id — string; session re-hydration key (Week 2)
message PerceptionFrame {
  repeated HandData hands = 1;
  int64 timestamp_us      = 2;
  string session_id       = 3;
}

// StreamRequest is sent by the Go client when opening a StreamFrames call.
message StreamRequest {
  string session_id = 1;
}

// PerceptionService is the simple one-directional transport between the Python
// vision layer and the Go backend. Frames flow Python → Go.
// Week 3 will extend this to bidirectional via CognitionService.
service PerceptionService {
  // StreamFrames opens a server-streaming RPC. The Python server yields one
  // PerceptionFrame per processed camera frame; Go reads and broadcasts them.
  rpc StreamFrames(StreamRequest) returns (stream PerceptionFrame);
}
```

### Step 2: Verify proto syntax (no compile yet — just visual check)

The file should now have two services: `CognitionService` (existing) and `PerceptionService` (new). No other changes.

### Step 3: Commit proto change

```bash
cd /Users/sucheetboppana/aria
git add proto/perception.proto
git commit -m "feat(proto): add PerceptionService, PerceptionFrame, HandData, StreamRequest for Week 1 gRPC transport"
```

---

## Task 2: Install tools

**Files:** none (environment setup)

### Step 1: Install buf CLI

```bash
which buf || brew install bufbuild/buf/buf
buf --version
```
Expected: prints version like `1.x.x`

### Step 2: Install Python gRPC tools

```bash
/Users/sucheetboppana/miniconda-arm64/bin/pip install grpcio grpcio-tools --break-system-packages
```
Expected: `Successfully installed grpcio-x.x.x grpcio-tools-x.x.x` (or "already satisfied")

### Step 3: Install Go protoc plugins

```bash
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest
```

Verify they are on PATH:
```bash
which protoc-gen-go
which protoc-gen-go-grpc
```
Expected: paths under `$GOPATH/bin` or `$HOME/go/bin`

**STOP if any of these fail** — do not proceed without working tools.

---

## Task 3: Create buf configuration files

**Files:**
- Create: `proto/buf.yaml`
- Create: `proto/buf.gen.yaml`

### Step 1: Create `proto/buf.yaml`

```yaml
version: v2
modules:
  - path: .
lint:
  use:
    - STANDARD
breaking:
  use:
    - FILE
```

### Step 2: Create `proto/buf.gen.yaml`

Note: uses `module=` option (not `paths=source_relative`) so output lands at `backend/gen/go/perception/v1/` matching the updated `go_package` import path.

```yaml
version: v2
plugins:
  - remote: buf.build/protocolbuffers/go
    out: ../backend/gen/go
    opt:
      - module=github.com/sucheet2000/aria/backend
  - remote: buf.build/grpc/go
    out: ../backend/gen/go
    opt:
      - module=github.com/sucheet2000/aria/backend
```

---

## Task 4: Generate Go stubs

**Files:**
- Create: `backend/gen/go/perception/v1/perception.pb.go`
- Create: `backend/gen/go/perception/v1/perception_grpc.pb.go`

### Step 1: Create output directory

```bash
mkdir -p /Users/sucheetboppana/aria/backend/gen/go
```

### Step 2: Try buf first (requires network for remote plugins)

```bash
cd /Users/sucheetboppana/aria/proto && buf generate
```

If this succeeds, verify:
```bash
ls /Users/sucheetboppana/aria/backend/gen/go/perception/v1/
```
Expected: `perception.pb.go` and `perception_grpc.pb.go`

### Step 3: Fallback — local protoc if buf remote plugins fail

If buf fails (network issue / BSR unavailable), use local protoc:

```bash
cd /Users/sucheetboppana/aria/proto && protoc \
  --go_out=../backend/gen/go \
  --go_opt=module=github.com/sucheet2000/aria/backend \
  --go-grpc_out=../backend/gen/go \
  --go-grpc_opt=module=github.com/sucheet2000/aria/backend \
  perception.proto
```

Verify output:
```bash
ls /Users/sucheetboppana/aria/backend/gen/go/perception/v1/
```
Expected: `perception.pb.go`, `perception_grpc.pb.go`

### Step 4: Quick sanity-check on generated file

```bash
head -5 /Users/sucheetboppana/aria/backend/gen/go/perception/v1/perception.pb.go
```
Expected: starts with `// Code generated by protoc-gen-go.` and `package perceptionv1`

---

## Task 5: Generate Python stubs

**Files:**
- Create: `backend/gen/python/perception/v1/perception_pb2.py`
- Create: `backend/gen/python/perception/v1/perception_pb2_grpc.py`
- Create: `backend/gen/python/perception/__init__.py`
- Create: `backend/gen/python/perception/v1/__init__.py`

### Step 1: Generate flat stubs

```bash
mkdir -p /Users/sucheetboppana/aria/backend/gen/python

cd /Users/sucheetboppana/aria/proto && \
  /Users/sucheetboppana/miniconda-arm64/bin/python3 -m grpc_tools.protoc \
    -I. \
    --python_out=../backend/gen/python \
    --grpc_python_out=../backend/gen/python \
    perception.proto
```

This creates flat files:
- `backend/gen/python/perception_pb2.py`
- `backend/gen/python/perception_pb2_grpc.py`

### Step 2: Move into package structure

```bash
mkdir -p /Users/sucheetboppana/aria/backend/gen/python/perception/v1
touch /Users/sucheetboppana/aria/backend/gen/python/perception/__init__.py
touch /Users/sucheetboppana/aria/backend/gen/python/perception/v1/__init__.py
mv /Users/sucheetboppana/aria/backend/gen/python/perception_pb2.py \
   /Users/sucheetboppana/aria/backend/gen/python/perception/v1/
mv /Users/sucheetboppana/aria/backend/gen/python/perception_pb2_grpc.py \
   /Users/sucheetboppana/aria/backend/gen/python/perception/v1/
```

### Step 3: Fix the relative import in the grpc stub

`grpc_tools.protoc` generates `import perception_pb2 as perception__pb2` in `perception_pb2_grpc.py`. This breaks once the file is in a package. Fix it:

```bash
sed -i '' 's/^import perception_pb2/from perception.v1 import perception_pb2/' \
  /Users/sucheetboppana/aria/backend/gen/python/perception/v1/perception_pb2_grpc.py
```

### Step 4: Verify import works

```bash
cd /Users/sucheetboppana/aria && \
  PYTHONPATH=backend/gen/python \
  /Users/sucheetboppana/miniconda-arm64/bin/python3 -c \
    "from perception.v1 import perception_pb2; print('OK')"
```
Expected: `OK`

---

## Task 6: Update Go module for gRPC dependency

**Files:**
- Modify: `backend/go.mod`
- Modify: `backend/go.sum`

### Step 1: Add gRPC dependencies

```bash
cd /Users/sucheetboppana/aria/backend && \
  go get google.golang.org/grpc@v1.64.0 && \
  go get google.golang.org/protobuf@v1.34.1
```

### Step 2: Tidy the module

```bash
cd /Users/sucheetboppana/aria/backend && go mod tidy
```

### Step 3: Verify go.mod has the new requires

```bash
grep -E "grpc|protobuf" /Users/sucheetboppana/aria/backend/go.mod
```
Expected lines like:
```
google.golang.org/grpc v1.64.0
google.golang.org/protobuf v1.34.1
```

---

## Task 7: Write failing Go test for GRPCClient.broadcastFrame

**Files:**
- Create: `backend/internal/vision/grpc_client_test.go`

### Step 1: Write the test

```go
package vision

import (
	"encoding/json"
	"testing"

	perceptionv1 "github.com/sucheet2000/aria/backend/gen/go/perception/v1"
)

type mockBroadcaster struct {
	received [][]byte
}

func (m *mockBroadcaster) Broadcast(data []byte) {
	m.received = append(m.received, data)
}

func TestBroadcastFrame_ProducesVisionStateJSON(t *testing.T) {
	hub := &mockBroadcaster{}
	client := NewGRPCClient(hub)

	frame := &perceptionv1.PerceptionFrame{
		Hands: []*perceptionv1.HandData{
			{
				Landmarks: []*perceptionv1.Point3D{
					{X: 0.1, Y: 0.2, Z: 0.3},
					{X: 0.4, Y: 0.5, Z: 0.6},
				},
			},
		},
	}

	client.broadcastFrame(frame)

	if len(hub.received) != 1 {
		t.Fatalf("expected 1 broadcast, got %d", len(hub.received))
	}

	var msg map[string]interface{}
	if err := json.Unmarshal(hub.received[0], &msg); err != nil {
		t.Fatalf("broadcast is not valid JSON: %v", err)
	}
	if msg["type"] != "vision_state" {
		t.Errorf("expected type=vision_state, got %v", msg["type"])
	}
	payload, ok := msg["payload"].(map[string]interface{})
	if !ok {
		t.Fatalf("payload is not a map, got %T", msg["payload"])
	}
	hands, ok := payload["hand_landmarks"].([]interface{})
	if !ok {
		t.Fatalf("hand_landmarks is not a list, got %T", payload["hand_landmarks"])
	}
	if len(hands) != 2 {
		t.Errorf("expected 2 hand landmarks, got %d", len(hands))
	}
}

func TestBroadcastFrame_EmptyFrameStillBroadcasts(t *testing.T) {
	hub := &mockBroadcaster{}
	client := NewGRPCClient(hub)

	client.broadcastFrame(&perceptionv1.PerceptionFrame{})

	if len(hub.received) != 1 {
		t.Fatalf("expected 1 broadcast even for empty frame, got %d", len(hub.received))
	}
	var msg map[string]interface{}
	if err := json.Unmarshal(hub.received[0], &msg); err != nil {
		t.Fatalf("broadcast not valid JSON: %v", err)
	}
	if msg["type"] != "vision_state" {
		t.Errorf("type should be vision_state, got %v", msg["type"])
	}
}
```

### Step 2: Run test to confirm it fails (grpc_client.go doesn't exist yet)

```bash
cd /Users/sucheetboppana/aria/backend && \
  go test ./internal/vision/... -run TestBroadcastFrame -v 2>&1
```
Expected: **FAIL** — `undefined: NewGRPCClient` (or similar compile error)

---

## Task 8: Implement Go gRPC client

**Files:**
- Create: `backend/internal/vision/grpc_client.go`

### Step 1: Write the implementation

```go
package vision

import (
	"context"
	"encoding/json"
	"time"

	perceptionv1 "github.com/sucheet2000/aria/backend/gen/go/perception/v1"
	"github.com/rs/zerolog/log"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

const visionGRPCAddr = "localhost:50051"

// GRPCClient connects to the Python vision gRPC server and streams
// PerceptionFrame messages, broadcasting them to the hub.
// It reuses the Broadcaster interface already defined in worker.go.
type GRPCClient struct {
	hub    Broadcaster
	cancel context.CancelFunc
}

func NewGRPCClient(hub Broadcaster) *GRPCClient {
	return &GRPCClient{hub: hub}
}

// Start connects to the Python vision server and streams frames.
// Retries with 2s backoff on disconnect. Blocks until ctx is cancelled.
func (c *GRPCClient) Start(ctx context.Context) error {
	ctx, c.cancel = context.WithCancel(ctx)
	for {
		if err := c.stream(ctx); err != nil {
			if ctx.Err() != nil {
				return nil
			}
			log.Warn().Err(err).Msg("vision gRPC stream disconnected, retrying in 2s")
			select {
			case <-time.After(2 * time.Second):
			case <-ctx.Done():
				return nil
			}
		}
	}
}

func (c *GRPCClient) stream(ctx context.Context) error {
	conn, err := grpc.NewClient(visionGRPCAddr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		return err
	}
	defer conn.Close()

	client := perceptionv1.NewPerceptionServiceClient(conn)
	stream, err := client.StreamFrames(ctx, &perceptionv1.StreamRequest{
		SessionId: "local",
	})
	if err != nil {
		return err
	}

	log.Info().Str("addr", visionGRPCAddr).Msg("vision gRPC stream connected")
	for {
		frame, err := stream.Recv()
		if err != nil {
			return err
		}
		c.broadcastFrame(frame)
	}
}

// broadcastFrame converts a PerceptionFrame to the existing JSON vision_state
// format so the hub and frontend require zero changes this sprint.
func (c *GRPCClient) broadcastFrame(frame *perceptionv1.PerceptionFrame) {
	// Flatten all hand landmarks into a single list — matches the existing
	// stdout JSON shape the frontend already consumes.
	handLandmarks := [][]float32{}
	for _, hand := range frame.Hands {
		for _, pt := range hand.Landmarks {
			handLandmarks = append(handLandmarks, []float32{pt.X, pt.Y, pt.Z})
		}
	}

	wrapped := map[string]interface{}{
		"type": "vision_state",
		"payload": map[string]interface{}{
			"face_landmarks": []interface{}{},
			"hand_landmarks": handLandmarks,
			"emotion":        "neutral",
			"head_pose":      map[string]float32{"pitch": 0, "yaw": 0, "roll": 0},
		},
	}
	data, err := json.Marshal(wrapped)
	if err != nil {
		return
	}
	c.hub.Broadcast(data)
}

func (c *GRPCClient) Stop() {
	if c.cancel != nil {
		c.cancel()
	}
}
```

### Step 2: Run the tests — expect GREEN

```bash
cd /Users/sucheetboppana/aria/backend && \
  go test ./internal/vision/... -run TestBroadcastFrame -v 2>&1
```
Expected: `PASS` for both `TestBroadcastFrame_ProducesVisionStateJSON` and `TestBroadcastFrame_EmptyFrameStillBroadcasts`

---

## Task 9: Write failing Python test for PerceptionServicer

**Files:**
- Create: `backend/tests/test_vision_grpc_server.py`

### Step 1: Write the test

```python
"""
Tests for the gRPC vision server wrapper.
These tests run against the real generated proto stubs — skips if grpc not installed.
"""
from __future__ import annotations

import queue
import sys
from pathlib import Path

import pytest

grpc = pytest.importorskip("grpc", reason="grpcio not installed")

# Add generated stubs to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend" / "gen" / "python"))

from perception.v1 import perception_pb2  # noqa: E402
from app.pipeline.vision_grpc_server import PerceptionServicer  # noqa: E402


def test_push_frame_enqueues_frame() -> None:
    """push_frame should place the frame onto the internal queue."""
    servicer = PerceptionServicer()
    frame = perception_pb2.PerceptionFrame()
    servicer.push_frame(frame)
    got = servicer._frame_queue.get_nowait()
    assert got is frame


def test_push_frame_drops_when_queue_full() -> None:
    """push_frame must not block or raise when queue is at capacity (maxsize=10)."""
    servicer = PerceptionServicer()
    for _ in range(10):
        servicer.push_frame(perception_pb2.PerceptionFrame())
    # 11th push should be silently dropped
    servicer.push_frame(perception_pb2.PerceptionFrame())
    assert servicer._frame_queue.qsize() == 10


def test_push_frame_with_hand_data() -> None:
    """PerceptionFrame with HandData should round-trip through the queue intact."""
    servicer = PerceptionServicer()
    frame = perception_pb2.PerceptionFrame(
        hands=[
            perception_pb2.HandData(
                landmarks=[perception_pb2.Point3D(x=0.1, y=0.2, z=0.3)]
            )
        ]
    )
    servicer.push_frame(frame)
    got = servicer._frame_queue.get_nowait()
    assert len(got.hands) == 1
    assert got.hands[0].landmarks[0].x == pytest.approx(0.1)
```

### Step 2: Run test — expect FAIL (vision_grpc_server.py doesn't exist yet)

```bash
cd /Users/sucheetboppana/aria && \
  PYTHONPATH=backend \
  /Users/sucheetboppana/miniconda-arm64/bin/python3 \
  -m pytest backend/tests/test_vision_grpc_server.py -v 2>&1
```
Expected: **ERROR** — `ModuleNotFoundError: No module named 'app.pipeline.vision_grpc_server'`

---

## Task 10: Implement Python gRPC server

**Files:**
- Create: `backend/app/pipeline/vision_grpc_server.py`

### Step 1: Write the implementation

```python
"""
gRPC server wrapper for the vision worker.
Serves PerceptionFrame messages on port 50051.
"""
from __future__ import annotations

import queue
import sys
from concurrent import futures
from pathlib import Path

import grpc
import structlog

# Add generated stubs to path so this module works whether run directly or
# imported from vision_worker.py (both set PYTHONPATH=backend).
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "gen" / "python"))
from perception.v1 import perception_pb2, perception_pb2_grpc

logger = structlog.get_logger()

GRPC_PORT = 50051


class PerceptionServicer(perception_pb2_grpc.PerceptionServiceServicer):
    """Implements the PerceptionService gRPC server."""

    def __init__(self) -> None:
        self._frame_queue: queue.Queue = queue.Queue(maxsize=10)

    def push_frame(self, frame: perception_pb2.PerceptionFrame) -> None:
        """Called by vision worker to push a new frame. Non-blocking — drops on full."""
        try:
            self._frame_queue.put_nowait(frame)
        except queue.Full:
            pass

    def StreamFrames(self, request, context):
        """Server-streaming RPC — yields PerceptionFrame to the Go client."""
        logger.info("vision gRPC client connected", session_id=request.session_id)
        try:
            while context.is_active():
                try:
                    frame = self._frame_queue.get(timeout=0.1)
                    yield frame
                except queue.Empty:
                    continue
        finally:
            logger.info("vision gRPC client disconnected")


def serve(servicer: PerceptionServicer) -> grpc.Server:
    """Start the gRPC server on GRPC_PORT. Returns the server instance."""
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=2),
        options=[
            ("grpc.max_send_message_length", 1024 * 1024),
            ("grpc.max_receive_message_length", 1024 * 1024),
        ],
    )
    perception_pb2_grpc.add_PerceptionServiceServicer_to_server(servicer, server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    server.start()
    logger.info("vision gRPC server started", port=GRPC_PORT)
    return server
```

### Step 2: Run the Python tests — expect GREEN

```bash
cd /Users/sucheetboppana/aria && \
  PYTHONPATH=backend \
  /Users/sucheetboppana/miniconda-arm64/bin/python3 \
  -m pytest backend/tests/test_vision_grpc_server.py -v 2>&1
```
Expected: all 3 tests **PASS**

---

## Task 11: Wire gRPC server into vision_worker.py

**Files:**
- Modify: `backend/app/pipeline/vision_worker.py`

### Step 1: Add `--grpc` arg and conditional gRPC startup

In `main()`, add:
```python
parser.add_argument("--grpc", action="store_true", default=False,
    help="Serve frames via gRPC instead of stdout JSON")
```

In `run_synthetic()` and `run_camera()`, accept `args` and check `args.grpc`. When `--grpc` is True:
1. Import and start the gRPC servicer + server in a background thread
2. After building the `state` dict, also build a `PerceptionFrame` proto and call `servicer.push_frame(frame)`
3. Keep the existing `print(json.dumps(state), flush=True)` as-is (stdout pipe still works when `--grpc` is False)

**Exact diff for `main()`** — add after the existing `parser.add_argument("--duration", ...)` line:
```python
    parser.add_argument("--grpc", action="store_true", default=False,
        help="Serve frames via gRPC instead of stdout JSON")
```

**Exact diff for `run_synthetic()`** — add at the top of the function (after the `fake_*` lines):
```python
    servicer = None
    if args.grpc:
        import threading
        import sys as _sys
        _sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent.parent / 'gen' / 'python'))
        from app.pipeline.vision_grpc_server import PerceptionServicer, serve
        from perception.v1 import perception_pb2
        servicer = PerceptionServicer()
        _grpc_server = serve(servicer)
        threading.Thread(target=lambda: _grpc_server.wait_for_termination(), daemon=True).start()
```

And inside the `while` loop, after `print(json.dumps(state), flush=True)`:
```python
        if servicer is not None:
            frame = perception_pb2.PerceptionFrame(
                timestamp_us=int(now * 1_000_000),
                session_id="local",
            )
            servicer.push_frame(frame)
```

Apply the same pattern to `run_camera()`.

### Step 2: Verify existing synthetic test still passes

```bash
cd /Users/sucheetboppana/aria && \
  PYTHONPATH=backend \
  /Users/sucheetboppana/miniconda-arm64/bin/python3 \
  -m pytest backend/tests/test_vision.py -v 2>&1 | tail -20
```
Expected: all tests **PASS** (stdout JSON path is unchanged when `--grpc` is False)

---

## Task 12: Full build and test verification

### Step 1: Go build

```bash
cd /Users/sucheetboppana/aria/backend && go build ./... 2>&1
```
Expected: **no output** (clean build)

### Step 2: Go vet

```bash
cd /Users/sucheetboppana/aria/backend && go vet ./... 2>&1
```
Expected: **no output**

### Step 3: Full Python test suite

```bash
cd /Users/sucheetboppana/aria && \
  PYTHONPATH=backend \
  /Users/sucheetboppana/miniconda-arm64/bin/python3 \
  -m pytest backend/tests/ -v 2>&1 | tail -30
```
Expected: all tests **PASS** (no failures, no errors)

---

## Task 13: Commit

### Step 1: Stage all new/modified files

```bash
cd /Users/sucheetboppana/aria && git add \
  proto/perception.proto \
  proto/buf.yaml \
  proto/buf.gen.yaml \
  backend/gen/ \
  backend/internal/vision/grpc_client.go \
  backend/internal/vision/grpc_client_test.go \
  backend/app/pipeline/vision_grpc_server.py \
  backend/app/pipeline/vision_worker.py \
  backend/tests/test_vision_grpc_server.py \
  backend/go.mod \
  backend/go.sum
```

### Step 2: Show status before committing

```bash
git status
```
Review the list — no unintended files staged.

### Step 3: Commit

```bash
git commit -m "feat(week1): gRPC transport layer — PerceptionService replaces stdout JSON pipe

- Add PerceptionService, PerceptionFrame, HandData, StreamRequest to perception.proto
- Generate Go stubs to backend/gen/go/perception/v1/
- Generate Python stubs to backend/gen/python/perception/v1/
- Add GRPCClient in backend/internal/vision/ (streams frames, converts to legacy JSON)
- Add PerceptionServicer + serve() in vision_grpc_server.py
- Wire --grpc flag into vision_worker.py (default False, stdout pipe unchanged)
- Worker subprocess manager (worker.go) untouched this sprint"
```

### Step 4: Push

```bash
git push origin integration
```

---

## Appendix: Troubleshooting

### buf remote plugins fail (BSR network unavailable)
Use the local protoc fallback in Task 4 Step 3. The `module=` flag produces identical output.

### `protoc-gen-go: program not found`
```bash
export PATH="$PATH:$(go env GOPATH)/bin"
```
Add this to `~/.zshrc` to make it permanent.

### Python import: `ModuleNotFoundError: No module named 'perception'`
Ensure `PYTHONPATH` includes `backend/gen/python` OR the `sys.path.insert` in `vision_grpc_server.py` resolves correctly based on `__file__`. The path logic uses `Path(__file__).parent.parent.parent / 'gen' / 'python'` which resolves to `aria/gen/python` — not `aria/backend/gen/python`. See Task 10 implementation where the path is corrected to use the actual repo structure.

### `grpc.NewClient` not found in older grpc versions
`grpc.NewClient` was added in gRPC-Go v1.63. The plan pins `v1.64.0`. If you see this error, run `go get google.golang.org/grpc@v1.64.0` again.
