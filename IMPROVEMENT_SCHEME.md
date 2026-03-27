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

## Week 2 — Session State (Redis Streams)
- Add Redis Streams for perception event ordering
- sequence_id enforcement across pod restarts
- session_id re-hydration for reconnecting clients
- ChromaDB memory queries keyed by session_id

## Week 3 — Bi-directional gRPC + Priority Interrupt
- StreamCognition RPC: perception events in, responses out
- interrupt_signal payload kills active cognitive stream in <100ms
- interrupt_priority and stream_id fields activated on HandGestureEvent
- Visual state change (user exits frame) triggers immediate interrupt

## Week 4 — ANE Acceleration (Apple Neural Engine)
- Whisper tiny → ANE-optimized CoreML model
- MediaPipe face/hand models converted to CoreML
- Target: STT latency < 300ms (currently 1-2s)
- Target: vision inference < 5ms per frame (currently ~16ms)

## Week 5 — NATS Async Transport
- High-frequency landmark streams migrated from gRPC to NATS
- DiscardOld consumer policy for backpressure
- nats_subject and backpressure_token fields activated
- gRPC retained for control plane (interrupts, session management)

## Week 6 — LMCache Integration
- KV cache sharing for Claude API calls
- Reduces latency when conversation history grows long
- Useful when scaling to multiple concurrent sessions

## Week 7 — Shannon Memory Graph
- Replace ChromaDB flat vectors with knowledge graph memory
- Entity extraction from conversations
- Relationship traversal for richer context retrieval

## Week 8 — Gesture Classification
- Train gesture classifier on top of MediaPipe landmarks
- gesture_class and gesture_confidence fields activated
- Initial gesture set: STOP, POINT, CONFIRM, CANCEL

## Week 9 — Spatial Anchoring
- pointing_vector derived from index finger landmarks
- RegisterAnchor RPC: persist 3D objects in world space
- spatial_anchor_id, depth_confidence, registration_state activated
- depth_mm TurboQuant compression on Point3D

## Critical Design Constraints
- Tags 1-15 in proto messages cost 1 byte on the wire
- Tags 16+ cost 2 bytes — never put hot-path fields here
- All timestamps as int64 microseconds (not Timestamp sub-message)
- All reserved blocks must have both number and name reservations
- Backward compatibility is non-negotiable after Week 1

## Tag Budget Reference
See proto/perception.proto for complete tag allocation table.
Reserved ranges document exactly which week activates which fields.
