# ARIA — Adaptive Realtime Intelligence Avatar

ARIA is a multimodal AI companion that perceives you through your camera and microphone, reasons about your emotional and cognitive state using a neurosymbolic architecture, and maintains a persistent world model of who you are across sessions. It runs locally on Apple Silicon with no cloud vision or audio processing.

## Architecture

ARIA is built on a three-language stack. A Go server coordinates all subsystems: it manages WebSocket connections to the browser, proxies cognition requests to a Python FastAPI service, and launches vision and audio workers as long-running subprocesses. Python handles all perception — MediaPipe Tasks for face and hand landmark extraction, faster-whisper for speech transcription, and a FastAPI service that builds neurosymbolic prompts, queries ChromaDB memory collections, and calls Claude. The Next.js frontend renders the live landmark overlay, conversation history, memory panel, and thinking indicator over WebSocket.

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
       |                    sounddevice microphone capture at 16kHz
       |                    webrtcvad voice activity detection
       |                    DeepFilterNet noise isolation (--denoise flag)
       |                    faster-whisper speech-to-text (base, int8)
       |                    JSON to stdout on utterance end
       |
       |-- HTTP proxy --> Python FastAPI (:8000)
                            Neurosymbolic prompt builder
                            Conflict detection (speech vs visual sentiment)
                            Claude claude-haiku-4-5 structured response
                            ChromaDB layered memory (profile / episodic / working)
```

## Neurosymbolic reasoning

System 1 is the fast, parallel, pattern-based perception layer: MediaPipe extracts 478 face landmarks, head pose angles, and hand geometry at 15 fps, while faster-whisper transcribes speech in real time. These streams produce continuous signals — emotion class, attention estimate, head orientation, and utterance text — that are forwarded to the cognition layer as structured JSON on every cycle.

System 2 is the symbolic inference layer built around Claude. On each cognition turn, the FastAPI service assembles a structured prompt from the current perceptual state, the last 10 symbolic inferences held in Go working memory, and relevant long-term facts retrieved from ChromaDB. Claude returns a structured response containing a symbolic inference, a world model triple, and a natural language reply. The triple is then written back to the appropriate ChromaDB collection, updating ARIA's persistent model of the user.

Conflict detection: if the absolute difference between speech sentiment and visual sentiment exceeds 0.4, ARIA responds to the visual truth via open invitation rather than validating the speech surface or directly confronting the incongruence. This prevents ARIA from reinforcing a stated emotion that contradicts observable affect.

Structured response schema:

```json
{
  "symbolic_inference": "user is in focused debugging state",
  "world_model_update": {
    "triple": { "subject": "...", "predicate": "...", "object": "..." },
    "confidence": 0.85,
    "source": "explicit_statement"
  },
  "natural_language_response": "spoken response here"
}
```

## Memory system

ARIA uses three ChromaDB collections with different retention policies:

| Collection    | Retention   | Contents |
|---------------|-------------|----------|
| aria_profile  | permanent   | explicit user facts |
| aria_episodic | 30-day TTL  | behavioral and visual inferences |
| aria_working  | session     | cleared on shutdown |

Working memory is implemented as a Go circular buffer holding the last 10 symbolic inferences. Its contents are serialized and injected into every Claude prompt as short-term context, giving ARIA continuity within a session without requiring a database lookup on every turn.

## Versions

| Version | Status   | Description |
|---------|----------|-------------|
| v0.1.0  | released | Monorepo scaffold |
| v0.2.0  | released | Go WebSocket server, MediaPipe vision pipeline, Next.js frontend |
| v0.3.0  | released | Emotion detection, Claude cognition API |
| v0.4.1  | released | Voice input, faster-whisper, webrtcvad, streaming TTS |
| v0.5.0  | released | Neurosymbolic reasoning, world model triples, working memory |
| v0.6.0  | released | ChromaDB persistent memory, DeepFilterNet noise isolation, message UI |
| v0.7.0  | planned  | VRM avatar, three-vrm, lip sync, emotion blendshapes |
| v1.0.0  | planned  | Gesture recognition, wake word detection, full MVP |

## Tech stack

| Layer     | Technology |
|-----------|-----------|
| Server    | Go 1.25, chi, gorilla/websocket, zerolog |
| Vision    | Python 3.13, MediaPipe Tasks 0.10.32, OpenCV |
| Audio     | Python 3.13, faster-whisper, webrtcvad, sounddevice, DeepFilterNet |
| AI        | Anthropic Claude claude-haiku-4-5 |
| Memory    | ChromaDB 1.5.5 (profile, episodic, working collections) |
| Frontend  | Next.js 14, TypeScript, Tailwind CSS, Zustand |
| TTS       | ElevenLabs (macOS say fallback) |

## Prerequisites

- macOS Apple Silicon (M1/M2/M3) or Linux
- Go 1.25+
- Python 3.11+ ARM64 native (see setup below)
- Node.js 20+
- Anthropic API key

## Setup

### 1. Clone

    git clone https://github.com/sucheet2000/aria.git
    cd aria
    cp backend/.env.example backend/.env
    # Add ANTHROPIC_API_KEY to backend/.env

### 2. Python environment (Apple Silicon)

    curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh
    bash Miniconda3-latest-MacOSX-arm64.sh -b -p ~/miniconda-arm64
    source ~/miniconda-arm64/bin/activate
    pip install mediapipe opencv-python torch faster-whisper webrtcvad \
                sounddevice structlog pydantic pydantic-settings \
                anthropic fastapi uvicorn chromadb deepfilternet

    # Set in backend/.env:
    # PYTHON_BIN=/Users/YOUR_USERNAME/miniconda-arm64/bin/python3

### 3. Go dependencies

    cd backend && go mod download

### 4. Frontend

    cd frontend && npm install

### 5. Run (three terminals required)

    # Terminal 1 — FastAPI cognition and memory service
    source ~/miniconda-arm64/bin/activate
    cd backend
    PYTHONPATH=$(pwd) python3 -m uvicorn app.main:app --port 8000

    # Terminal 2 — Go server (auto-starts vision and audio workers)
    cd backend
    go run cmd/server/main.go

    # Terminal 3 — Frontend
    cd frontend
    npm run dev

    Open http://localhost:3000 and allow camera and microphone access.

## Development commands

| Command | Description |
|---------|-------------|
| go run cmd/server/main.go | Start Go server with Python workers |
| uvicorn app.main:app --port 8000 | Start FastAPI cognition service |
| npm run dev | Start Next.js frontend |
| pytest tests/ -v | Run Python test suite |
| go test ./... | Run Go test suite |
| python scripts/audio_test.py | Test microphone and transcription |
| python scripts/audio_test.py --denoise | Test with noise isolation |
| curl localhost:8000/api/memory/profile | Inspect stored profile facts |

## Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| ANTHROPIC_API_KEY | Anthropic API key | required |
| PYTHON_BIN | Path to ARM64 Python | python3 |
| WHISPER_MODEL | Whisper model size | base |
| AUDIO_ENABLED | Enable audio worker | true |
| ELEVENLABS_API_KEY | ElevenLabs TTS key | optional |
| USE_OLLAMA | Use Ollama instead of Claude | false |

See backend/.env.example for the complete list.
