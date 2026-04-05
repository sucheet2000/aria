<div align="center">

# ARIA

**Adaptive Realtime Intelligence Avatar — v2.0.0**

[![Go](https://img.shields.io/badge/Go-1.21+-00ADD8?style=flat-square&logo=go&logoColor=white)](https://golang.org)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![Tests](https://img.shields.io/badge/Tests-160%20Python%20%7C%2020%2B%20Go-brightgreen?style=flat-square)](#testing)
[![Platform](https://img.shields.io/badge/Platform-Apple%20Silicon-555555?style=flat-square&logo=apple&logoColor=white)](https://apple.com/mac)
[![License](https://img.shields.io/badge/License-Private-red?style=flat-square)](#)

A real-time multimodal AI companion. Sees you through your camera, hears you through your microphone, reasons about your emotional and cognitive state using a neurosymbolic architecture, and maintains a persistent world model of who you are across sessions — entirely on-device.

</div>

---

## Architecture

ARIA is a three-language stack with clean subprocess and gRPC boundaries.

```
  Browser (Next.js :3000)
       |
       | WebSocket  ws://localhost:8080/ws
       | HTTP POST  /api/cognition
       | HTTP POST  /api/tts
       |
  Go Server (:8080)
       |-- gRPC stream --> Python Vision Worker (:50051)
       |                    MediaPipe Tasks FaceLandmarker (478 points)
       |                    Emotion classifier (7 classes, landmark geometry)
       |                    Head pose via solvePnP (pitch / yaw / roll)
       |                    Hand gesture classification (thumb_up, open_palm, pinch, point)
       |                    CoreML acceleration (2.9x speedup on Apple Neural Engine)
       |                    Typed proto frames via PerceptionService
       |
       |-- subprocess --> Python Audio Worker
       |                    sounddevice microphone capture at 16 kHz
       |                    webrtcvad voice activity detection
       |                    DeepFilterNet noise isolation (--denoise flag)
       |                    faster-whisper speech-to-text (CoreML backend)
       |                    JSON to stdout on utterance end
       |
       |-- NATS --> Internal event bus
       |                    Decoupled vision / audio / cognition events
       |                    Reconnect backoff (prevents storm on disconnect)
       |
       |-- HTTP proxy --> Python FastAPI (:8000)
                            Neurosymbolic prompt builder
                            Conflict detection (speech vs visual sentiment)
                            Claude Haiku / Sonnet tiered routing + prompt caching
                            ChromaDB episodic memory + NetworkX graph memory
                            SQLite spatial anchor registry
```

**Design decisions:**

| ADR | Decision | Rationale |
|-----|----------|-----------|
| 001 | Go for WebSocket, Python for ML | Goroutines handle concurrent connections; Python owns the ML ecosystem |
| 002 | gRPC replacing stdout IPC for vision | Typed proto contract; bidirectional streaming; priority interrupt support |
| 003 | webrtcvad over Silero VAD | No torch dependency; native ARM64; sub-1ms per 30ms chunk |
| 004 | Native ARM64 Python via miniconda | Avoids Rosetta conflicts; unlocks Apple Neural Engine for ML inference |
| 005 | MediaPipe Tasks API | Solutions API deprecated in 0.10.21+; Tasks API has Metal GPU acceleration |
| 006 | NATS for async transport | Decoupled event bus; eliminates Go channel fan-out complexity |
| 007 | Claude Haiku / Sonnet tiered routing | Cost-sensitive fast path (Haiku) with Sonnet escalation for complex turns |
| 008 | NetworkX graph memory alongside ChromaDB | Relational traversal for memory anchoring not achievable in vector similarity |

---

## Pipeline Timeline

### Vision pipeline (gRPC, continuous)

```
Webcam frame
  → MediaPipe FaceLandmarker       — 478 normalized landmarks (x, y, z)
  → Emotion classifier             — 7 classes, 5-frame smoothing
  → Head pose (solvePnP)           — pitch / yaw / roll in degrees
  → Gesture classifier             — thumb_up, open_palm, pinch, point
  → CoreML inference backend       — 2.9x speedup via Apple Neural Engine
  → PerceptionService gRPC frame   — typed proto, streamed to Go server
  → Go broadcasts to WebSocket clients
  → Browser updates landmark overlay + emotion + gesture display
```

### Audio pipeline (per utterance)

```
Microphone (16 kHz)
  → DeepFilterNet (optional)       — noise isolation
  → webrtcvad (30ms chunks)        — voice activity boundary detection
  → faster-whisper (CoreML)        — speech-to-text transcription
  → JSON to stdout
  → Go reads stdout → NATS publish
  → Broadcast transcript over WebSocket
  → Browser auto-sends to /api/cognition
  → FastAPI builds neurosymbolic prompt
  → Claude Haiku (fast path) or Sonnet (escalated) responds
  → Browser calls /api/tts
  → ElevenLabs streams audio → browser plays
```

### Neurosymbolic cognition loop

```
Each cognition turn:
  ┌─ Current perceptual state      — emotion, head pose, hands, gesture, face_detected
  ├─ Go working memory (circular)  — last 10 symbolic inferences, keyed by session UUID
  ├─ ChromaDB retrieval            — relevant long-term profile + episodic facts
  └─ NetworkX graph traversal      — relational memory anchors
        ↓
  FastAPI assembles structured prompt (with prompt caching)
        ↓
  Haiku / Sonnet tiered routing:
    {
      "symbolic_inference": "...",
      "world_model_update": { "triple": {…}, "confidence": 0.85 },
      "natural_language_response": "..."
    }
        ↓
  Triple written back to ChromaDB + NetworkX — persistent world model updated
  Spatial anchors persisted to SQLite
```

**Conflict detection:** if `|speech_sentiment − visual_sentiment| > 0.4`, ARIA responds to the observable affect via open invitation rather than validating the stated emotion.

**Priority interrupt:** `FaceExitDetector → gRPC → StreamRegistry.CancelActive(session_id)` — concrete session IDs only, rejected at gRPC ingress if no matching session.

---

## Version History

<details>
<summary><strong>v1.0.0</strong> — Voice companion (baseline)</summary>

- Go WebSocket server, Python vision + audio workers
- MediaPipe FaceLandmarker, emotion classifier (7 classes), head pose
- faster-whisper STT, webrtcvad VAD, ElevenLabs TTS
- Claude Haiku cognition, ChromaDB layered memory
- Wake word: "Hey ARIA" — sleep: "That would be all"
- Next.js 14 frontend with 3D avatar placeholder

</details>

<details>
<summary><strong>v1.1.0</strong> — gRPC transport layer</summary>

- Replaced stdout JSON IPC with typed gRPC stream (PerceptionService on :50051)
- `buf.gen.yaml` generates Go + Python stubs from `proto/perception.proto`
- `perception.proto`: Point3D, HandGestureEvent, SpatialAnchor, Handedness enum
- Go server implements PerceptionService client; Python vision worker implements server
- Proto tag budget reserved for all future weeks

</details>

<details>
<summary><strong>v1.2.0</strong> — Bidirectional gRPC + priority interrupt</summary>

- Bidirectional gRPC streaming between Go and Python vision worker
- Priority interrupt path: FaceExitDetector → gRPC → StreamRegistry.CancelActive()
- CognitionService gRPC interface defined
- Interrupt scoped to concrete session UUIDs — no wildcard cancellation

</details>

<details>
<summary><strong>v1.3.0</strong> — CoreML / ANE acceleration (2.9x)</summary>

- CoreML inference backend for MediaPipe gesture and emotion models
- Apple Neural Engine acceleration: 2.9x throughput on M1 Pro vs CPU baseline
- Accuracy benchmarked before enabling — CoreML fallback safety guard retained
- faster-whisper CoreML backend enabled for STT

</details>

<details>
<summary><strong>v1.4.0</strong> — Codex hardening sprint</summary>

- Codex adversarial review integrated into sprint workflow
- All P0 findings fixed before merge
- Session ID UUIDs enforced end-to-end; "default" wildcard removed
- Pending cancel map bounded at 32 entries with 10s TTL eviction

</details>

<details>
<summary><strong>v1.5.0</strong> — Security review (Codex-found fixes)</summary>

- gRPC services rebound to 127.0.0.1 (were 0.0.0.0)
- vision_grpc_server.py: loopback-only bind enforced
- session_init sent on WebSocket open — no anonymous sessions
- Worker replay attack surface closed
- 12 Codex security findings resolved (see Security section)

</details>

<details>
<summary><strong>v1.6.0</strong> — Session isolation</summary>

- Full session UUID isolation across WebSocket hub, gRPC, and cognition
- StreamRegistry enforces concrete session IDs at gRPC ingress
- CancelActive() only cancels the caller's own session
- Working memory keyed per session UUID

</details>

<details>
<summary><strong>v1.7.0</strong> — NATS async transport</summary>

- NATS replaces Go channel fan-out for vision / audio / cognition events
- Reconnect backoff implemented in subscriber — prevents reconnect storm
- All internal event buses decoupled via NATS subjects
- NATS subscriber DisconnectErrHandler + ReconnectHandler wired

</details>

<details>
<summary><strong>v1.8.0</strong> — LMCache + tiered Claude routing</summary>

- Prompt caching enabled for neurosymbolic system prompt (stable prefix)
- Claude Haiku / Sonnet tiered routing: Haiku for fast path, Sonnet for escalated turns
- LMCache KV-cache reuse reduces cognition latency on repeated context
- Cost per cognition turn reduced significantly on cached sessions

</details>

<details>
<summary><strong>v1.9.0</strong> — Shannon memory graph</summary>

- NetworkX graph memory alongside ChromaDB for relational traversal
- `graph_memory.py`: node insertion, edge linking, traversal for anchor resolution
- Episodic memory anchored to graph nodes for contextual retrieval
- ChromaDB + NetworkX queried in parallel per cognition turn

</details>

<details>
<summary><strong>v2.0.0-beta</strong> — Gesture classification</summary>

- Gesture classifier: thumb_up, open_palm, pinch, point (21-point hand landmark geometry)
- Magic constant documented: thumb_up classifier uses landmark distance threshold = 0.4
- Gesture events streamed via PerceptionService proto (HandGestureEvent)
- Gesture state included in cognition context

</details>

<details>
<summary><strong>v2.0.0</strong> — Spatial anchoring</summary>

- SQLite spatial anchor registry: anchors persisted by session + world position
- SpatialAnchor proto message activated (Week 9 reserved tags)
- Anchor creation via hand gesture + gaze direction
- Anchor retrieval included in cognition context for object reference resolution

</details>

---

## Quick Start

### Prerequisites

- macOS Apple Silicon (M1/M2/M3) or Linux
- Go 1.21+
- Node.js 20+
- Anthropic API key
- ElevenLabs API key (optional — falls back to browser TTS)

### 1. Clone

```bash
git clone https://github.com/sucheet2000/aria.git
cd aria
cp backend/.env.example backend/.env
# Add your ANTHROPIC_API_KEY to backend/.env
```

### 2. Python environment (Apple Silicon)

```bash
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh
bash Miniconda3-latest-MacOSX-arm64.sh -b -p ~/miniconda-arm64
source ~/miniconda-arm64/bin/activate

pip install mediapipe opencv-python torch faster-whisper webrtcvad \
            sounddevice structlog pydantic pydantic-settings \
            anthropic fastapi uvicorn chromadb deepfilternet networkx
```

Set in `backend/.env`:
```
PYTHON_BIN=/Users/YOUR_USERNAME/miniconda-arm64/bin/python3
```

> **Note:** Always use `/Users/sucheetboppana/miniconda-arm64/bin/python3` — never system Python or conda base.

### 3. Backend dependencies

```bash
cd backend && go mod download
```

### 4. Frontend

```bash
cd frontend && npm install
```

### 5. Run (three terminals)

**Terminal 1 — FastAPI cognition + memory service**
```bash
cd backend
PYTHONPATH=backend /Users/sucheetboppana/miniconda-arm64/bin/python3 \
  -m uvicorn app.main:app --port 8000
```

**Terminal 2 — Go server (manages gRPC vision worker + NATS)**
```bash
cd backend
go run cmd/server/main.go
```

**Terminal 3 — Frontend**
```bash
cd frontend
npm run dev
```

Open `http://localhost:3000` and allow camera and microphone access.

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Required. Claude API key. |
| `PYTHON_BIN` | `python3` | Path to ARM64 Python binary. |
| `WHISPER_MODEL` | `base` | faster-whisper model size (`tiny` / `base` / `small`). |
| `AUDIO_ENABLED` | `true` | Set `false` to disable the audio worker. |
| `ELEVENLABS_API_KEY` | — | Optional. Falls back to browser TTS. |
| `ELEVENLABS_VOICE_ID` | Rachel | ElevenLabs voice ID. |
| `TTS_PROVIDER` | `elevenlabs` | Set `browser` for lower latency. |
| `USE_OLLAMA` | `false` | Use local Ollama instead of Claude. |
| `PORT` | `8080` | Go server port. |
| `DEBUG` | `false` | Verbose server logging. |

See `backend/.env.example` for the full list.

### Testing

```bash
# Python — 160 tests
PYTHONPATH=backend /Users/sucheetboppana/miniconda-arm64/bin/python3 \
  -m pytest backend/tests/ -v

# Go — 20+ tests
cd backend && go build ./... && go vet ./... && go test ./...

# Frontend
cd frontend && npm run build
```

### Development commands

| Command | Description |
|---------|-------------|
| `go run cmd/server/main.go` | Start Go server with gRPC vision worker + NATS |
| `uvicorn app.main:app --port 8000` | Start FastAPI cognition + memory service |
| `npm run dev` | Start Next.js frontend |
| `PYTHONPATH=backend python3 -m pytest backend/tests/ -v` | Run Python test suite (160 tests) |
| `cd backend && go test ./...` | Run Go test suite (20+ tests) |
| `cd frontend && npm run build` | Type-check + build frontend |
| `cd proto && buf generate` | Regenerate Go + Python proto stubs |

---

## Security

All 12 Codex adversarial review findings resolved in v1.5.0–v1.6.0:

| # | Finding | Fix | Version |
|---|---------|-----|---------|
| 1 | gRPC PerceptionService bound to `0.0.0.0` | Rebound to `127.0.0.1:50051` | v1.5.0 |
| 2 | gRPC CognitionService bound to `0.0.0.0` | Rebound to `127.0.0.1:50052` | v1.5.0 |
| 3 | `vision_grpc_server.py` exposed on all interfaces | Loopback-only bind enforced | v1.5.0 |
| 4 | Session IDs used `"default"` wildcard in working memory | UUIDs end-to-end, wildcard removed | v1.5.0 |
| 5 | Interrupt path accepted any string as session ID | Rejected at gRPC ingress if no matching session | v1.5.0 |
| 6 | `CancelActive()` had no session scope guard | Scoped to caller's concrete session UUID only | v1.6.0 |
| 7 | Pending cancel map unbounded — OOM under load | Bounded at 32 entries, 10s TTL eviction | v1.5.0 |
| 8 | WebSocket connections had no `session_init` handshake | `session_init` sent on WS open before any routing | v1.6.0 |
| 9 | Audio worker replay: same utterance could trigger twice | Utterance dedup by timestamp + content hash | v1.6.0 |
| 10 | NATS subscriber had no reconnect backoff | Exponential backoff in ReconnectHandler — prevents storm | v1.7.0 |
| 11 | CoreML backend enabled without accuracy gate | Accuracy benchmarked vs CPU; fallback safety guard retained | v1.3.0 |
| 12 | ANE acceleration not verified against CPU baseline | Benchmark required before enabling; 2.9x confirmed on M1 Pro | v1.3.0 |

**Ongoing constraints:**
- All gRPC services: `127.0.0.1` only — never `0.0.0.0`
- `backend/.env` is gitignored — never commit it
- API keys never hardcoded — always from environment
- Security findings from Codex adversarial review are P0 — fix before merging any sprint

---

## Roadmap

### Completed (Weeks 0–9)

| Week | Module | Deliverable | Status |
|------|--------|-------------|--------|
| 0 | Proto | Protobuf data contract (`perception.proto`) | Complete |
| 1 | gRPC Transport | Typed gRPC stream replacing stdout IPC | Complete |
| 2 | Session State | UUID session isolation across all subsystems | Complete |
| 3 | Bidirectional gRPC + Priority Interrupt | FaceExitDetector → StreamRegistry interrupt path | Complete |
| 4 | ANE Acceleration | CoreML backend, 2.9x speedup, accuracy gate | Complete |
| 5 | NATS Async Transport | NATS event bus, reconnect backoff | Complete |
| 6 | LMCache + Tiered Routing | Prompt caching, Haiku/Sonnet routing | Complete |
| 7 | Shannon Memory Graph | NetworkX graph memory + ChromaDB integration | Complete |
| 8 | Gesture Classification | thumb_up, open_palm, pinch, point via HandGestureEvent | Complete |
| 9 | Spatial Anchoring | SQLite anchor registry, SpatialAnchor proto | Complete |

### In Progress

| Week | Module | Deliverable | Status |
|------|--------|-------------|--------|
| 10 | Hardening | NATS reconnect Go unit tests, anchor delete/update API, observability | In Progress |

### Future

| Version | Scope |
|---------|-------|
| v3 | Spatial computing environment — ARKit integration, persistent spatial map, multi-anchor scene understanding |
| v4 | Autonomous agent architecture — multi-agent task delegation, SOUL.md human-in-the-loop gate, gitagent DUTIES.md segregation |

**Hard constraints:**
- Sub-100ms interrupt latency is non-negotiable
- Proto tags 1–15 (1-byte wire cost) reserved for hot-path fields only
- All timestamps as `int64` microseconds — no `Timestamp` sub-message
- Backward compatibility is non-negotiable after Week 1

---

## Stack

### v2.0.0 full stack

| Layer | Technology |
|-------|-----------|
| WebSocket server | Go 1.21+, chi, gorilla/websocket, zerolog |
| gRPC transport | Go + Python, buf, protobuf, PerceptionService + CognitionService |
| Event bus | NATS (async vision / audio / cognition decoupling) |
| Vision | Python 3.13, MediaPipe Tasks 0.10.32+, OpenCV, CoreML (ANE) |
| Gesture | Python, 21-point hand landmark geometry classifier |
| Audio | Python 3.13, faster-whisper (CoreML), webrtcvad, sounddevice, DeepFilterNet |
| Cognition | Claude Haiku (fast path) + Claude Sonnet (escalated), prompt caching |
| Episodic memory | ChromaDB 1.5.5 (profile / episodic / working collections) |
| Graph memory | NetworkX — relational traversal for memory anchor resolution |
| Spatial anchors | SQLite — persistent anchor registry keyed by session + world position |
| Frontend | Next.js 14, TypeScript, Three.js, Tailwind CSS, Zustand |
| TTS | ElevenLabs streaming (Web Speech API fallback) |
| Proto codegen | buf (`cd proto && buf generate`) |
