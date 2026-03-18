# ARIA — Adaptive Realtime Intelligence Avatar

ARIA is a multimodal AI companion that perceives you through your camera and microphone, understands your emotional state from facial geometry and voice, and responds through a conversational interface powered by Claude. It runs locally on your machine with no cloud vision or audio processing.

## Architecture

Three-language stack:

- **Go server (port 8080):** manages WebSocket connections, launches Python workers as subprocesses, serves cognition and TTS API endpoints
- **Python vision worker:** reads webcam at 15fps via MediaPipe Tasks, extracts 478 face landmarks, head pose, hand landmarks, and expressive state
- **Python audio worker:** captures microphone via sounddevice, detects speech with webrtcvad, transcribes with faster-whisper
- **Next.js frontend (port 3000):** renders live landmark overlay, conversation UI, voice indicator, and avatar placeholder

Data flow:

    Camera -> Python vision worker -> Go server -> WebSocket -> Browser
    Microphone -> Python audio worker -> Go server -> WebSocket -> Browser
    User speech -> Claude API (cognition) -> TTS -> Audio playback

## Versions

| Version | Description |
|---------|-------------|
| v0.1.0  | Monorepo scaffold — backend pipeline stubs, Go server structure, Next.js frontend shell |
| v0.2.0  | Go WebSocket server, Python MediaPipe vision pipeline, Next.js frontend with live landmark overlay |
| v0.3.0  | Emotion detection via landmark geometry, Claude cognition API, emotion-reactive UI |
| v0.4.0  | Voice input with faster-whisper, webrtcvad VAD, streaming TTS, full spoken conversation loop |
| v0.5.0  | Structured Claude responses, prompt caching (planned) |
| v0.6.0  | Layered memory system with ChromaDB (planned) |
| v0.7.0  | VRM 3D avatar with lip sync and emotion blendshapes (planned) |
| v1.0.0  | Gesture recognition, wake word detection, full MVP (planned) |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Server | Go 1.25, chi router, gorilla/websocket, zerolog |
| Vision | Python 3.13, MediaPipe Tasks 0.10.32, OpenCV |
| Audio | Python 3.13, faster-whisper, webrtcvad, sounddevice |
| AI | Anthropic Claude claude-haiku-4-5 |
| Frontend | Next.js 14, React, TypeScript, Tailwind CSS, Zustand |
| 3D Avatar | Three.js, React Three Fiber (Sprint 7) |

## Prerequisites

- macOS (M1/M2/M3 recommended) or Linux
- Go 1.25+
- Python 3.11+ (ARM64 native on Apple Silicon — use miniconda-arm64)
- Node.js 20+
- Anthropic API key (console.anthropic.com)
- ElevenLabs API key (optional, for voice output)

## Setup

### 1. Clone and configure

    git clone https://github.com/sucheet2000/aria.git
    cd aria
    cp backend/.env.example backend/.env
    # Edit backend/.env and add your ANTHROPIC_API_KEY

### 2. Install Python dependencies (Apple Silicon)

    curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh
    bash Miniconda3-latest-MacOSX-arm64.sh -b -p ~/miniconda-arm64
    source ~/miniconda-arm64/bin/activate
    pip install mediapipe opencv-python torch faster-whisper webrtcvad sounddevice structlog pydantic pydantic-settings anthropic

    # Update backend/.env
    # PYTHON_BIN=/Users/YOUR_USERNAME/miniconda-arm64/bin/python3

### 3. Install Go dependencies

    cd backend
    go mod download

### 4. Install frontend dependencies

    cd frontend
    npm install

### 5. Run

    # Terminal 1 — Go server (auto-starts Python workers)
    cd backend
    go run cmd/server/main.go

    # Terminal 2 — Frontend
    cd frontend
    npm run dev

Open http://localhost:3000. Allow camera and microphone access.

## Development

| Command | Description |
|---------|-------------|
| go run cmd/server/main.go | Start Go server with both Python workers |
| npm run dev | Start Next.js frontend |
| python -m pytest tests/ -v | Run Python test suite |
| go test ./... | Run Go test suite |
| python scripts/vision_preview.py | Preview camera with landmark overlay |
| python scripts/audio_test.py | Test microphone and transcription |

## Environment Variables

See backend/.env.example for all variables. Key ones:

| Variable | Description | Default |
|----------|-------------|---------|
| ANTHROPIC_API_KEY | Anthropic API key | required |
| PYTHON_BIN | Path to Python binary | python3 |
| AUDIO_ENABLED | Enable audio worker | true |
| WHISPER_MODEL | Whisper model size | base |
| ELEVENLABS_API_KEY | ElevenLabs API key | optional |
| USE_OLLAMA | Use Ollama instead of Claude | false |
