# Architecture Decisions

## ADR-001: Go for WebSocket server, Python for ML inference

Decision: Go manages all network I/O and subprocess orchestration.
Python handles all ML model inference.

Rationale: Go's goroutine model handles hundreds of concurrent WebSocket
connections with minimal overhead. Python has no viable alternative for
MediaPipe, faster-whisper, and torch-based ML libraries. Separating the
two via subprocess stdout IPC gives clean boundaries and independent
restartability.

## ADR-002: Subprocess stdout as IPC between Go and Python

Decision: Python workers print one JSON line per event to stdout.
Go reads stdout line by line and broadcasts to WebSocket clients.

Rationale: No message broker needed. No shared memory complexity.
Python crashes do not take down the Go server. Go can restart Python
automatically. The interface contract is a simple JSON schema.

## ADR-003: webrtcvad over Silero VAD

Decision: webrtcvad for voice activity detection instead of Silero VAD.

Rationale: Silero VAD requires torch, which caused dependency conflicts
with other packages on Apple Silicon. webrtcvad has no ML dependencies,
runs natively on ARM64, processes 30ms chunks in under 1ms, and has
sufficient accuracy for conversational VAD.

## ADR-004: Native ARM64 Python via miniconda

Decision: Use miniconda-arm64 for the Python runtime on Apple Silicon.

Rationale: The default Anaconda installation runs in Rosetta x86_64
emulation. This causes torch, OpenCV, and MediaPipe to pull x86 wheels
which conflict with each other on numpy version requirements. Native
ARM64 Python resolves all conflicts and provides significantly better
ML inference performance via Apple Neural Engine acceleration.

## ADR-005: MediaPipe Tasks API over Solutions API

Decision: Use mediapipe.tasks for FaceLandmarker and HandLandmarker
instead of mp.solutions.face_mesh and mp.solutions.hands.

Rationale: MediaPipe 0.10.21+ deprecated and removed the Solutions API.
The Tasks API provides the same functionality with a cleaner interface
and better performance on Apple Silicon via Metal GPU acceleration.
