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

## Security Architecture (Ongoing)

### Completed (Codex-found, fixed in v1.5.0–v1.6.0)
- gRPC services bound to 127.0.0.1 only (not 0.0.0.0)
- Session IDs: UUIDs end-to-end, no "default" wildcard
- Interrupt path: concrete session IDs only, rejected at gRPC ingress
- Pending cancel map: bounded at 32 entries, 10s TTL eviction
- vision_grpc_server.py: loopback only

### v3 Security Requirements
- mTLS on gRPC services when ARIA exposes to local network
- WebSocket rate limiting: max N connections per IP
- Session token expiry: UUID sessions expire after 30 min idle
- Audit log: all cognition requests logged with session_id + timestamp
- Input validation: sanitize all WebSocket message payloads before routing

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
