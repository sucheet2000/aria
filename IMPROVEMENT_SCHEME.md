# ARIA Improvement Scheme

## Philosophy
- Schema-First: Protobuf enforced across Go, Python, Next.js
- Edge-Local: All inference runs on-device (M1 Pro)
- Sub-100ms interrupt latency is a hard constraint
- Each week builds on the previous — no skipping

## Week 0 — Data Contract (COMPLETE)
- proto/perception.proto: Point3D, HandGestureEvent, SpatialAnchor
- Handedness enum (UNSPECIFIED/LEFT/RIGHT)
- Tag budget reserved for Weeks 2, 3, 5, 9
- CognitionService gRPC interface defined

## Week 1 — gRPC Transport Layer
- Replace Python vision worker stdout JSON pipe with gRPC stream
- Go server implements PerceptionService client
- Python vision worker implements PerceptionService server
- buf.gen.yaml generates Go + Python stubs
- Goal: vision frames arrive via typed proto, not raw JSON

## Week 2 — Session State
*Details coming soon.*

## Week 3 — Bi-directional gRPC + Priority Interrupt
*Details coming soon.*

## Week 4 — ANE Acceleration
*Details coming soon.*

## Week 5 — NATS Async Transport
*Details coming soon.*

## Week 6 — LMCache Integration
*Details coming soon.*

## Week 7 — Shannon Memory Graph
*Details coming soon.*

## Week 8 — Gesture Classification
*Details coming soon.*

## Week 9 — Spatial Anchoring
*Details coming soon.*

## Week 10 — NATS Reliability + Anchor Lifecycle (COMPLETE)
- NATS subscriber reconnect path: DisconnectErrHandler + ReconnectHandler with embedded nats-server Go test
- Anchor registry: delete and update API endpoints
- Stale anchor pruning on session expiry

## Week 11 — Spatial Canvas
- Render spatial anchors as 3D objects in the Three.js frontend
- Each anchor maps to a low-poly mesh positioned at (x, y, z) from the anchor registry
- Object selection: ray-cast from pointer position, highlight on hover
- Basic manipulation: translate selected object via drag, persist new coords back to registry
- Goal: anchors are first-class 3D citizens, not just data records

## Week 12 — Multi-Display Broadcast
- Extend WebSocket hub to broadcast spatial state across multiple browser windows/tabs
- SharedWorker or BroadcastChannel for same-origin sync without a round-trip to Go server
- Conflict resolution: last-write-wins on anchor position, sequence-numbered on gesture events
- Goal: two monitors can show the same spatial canvas, updated in real time

## Week 13 — Two-Hand Physics
- BOND/THROW/EXPAND gesture events drive real 3D object physics in Three.js
- BOND: constrain two anchors with a spring joint
- THROW: apply velocity vector from pointing_vector to anchor rigid body
- EXPAND: scale the world-space unit by gesture factor, re-project all anchors
- Physics engine: cannon-es (lightweight, tree-shakeable, no WASM)
- Goal: hands are the physics controller, not just an event source

## Week 14 — Visual Event Pipeline
- TouchDesigner-style node graph for spatial event routing in the frontend
- Nodes: sources (gesture stream, anchor registry), transforms (filter, map, delay), sinks (3D canvas, TTS, memory)
- Edges are live WebSocket subscriptions; nodes hot-reload without page refresh
- Built with React Flow; node state persisted to localStorage
- Goal: non-code users can wire up spatial behaviours visually

## Week 15 — Spatial Persistence
- Anchors survive sessions: write anchor state to SQLite on every mutation
- On Go server startup: load anchors from SQLite, publish to NATS, hydrate frontend on first WebSocket connect
- Schema: anchor_id, label, x, y, z, session_id, created_at, updated_at
- Migrations managed with golang-migrate (same pattern as Week 2 session state)
- Goal: the spatial world persists across restarts — ARIA remembers where things are

## Security Architecture (Ongoing)

### Completed (Codex-found, fixed in v1.5.0–v1.6.0)
- gRPC services bound to 127.0.0.1 only (not 0.0.0.0)
- Session IDs: UUIDs end-to-end, no "default" wildcard
- Interrupt path: concrete session IDs only, rejected at gRPC ingress
- Pending cancel map: bounded at 32 entries, 10s TTL eviction
- vision_grpc_server.py: loopback only

### v3 Vision — Spatial Computing Environment
Weeks 10-15 complete ARIA's transformation from a voice companion into a
spatial computing environment. By Week 15, the system maintains a persistent
3D world model: anchors are physical objects with mass and velocity, hands
are physics controllers, and multiple displays share a live view of the same
scene. The visual event pipeline (Week 14) makes the spatial wiring
inspectable and reconfigurable without code changes. Persistence (Week 15)
means the environment survives restarts — ARIA's memory of space becomes as
durable as her episodic memory of conversation.

### v3 Security Requirements
- mTLS on gRPC services when ARIA exposes to local network
- WebSocket rate limiting: max N connections per IP
- Session token expiry: UUID sessions expire after 30 min idle
- Audit log: all cognition requests logged with session_id + timestamp
- Input validation: sanitize all WebSocket message payloads before routing
- SQLite anchor store: parameterized queries only, no string interpolation

### v4 Security Requirements (Agent Trust Boundaries)
- Segregation of duties enforced via gitagent DUTIES.md
- code-builder agent cannot approve its own work
- Agent-to-agent communication authenticated (not just localhost trust)
- API key rotation: ANTHROPIC_API_KEY rotated every 90 days
- No agent can write to SOUL.md without human approval (human-in-the-loop)

### Critical Design Constraint
Security findings from Codex adversarial review are P0 — fix before
merging any sprint. No security debt carried forward between versions.

## Critical Design Constraints
- Tags 1-15 in proto messages cost 1 byte on the wire
- Tags 16+ cost 2 bytes — never put hot-path fields here
- All timestamps as int64 microseconds (not Timestamp sub-message)
- All reserved blocks must have both number and name reservations
- Backward compatibility is non-negotiable after Week 1

## Tag Budget Reference
See proto/perception.proto for complete tag allocation table.
Reserved ranges document exactly which week activates which fields.
