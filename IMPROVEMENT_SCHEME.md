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

## Critical Design Constraints
- Tags 1-15 in proto messages cost 1 byte on the wire
- Tags 16+ cost 2 bytes — never put hot-path fields here
- All timestamps as int64 microseconds (not Timestamp sub-message)
- All reserved blocks must have both number and name reservations
- Backward compatibility is non-negotiable after Week 1

## Tag Budget Reference
See proto/perception.proto for complete tag allocation table.
Reserved ranges document exactly which week activates which fields.
