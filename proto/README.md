# ARIA Protobuf Contract

This directory holds the protobuf source of truth for the typed data structures shared across
ARIA's Go and Python layers, plus the [buf](https://buf.build) codegen config.

## What is live here

The **message types** (`Point3D`, `PerceptionFrame`, `HandGestureEvent`, `SpatialAnchor`, and
the related enums) are generated into Go and Python and are imported by the backend. Keeping
them in one contract means the same concept has the same shape on both sides.

> **Note on the gRPC services.** ARIA originally streamed perception frames over a gRPC
> `PerceptionService` between Go and a server-side Python vision worker. That transport has
> been retired now that perception runs in the browser (see
> [`../docs/plans/2026-07-11-a2-browser-perception-design.md`](../docs/plans/2026-07-11-a2-browser-perception-design.md)).
> The `.proto` message definitions remain the shared contract; the gRPC *service* stubs are
> dormant and slated to be scoped out in a later pass. Do not build new features on them.

## Layout

```
proto/
├── perception/v1/perception.proto   the contract
├── buf.yaml                         buf module config
└── buf.gen.yaml                     codegen targets (Go + Python)
```

## Compilation

A single command regenerates both language stubs:

```bash
# Install buf: https://buf.build/docs/installation
cd proto && buf generate
```

Output:

- `backend/gen/go/perception/v1/` — Go package for the message types.
- `backend/gen/python/perception/v1/` — self-contained Python package, imported as
  `from perception.v1 import ...`.

## Editing the contract

- Never renumber or reuse an existing field tag — that breaks wire compatibility.
- Add new fields with new tags.
- Regenerate the stubs (`buf generate`) and rebuild both backends after any change.
</content>
