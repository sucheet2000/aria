# ARIA Naming Audit

**Date:** 2026-04-05
**Scope:** All layers — Proto, Python backend, Go server, TypeScript frontend
**Method:** Graph search (code-review-graph MCP) + targeted file reads
**Purpose:** Identify naming inconsistencies for each core concept across layers

---

## Status: COMPLETE

Pass 1 complete across all 4 layers.
3 bugs fixed. 4 naming inconsistencies normalized.
All tests passing: 219 Python, 20 vitest, Go build clean.

| Layer | Commit |
|-------|--------|
| Proto | `bbea4ae` refactor(pass1/proto) |
| Python | `5c4584a` refactor(pass1/python) |
| Go | `ea3dba2` refactor(pass1/go) |
| TypeScript | `5ee8ec8` refactor(pass1/ts) |

---

## CONCEPT 1 — The gesture from a single hand

**STATUS: RESOLVED** — Canonical name: `HandGesture` (Python class), `HAND_GESTURE_*` constants, `HandGestureType` enum (proto). Fixed in `5c4584a` (Python) + `bbea4ae` (proto).

| Layer | File | Name used |
|-------|------|-----------|
| Proto | `proto/perception.proto` | `GestureType` (enum); `gesture` field on `HandGestureEvent` (type: `GestureType`) |
| Python backend | `app/pipeline/gesture_classifier.py` | `GestureResult` (NamedTuple); `gesture_type: int` (field) |
| Python backend | `app/pipeline/vision_worker.py` | `gesture_name: str` (local var; string: `"point"`, `"stop"`, `"none"`, etc.) |
| Python backend | `app/models/schemas.py` | `gesture_name: str` (field in `GestureState`); `gesture: str` (field in `CognitionRequest`) |
| Python backend | `app/api/cognition_route.py` | `req.gesture` (str, e.g. `"point"`) |
| Python backend | `app/spatial/gesture_anchor_bridge.py` | `gesture: str` (parameter name) |
| Go server | `internal/cognition/grpc_server.go` | `"gesture_event"` (WebSocket broadcast type); `GestureEvent` (proto accessor `CognitionRequest_GestureEvent`) |
| Go server | `internal/cognition/handler.go` | — (not referenced) |
| Go server | `internal/server/hub.go` | — (not referenced directly) |
| TypeScript | `store/ariaStore.ts` | — (no explicit single-gesture field exposed) |
| TypeScript | `hooks/useCognition.ts` | — (consumed indirectly via `spatial_event`; not passed by frontend) |
| TypeScript | `hooks/useWebSocket.ts` | — (receives `"gesture_event"` WS message but no TS type defined) |
| TypeScript | `spatial/useWorldModel.ts` | — (not stored; gesture type strings feed `activeGesture` indirectly) |

### What was fixed
- `GestureResult` → `HandGesture` (NamedTuple)
- `GESTURE_TYPE_*` constants → `HAND_GESTURE_*` (matching proto `HandGestureType` values)
- `CognitionRequest.gesture` → `CognitionRequest.hand_gesture`
- Added `HandGestureType` and `TwoHandGestureType` enums to proto
- `TwoHandGesture.gesture_type` → `TwoHandGesture.hand_gesture_type`

---

## CONCEPT 2 — The gesture from two hands

**STATUS: RESOLVED** — Canonical name: `TwoHandGesture` (Python dataclass), `TWO_HAND_*` string constants, `TwoHandGestureType` enum (proto). Fixed in `5c4584a` (Python) + `bbea4ae` (proto).

| Layer | File | Name used |
|-------|------|-----------|
| Proto | `proto/perception.proto` | — (not modelled; absent from proto) |
| Python backend | `app/pipeline/gesture_classifier.py` | `TwoHandGesture` (dataclass); `gesture_type: str` (field: `"HOLD"`, `"EXPAND"`, `"THROW"`, `"BOND"`, `"NONE"`) |
| Python backend | `app/models/schemas.py` | `two_hand_gesture: str` (field in `CognitionRequest`) |
| Python backend | `app/api/cognition_route.py` | `req.two_hand_gesture` (str) |
| Python backend | `app/spatial/gesture_anchor_bridge.py` | `two_hand_gesture: str` (parameter) |
| Go server | `internal/server/hub.go` | — |
| Go server | `internal/cognition/handler.go` | — (not modelled in Go's `CognitionRequest`) |
| TypeScript | `store/ariaStore.ts` | — (not stored explicitly) |
| TypeScript | `hooks/useCognition.ts` | — (not forwarded from browser to backend) |
| TypeScript | `hooks/useWebSocket.ts` | — |
| TypeScript | `spatial/useWorldModel.ts` | `activeGesture: string \| null` (stores the resolved gesture string, e.g. `"BOND"`, `"EXPAND"`) |

### What was fixed
- Added `TwoHandGestureType` enum to proto (`bbea4ae`)
- `TwoHandGesture.gesture_type` → `TwoHandGesture.hand_gesture_type` (`5c4584a`)

---

## CONCEPT 3 — A spatial anchor

**STATUS: RESOLVED** — Canonical name: `SpatialAnchor` with field `anchor_id`. Fixed in `5ee8ec8` (TypeScript).

| Layer | File | Name used |
|-------|------|-----------|
| Proto | `proto/perception.proto` | `SpatialAnchor` (message); `anchor_id` (field); `spatial_anchor_id` (field on `HandGestureEvent` tag 13) |
| Python backend | `app/spatial/anchor_registry.py` | `SpatialAnchor` (dataclass); `anchor_id: str` (field) |
| Python backend | `app/spatial/gesture_anchor_bridge.py` | `anchor_id` (local var); dict key `"anchor_id"` in returned payload |
| Python backend | `app/api/cognition_route.py` | `spatial_event` dict (no typed class); key `"anchor_id"` forwarded from bridge |
| Python backend | `app/models/schemas.py` | — (not modelled) |
| Go server | `internal/server/hub.go` | — |
| Go server | `internal/cognition/grpc_server.go` | `SpatialAnchor` (proto type in `RegisterAnchor` stub) |
| Go server | `internal/cognition/handler.go` | — (not modelled in Go cognition types) |
| TypeScript | `store/ariaStore.ts` | — (not stored in ariaStore) |
| TypeScript | `hooks/useCognition.ts` | `SpatialAnchor` (imported from `useWorldModel`); `event.anchor_id` (read from spatial_event dict) |
| TypeScript | `hooks/useWebSocket.ts` | — (dispatches `"aria:anchor_registered"` CustomEvent; no typed struct) |
| TypeScript | `spatial/useWorldModel.ts` | `SpatialAnchor` (interface); identifier field is **`id: string`** |

### What was fixed
- `SpatialAnchor.id` → `SpatialAnchor.anchor_id` across all TS files (`5ee8ec8`)
- `handleSpatialEvent` now reads `event.anchor_id` directly (was `event.anchor` object cast)
- `AnchorMarker`, `SpatialCanvas`, `SpatialWindow` all updated to use `anchor.anchor_id`
- All Map key lookups updated to use `anchor.anchor_id`

---

## CONCEPT 4 — Vision state from the camera

**STATUS: RESOLVED** — Canonical name: `PerceptionFrame` (aligned with proto). Fixed in `5c4584a` (Python), `ea3dba2` (Go), `5ee8ec8` (TypeScript).

| Layer | File | Name used |
|-------|------|-----------|
| Proto | `proto/perception.proto` | `PerceptionFrame` (message for raw per-frame data from vision worker) |
| Python backend | `app/pipeline/vision.py` | `VisionState` (return type of `process_frame`) |
| Python backend | `app/models/schemas.py` | `VisionState` (full raw model with landmarks); `VisionContext` (trimmed model for cognition input) |
| Python backend | `app/api/cognition_route.py` | `vision_state: VisionContext` (field in `CognitionRequest`); local var `vision: VisionContext` |
| Python backend | `app/pipeline/vision_worker.py` | broadcasts as `"vision_state"` JSON type; local var `_perception_frame` (for proto object) |
| Go server | `internal/vision/grpc_client.go` | `"vision_state"` (WebSocket message type in `broadcastFrame`) |
| Go server | `internal/nats/subscriber.go` | `"vision_state"` (WebSocket message type) |
| Go server | `internal/cognition/handler.go` | `VisionStateInput` (Go struct); `VisionState` field on `CognitionRequest` |
| Go server | `internal/cognition/prompt.go` | `VisionStateContext` (Go struct) |
| TypeScript | `store/ariaStore.ts` | `VisionFrame` (interface for WS payload); `setVisionFrame()` action |
| TypeScript | `hooks/useCognition.ts` | `vision_state` (JSON field key sent to backend API) |
| TypeScript | `hooks/useWebSocket.ts` | `"vision_state"` (WS message type match string) |
| TypeScript | `spatial/useWorldModel.ts` | — |

### What was fixed
- `VisionContext` → `PerceptionFrame` (Python models/schemas, llm.py, prompt.py) (`5c4584a`)
- `VisionStateInput` + `VisionStateContext` merged → single `PerceptionFrame` struct (Go handler.go + prompt.go) (`ea3dba2`)
- `BuildSystemPrompt(visionState VisionStateContext)` → `BuildSystemPrompt(frame PerceptionFrame)` (`ea3dba2`)
- `VisionFrame` → `PerceptionFrame` (TypeScript ariaStore.ts) (`5ee8ec8`)

---

## CONCEPT 5 — The session identifier

**STATUS: RESOLVED** — Canonical name: `session_id` (wire/Python/Go), `sessionId` (TypeScript camelCase), `MsgTypeSessionInit` constant (Go). Fixed in `ea3dba2` (Go).

| Layer | File | Name used |
|-------|------|-----------|
| Proto | `proto/perception.proto` | `session_id` (string field on `HandGestureEvent`, `CognitionRequest`, `CognitionResponse`, `PerceptionFrame`, `StreamRequest`) |
| Python backend | `app/models/schemas.py` | `session_id: str` (field in `CognitionRequest`) |
| Python backend | `app/api/cognition_route.py` | `req.session_id` |
| Python backend | `app/spatial/gesture_anchor_bridge.py` | `session_id: str` (parameter) |
| Go server | `internal/server/hub.go` | `SessionID string` (JSON struct tag: `"session_id"`); message type `"session_init"` |
| Go server | `internal/cognition/handler.go` | `SessionID string` (Go field; JSON tag: `"session_id"`) |
| Go server | `internal/cognition/grpc_server.go` | `req.SessionId` (proto accessor, Go camelCase) |
| Go server | `internal/cognition/stream_registry.go` | `session_id` (comment/doc string) |
| TypeScript | `store/ariaStore.ts` | `sessionId: string` (camelCase; initialised via `crypto.randomUUID()`) |
| TypeScript | `hooks/useCognition.ts` | `session_id: useAriaStore.getState().sessionId` (serialised to snake_case in JSON body) |
| TypeScript | `hooks/useWebSocket.ts` | `sessionId` (local var camelCase); sent as `session_id` in JSON; received as `msg.session_id` |
| TypeScript | `spatial/useWorldModel.ts` | — |

### What was fixed
- Hardcoded `"session_init"` in `hub.go` → `MsgTypeSessionInit` constant (`ea3dba2`)
- `MsgTypeSessionInit` added to `server/messages.go` (`ea3dba2`)

---

## CONCEPT 6 — The cognition response

**STATUS: RESOLVED** — Canonical name: `CognitionResponse` (all layers). Fixed in `5c4584a` (Python), `5ee8ec8` (TypeScript).

| Layer | File | Name used |
|-------|------|-----------|
| Proto | `proto/perception.proto` | `CognitionRequest` (message); `CognitionResponse` (message) |
| Python backend | `app/models/schemas.py` | `CognitionRequest` (Pydantic model); `SymbolicResponse` (response model — **not** `CognitionResponse`) |
| Python backend | `app/api/cognition_route.py` | `CognitionRequest` (request); `result: SymbolicResponse` (internal); returns anonymous `dict` (no typed response class) |
| Go server | `internal/cognition/handler.go` | `CognitionRequest` (Go struct); `CognitionResponse` (Go struct) |
| TypeScript | `hooks/useCognition.ts` | `CognitionResponse` (local interface, inline defined) |
| TypeScript | `store/ariaStore.ts` | — (fields from response stored individually, no response wrapper) |
| TypeScript | `hooks/useWebSocket.ts` | — |
| TypeScript | `spatial/useWorldModel.ts` | — |

### What was fixed
- `SymbolicResponse` → `CognitionResponse` (Python models/schemas, llm.py) (`5c4584a`)
- `CognitionResponse` interface in TypeScript fully typed with `symbolic_inference`, `world_model_update`, `episodic_memory`, `spatial_event: SpatialEvent | null` (`5ee8ec8`)

---

## CONCEPT 7 — The spatial event

**STATUS: RESOLVED** — Canonical name: `SpatialEvent` (typed dataclass/struct/interface on all layers). Fixed across all 4 commits.

| Layer | File | Name used |
|-------|------|-----------|
| Proto | `proto/perception.proto` | — (not modelled) |
| Python backend | `app/spatial/gesture_anchor_bridge.py` | returns `dict \| None` (no typed class); dict key `"type"` is `"anchor_registered"`, `"anchors_bonded"`, `"anchor_thrown"`, `"world_expand"` |
| Python backend | `app/api/cognition_route.py` | `spatial_event: dict \| None` (local variable); returned under JSON key `"spatial_event"` |
| Python backend | `app/models/schemas.py` | — (not modelled; no `SpatialEvent` class) |
| Go server | `internal/server/hub.go` | — |
| Go server | `internal/cognition/grpc_server.go` | — |
| Go server | `internal/cognition/handler.go` | — (not forwarded by Go handler) |
| TypeScript | `hooks/useCognition.ts` | `spatial_event?: Record<string, unknown>` (field in `CognitionResponse`); `handleSpatialEvent()` (function) |
| TypeScript | `hooks/useWebSocket.ts` | `"aria_anchor_registered"` (WS message type); dispatches `"aria:anchor_registered"` CustomEvent |
| TypeScript | `spatial/useWorldModel.ts` | — (reacts to resolved gesture strings via `setActiveGesture`; no spatial event struct) |

### What was fixed
- Added `SpatialEvent` proto message (`bbea4ae`)
- Added `SpatialEvent` Python dataclass in `app/models/schemas.py` (`5c4584a`)
- `gesture_anchor_bridge.py` now returns `SpatialEvent | None` (was `dict | None`) (`5c4584a`)
- Added `SpatialEvent` Go struct in `server/messages.go` + `MsgTypeAnchorRegistered`, `MsgTypeAnchorsBonded`, `MsgTypeAnchorThrown`, `MsgTypeWorldExpand` constants (`ea3dba2`)
- Added `SpatialEvent` TypeScript interface in `useCognition.ts`; `handleSpatialEvent` now accepts `SpatialEvent | null` (`5ee8ec8`)
- **Bug #2 fixed:** `"aria_anchor_registered"` → `"anchor_registered"` in `useWebSocket.ts` (`5ee8ec8`)
- `msgTypeAriaInterrupt`, `msgTypeGestureEvent`, `msgTypeTextInput` local constants added to `grpc_server.go` replacing hardcoded strings (`ea3dba2`)

---

## Summary of Cross-Cutting Issues

| Issue | Status |
|-------|--------|
| `anchor_id` (Python/proto) vs `id` (TypeScript) | FIXED `5ee8ec8` |
| Four names for one concept (vision state) | FIXED `5c4584a` `ea3dba2` `5ee8ec8` |
| `SymbolicResponse` (Python) vs `CognitionResponse` (proto/Go/TS) | FIXED `5c4584a` |
| `gesture_type: int` vs `gesture_name: str` vs `gesture: str` | FIXED `5c4584a` |
| `gesture_type: str` (two-hand) shadows `gesture_type: int` (single-hand) | FIXED `5c4584a` |
| Two-hand gesture absent from proto and Go | FIXED `bbea4ae` (proto enum added) |
| Spatial event untyped (`dict` / `Record<string, unknown>`) | FIXED all 4 commits |
| Two WS event names for same anchor event (`aria_anchor_registered` vs `anchor_registered`) | FIXED `5ee8ec8` |
| `session_init` (WS type) vs `session_id` (all other references) | FIXED `ea3dba2` |
