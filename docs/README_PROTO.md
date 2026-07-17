# ARIA Nervous System: Protocol Buffers

This directory contains the source of truth for all data exchanged between ARIA's Go, Python, and frontend services.

## Why Protobuf?
For a production-grade neurosymbolic system, JSON is a liability:
1.  **Type Safety:** We can't afford "undefined" 3D landmarks or missing `session_id`s in a real-time loop.
2.  **Performance:** Binary serialization is 5-10x faster and significantly smaller than JSON, critical for 15fps vision streams.
3.  **The Contract:** Protobuf enforces a strict contract. If the vision worker's schema doesn't match the cognition engine's, the system won't even compile, preventing runtime disasters.
4.  **gRPC Streaming:** Enables the bi-directional communication required for sub-100ms interrupts.

## Compilation
The contract lives at `proto/perception/v1/perception.proto`. A single command
generates code for both Go and Python:

```bash
# Install buf (see https://buf.build/docs/installation)
cd proto && buf generate
```

This will output:
- `backend/gen/go/perception/v1/`: Go package for the server and gRPC services.
- `backend/gen/python/perception/v1/`: self-contained nested Python package for
  the perception and cognition workers (imported as `from perception.v1 import ...`).

## Usage in ARIA
1.  **System 1 (Vision/Audio):** Use the generated Python classes to serialize MediaPipe landmarks and Whisper transcriptions.
2.  **System 2 (Cognition):** Use the gRPC service to receive these streams and send structured responses back to the Go server.
3.  **Interrupts:** Fire a `CognitionRequest` with `interrupt_signal: true` to immediately halt an LLM stream.
