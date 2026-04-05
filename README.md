<div align="center">

# ARIA

**Adaptive Realtime Intelligence Avatar**

[![Go](https://img.shields.io/badge/Go-1.21+-00ADD8?style=flat-square&logo=go&logoColor=white)](https://golang.org)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![Platform](https://img.shields.io/badge/Platform-Apple%20Silicon-555555?style=flat-square&logo=apple&logoColor=white)](https://apple.com/mac)
[![License](https://img.shields.io/badge/License-Private-red?style=flat-square)](#)

A real-time multimodal AI companion. Sees you through your camera, hears you through your microphone, reasons about your emotional and cognitive state, and maintains a persistent world model of who you are — entirely on-device.

</div>

---

## Architecture

ARIA is a three-language stack with clean subprocess boundaries.

```
  Browser (Next.js :3000)
       |
       | WebSocket  ws://localhost:8080/ws
       | HTTP POST  /api/cognition
       | HTTP POST  /api/tts
       |
  Go Server (:8080)
       |-- subprocess --> Python Vision Worker
       |                    MediaPipe Tasks FaceLandmarker (478 points)
       |                    Emotion classifier (7 classes, landmark geometry)
       |                    Head pose via solvePnP (pitch / yaw / roll)
       |                    Hand landmarks (21 points per hand)
       |                    15 fps JSON to stdout
       |
       |-- subprocess --> Python Audio Worker
       |                    sounddevice microphone capture at 16 kHz
       |                    webrtcvad voice activity detection
       |                    DeepFilterNet noise isolation (--denoise flag)
       |                    faster-whisper speech-to-text (base, int8)
       |                    JSON to stdout on utterance end
       |
       |-- HTTP proxy --> Python FastAPI (:8000)
                            Neurosymbolic prompt builder
                            Conflict detection (speech vs visual sentiment)
                            Claude Haiku structured response
                            ChromaDB layered memory (profile / episodic / working)
```

**Design decisions:**

| ADR | Decision | Rationale |
|-----|----------|-----------|
| 001 | Go for WebSocket, Python for ML | Goroutines handle concurrent connections; Python owns the ML ecosystem |
| 002 | Subprocess stdout as IPC | No broker needed; Python crashes don't kill Go; auto-restart is trivial |
| 003 | webrtcvad over Silero VAD | No torch dependency; native ARM64; sub-1ms per 30ms chunk |
| 004 | Native ARM64 Python via miniconda | Avoids Rosetta conflicts; unlocks Apple Neural Engine for ML inference |
| 005 | MediaPipe Tasks API | Solutions API deprecated in 0.10.21+; Tasks API has Metal GPU acceleration |

---

## Pipeline Timeline

### Vision pipeline (15 fps continuous)

```
Webcam frame
  → MediaPipe FaceLandmarker       — 478 normalized landmarks (x, y, z)
  → Emotion classifier             — 7 classes, 5-frame smoothing
  → Head pose (solvePnP)           — pitch / yaw / roll in degrees
  → JSON stdout line
  → Go reads stdout
  → Broadcast to all WebSocket clients
  → Browser updates landmark overlay + emotion display
```

### Audio pipeline (per utterance)

```
Microphone (16 kHz)
  → DeepFilterNet (optional)       — noise isolation
  → webrtcvad (30ms chunks)        — voice activity boundary detection
  → faster-whisper base/int8       — speech-to-text transcription
  → JSON stdout line
  → Go reads stdout
  → Broadcast transcript over WebSocket
  → Browser auto-sends to /api/cognition
  → FastAPI builds neurosymbolic prompt
  → Claude Haiku returns structured response
  → Browser calls /api/tts
  → ElevenLabs streams audio → browser plays
```

### Neurosymbolic cognition loop

```
Each cognition turn:
  ┌─ Current perceptual state      — emotion, head pose, hands, face_detected
  ├─ Go working memory (circular)  — last 10 symbolic inferences
  └─ ChromaDB retrieval            — relevant long-term profile + episodic facts
        ↓
  FastAPI assembles structured prompt
        ↓
  Claude Haiku responds:
    {
      "symbolic_inference": "...",
      "world_model_update": { "triple": {…}, "confidence": 0.85 },
      "natural_language_response": "..."
    }
        ↓
  Triple written back to ChromaDB — persistent world model updated
```

**Conflict detection:** if `|speech_sentiment − visual_sentiment| > 0.4`, ARIA responds to the observable affect via open invitation rather than validating the stated emotion.

---

## Version History

<details>
<summary><strong>v0.1.0</strong> — Monorepo scaffold</summary>

- Repository structure: `backend/`, `frontend/`, `ml/`, `shared/`, `docs/`, `proto/`
- `buf.gen.yaml` and proto scaffolding
- CI workflow skeleton

</details>

<details>
<summary><strong>v0.2.0</strong> — Go WebSocket server + MediaPipe vision + Next.js frontend</summary>

- Go server with chi router, gorilla/websocket hub, subprocess lifecycle manager
- Python vision worker: MediaPipe FaceLandmarker + HandLandmarker at 15 fps
- Next.js 14 frontend with live landmark canvas overlay
- Zustand store for vision + conversation state

</details>

<details>
<summary><strong>v0.3.0</strong> — Emotion detection + Claude cognition</summary>

- Landmark geometry emotion classifier (7 classes, 5-frame smoothing)
- Head pose estimation via OpenCV solvePnP
- `/api/cognition` proxied from Go to FastAPI → Claude Haiku
- Conversation history management

</details>

<details>
<summary><strong>v0.4.1</strong> — Voice input + faster-whisper + streaming TTS</summary>

- Python audio worker: sounddevice 16 kHz capture
- webrtcvad voice activity detection (aggressiveness=2)
- faster-whisper base model, int8 quantization
- ElevenLabs streaming TTS with Web Speech API fallback
- Wake word: "Hey ARIA" — sleep: "That would be all"
- VoiceIndicator component; VoiceDot bottom-center UI

</details>

<details>
<summary><strong>v0.5.0</strong> — Neurosymbolic reasoning + world model triples</summary>

- System 1 / System 2 architecture
- Structured Claude response schema (symbolic_inference, world_model_update, natural_language_response)
- Go working memory circular buffer (last 10 inferences)
- Conflict detection: speech vs visual sentiment divergence

</details>

<details>
<summary><strong>v0.6.0</strong> — ChromaDB persistent memory + DeepFilterNet</summary>

- Three ChromaDB collections: `aria_profile` (permanent), `aria_episodic` (30-day TTL), `aria_working` (session)
- DeepFilterNet noise isolation (`--denoise` flag on audio worker)
- Message UI panel with ChatPanel + MemoryPanel slide-out components
- Low-poly 3D avatar placeholder (Avatar3D, Three.js)

</details>

<details>
<summary><strong>v0.7.0</strong> — VRM avatar (planned)</summary>

- three-vrm integration
- Lip sync driven by TTS phoneme stream
- Emotion blendshapes mapped from classifier output

</details>

<details>
<summary><strong>v1.0.0</strong> — Full MVP (planned)</summary>

- Gesture recognition (thumb_up, open_palm, pinch, point)
- Wake word detection hardened
- Full gRPC transport replacing stdout IPC for vision
- NATS async transport for all internal events

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
            anthropic fastapi uvicorn chromadb deepfilternet
```

Set in `backend/.env`:
```
PYTHON_BIN=/Users/YOUR_USERNAME/miniconda-arm64/bin/python3
```

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
source ~/miniconda-arm64/bin/activate
cd backend
PYTHONPATH=$(pwd) python3 -m uvicorn app.main:app --port 8000
```

**Terminal 2 — Go server (auto-starts vision + audio workers)**
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

### Development commands

| Command | Description |
|---------|-------------|
| `go run cmd/server/main.go` | Start Go server with Python workers |
| `uvicorn app.main:app --port 8000` | Start FastAPI cognition service |
| `npm run dev` | Start Next.js frontend |
| `PYTHONPATH=backend python3 -m pytest backend/tests/ -v` | Run Python test suite (93 tests) |
| `cd backend && go test ./...` | Run Go test suite |
| `cd frontend && npm run build` | Type-check + build frontend |

---

## Security

| Finding | Severity | Status |
|---------|----------|--------|
| gRPC bound to `127.0.0.1` only — no external exposure | N/A | Enforced |
| API keys loaded from `backend/.env` — never hardcoded | N/A | Enforced |
| `backend/.env` excluded from `.gitignore` and CI | N/A | Enforced |
| WebSocket hub broadcasts to all connected clients — no auth | Low | Known limitation (single-user design) |
| Vision worker stdout pipe — no integrity check on JSON frames | Low | Accepted (localhost-only subprocess) |
| ElevenLabs audio streamed over HTTPS — no local key storage beyond `.env` | N/A | Enforced |
| TTS mute window (5s) after sleep phrase — prevents self-wake-word loop | N/A | Implemented in v0.4.1 |

**Do not:**
- Run with `USE_OLLAMA=false` and expose port 8080 publicly without a reverse proxy and auth layer
- Commit `backend/.env` — it is gitignored but verify before any force-push

---

## Roadmap

| Week | Module | Goal | Status |
|------|--------|------|--------|
| 0 | Proto | Protobuf data contract (`perception.proto`) | Complete |
| 1 | gRPC Transport | Replace stdout IPC with typed gRPC stream (PerceptionService) | Complete |
| 2 | Session State | Per-session state management | In progress |
| 3 | Bidirectional gRPC + Priority Interrupt | Interrupt path via StreamRegistry | Planned |
| 4 | ANE Acceleration | Core ML / ANE inference for vision models | Planned |
| 5 | NATS Async Transport | Replace all internal event buses with NATS | Planned |
| 6 | LMCache Integration | KV-cache reuse for cognition latency | Planned |
| 7 | Shannon Memory Graph | Graph-structured episodic memory | Planned |
| 8 | Gesture Classification | `thumb_up`, `open_palm`, `pinch`, `point` | Planned |
| 9 | Spatial Anchoring | Persistent spatial anchors for object references | Planned |
| 10 | Hardening | NATS reconnect tests, anchor delete API, observability | Planned |

**Hard constraints:**
- Sub-100ms interrupt latency is non-negotiable
- Proto tags 1–15 (1-byte wire cost) reserved for hot-path fields only
- All timestamps as `int64` microseconds — no `Timestamp` sub-message
- Backward compatibility is non-negotiable after Week 1

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Server | Go 1.21+, chi, gorilla/websocket, zerolog |
| Vision | Python 3.13, MediaPipe Tasks 0.10.32+, OpenCV |
| Audio | Python 3.13, faster-whisper, webrtcvad, sounddevice, DeepFilterNet |
| Cognition | Anthropic Claude Haiku, FastAPI, structlog |
| Memory | ChromaDB 1.5.5 (profile / episodic / working collections) |
| Frontend | Next.js 14, TypeScript, Three.js, Tailwind CSS, Zustand |
| TTS | ElevenLabs (browser Web Speech API fallback) |
| Transport | gRPC (buf), protobuf, NATS (Week 5) |
