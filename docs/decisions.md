# Architecture Decisions

These are the decisions that shape ARIA today. Superseded decisions from the server-side
perception era are listed at the end for context.

## ADR-001: Go at the edge, Python for ML, TypeScript in the browser

**Decision:** Go owns network I/O, auth, and rate-limiting. Python owns all server-side ML
(speech-to-text, Claude cognition, memory, TTS). The browser owns capture and vision
inference.

**Rationale:** Go's goroutine model handles many concurrent WebSocket connections cheaply and
makes a clean single auth boundary. Python has the mature ML ecosystem (faster-whisper, the
Anthropic SDK, ChromaDB). Keeping the layers separate lets each be replaced or restarted
independently.

## ADR-002: Perception runs in the browser

**Decision:** Camera and microphone capture, plus MediaPipe face/hand tracking and the
emotion/gesture/head-pose math, run in each user's browser. Only the derived `vision_state`
and the mic audio are sent to the server.

**Rationale:** A cloud container has no physical camera or microphone, and a single server
device could only ever serve one user. Moving capture browser-side makes ARIA cloud-viable
and genuinely multi-user in one step, and it improves privacy: raw video never leaves the
user's machine. The browser fills the exact `vision_state` fields the cognition route already
consumed, so the server contract barely changed.

## ADR-003: Speech-to-text stays on the server, fed by streamed browser audio

**Decision:** The browser captures the microphone and streams PCM audio to a server
`/ws/audio` WebSocket. faster-whisper, VAD, and the wake-word / sleep-phrase state machine
stay server-side.

**Rationale:** There is no browser-quality equivalent of faster-whisper, and STT is
CPU-heavy. So capture moves to the browser (consistent with ADR-002) but transcription stays
where the model lives. This is the one signal, besides text, that must reach the server.

## ADR-004: webrtcvad for voice activity detection

**Decision:** Use webrtcvad rather than a torch-based VAD.

**Rationale:** webrtcvad has no heavy ML dependency, runs natively on ARM64, and processes a
30 ms chunk in well under a millisecond — more than enough for conversational turn-taking,
without pulling torch into the dependency graph.

## ADR-005: MediaPipe Tasks API

**Decision:** Use the MediaPipe Tasks API (`@mediapipe/tasks-vision` in the browser) for the
Face and Hand landmarkers.

**Rationale:** The older Solutions API was deprecated and removed. The Tasks API is the
supported path and runs efficiently in the browser via WASM/WebGPU.

## ADR-006: Claude for cognition, with SOUL.md as the identity prefix

**Decision:** Each cognition turn calls Claude with a prompt whose stable prefix is ARIA's
identity from `SOUL.md`, followed by the user message, current vision state, and memory.

**Rationale:** A stable prefix keeps the persona consistent and is cache-friendly. Claude
returns a structured object (`symbolic_inference`, `world_model_update`,
`natural_language_response`) so the reasoning, the memory write, and the spoken reply are
cleanly separable.

## ADR-007: Three-tier memory in ChromaDB

**Decision:** Keep profile, episodic, and working memory in ChromaDB; persist spatial anchors
in SQLite.

**Rationale:** Vector retrieval over episodic and profile collections gives ARIA long-term
recall of who the user is, while working memory keeps within-session continuity. Spatial
anchors are small, relational, and queried by key, so SQLite fits them better than a vector
store.

## ADR-008: Clerk auth with the Go server as the only trust boundary

**Decision:** Authenticate users with Clerk. The Go server verifies the token; the Python
service is never public and trusts the owner identity Go passes, backed by a shared
`INTERNAL_AUTH_SECRET`.

**Rationale:** A single public process with one auth check is easier to reason about and
harden than exposing both services. The shared secret is defense-in-depth if `:8000` is ever
accidentally exposed.

## ADR-009: Railway (backend) + Vercel (frontend)

**Decision:** Deploy the Go + Python backend as one Docker image on Railway and the Next.js
frontend on Vercel.

**Rationale:** One container keeps the Go↔Python localhost proxy simple and cheap. Vercel is
the natural home for the Next.js app. See [`DEPLOY.md`](DEPLOY.md) for the runbook and the
"Python is never public" invariant.

---

## Superseded decisions (server-side perception era)

These held while perception ran on the server; they were retired by ADR-002/003. The full
plans are in [`archive/`](archive/).

- **Subprocess stdout as vision IPC** — the Python vision worker printed JSON frames to
  stdout for Go to broadcast. Retired: there is no server-side camera worker anymore.
- **gRPC `PerceptionService` transport** — a typed gRPC stream between Go and a Python vision
  worker. Built but never carried production traffic; retired with server-side perception.
- **NATS event bus** — an async `aria.perception.frames` transport. Also retired; it was
  wired to no live consumer.
- **CoreML / Apple Neural Engine acceleration** — a macOS-only optimization for the
  server-side MediaPipe models. Not part of the browser-perception or cloud story.
</content>
