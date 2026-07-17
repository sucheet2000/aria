# ARIA

ARIA (Adaptive Reasoning and Intelligent Assistant) is a local, multimodal AI assistant that runs entirely on your machine. It combines real-time computer vision, wake-word-gated voice input, and conversational AI to produce a responsive, hands-free interface. ARIA is designed to be privacy-first: no audio or video leaves your device.

---

## Architecture

```
Browser (Next.js)
    |
    | WebSocket + HTTP
    v
Go server (port 8080)
    |-- /api/cognition  --> FastAPI (port 8000) --> Claude / Ollama
    |-- /api/tts        --> ElevenLabs API
    |-- /ws             --> hub broadcasts vision frames + transcripts
    |
    |-- vision_worker.py   (MediaPipe face + hand tracking, 15fps -> 5fps gated)
    |-- audio_worker.py    (webrtcvad + faster-whisper, wake-word gated)
```

- **Go server** (`backend/`) — HTTP and WebSocket hub, spawns and supervises Python subprocesses, proxies cognition and TTS requests.
- **Python workers** (`backend/app/pipeline/`) — vision runs MediaPipe and streams JSON frames; audio runs VAD + Whisper and streams transcript JSON when active.
- **FastAPI service** (`backend/app/`) — handles cognition requests, maintains conversation context, interfaces with Claude or Ollama.
- **Next.js frontend** (`frontend/`) — renders the 3D avatar, chat log, memory panel, and voice indicator; communicates over WebSocket and REST.

---

## Prerequisites

| Dependency | Version |
|---|---|
| Node.js | 18+ |
| Go | 1.21+ |
| Python | 3.13 |
| Conda (Miniconda) | any recent |

You also need:
- An Anthropic API key (Claude)
- An ElevenLabs API key (TTS) — optional if you prefer browser TTS fallback

---

## Setup

### 1. Clone and enter the repo

```bash
git clone https://github.com/sucheet2000/aria.git
cd aria
```

### 2. Python environment

```bash
conda create -n aria python=3.13 -y
conda activate aria
pip install -r backend/requirements.txt
```

### 3. Environment variables

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and fill in at minimum:

```
ANTHROPIC_API_KEY=sk-ant-...
ELEVENLABS_API_KEY=...        # optional
```

### 4. Frontend dependencies

```bash
cd frontend && npm install && cd ..
```

### 5. Go dependencies

```bash
cd backend && go mod download && cd ..
```

---

## Starting ARIA

Open three terminals.

**Terminal 1 — FastAPI cognition service**

```bash
conda activate aria
cd backend
uvicorn app.main:app --port 8000 --reload
```

**Terminal 2 — Go server**

```bash
cd backend
go run ./cmd/server/main.go
```

The Go server starts on `http://localhost:8080`. It waits up to 30 seconds for FastAPI to be ready before accepting cognition requests.

**Terminal 3 — Frontend**

```bash
cd frontend
npm run dev
```

Open `http://localhost:3000` in your browser.

---

## Usage

### Voice (hands-free)

ARIA uses a two-state wake-word gate. Whisper transcribes continuously but transcripts are only forwarded to cognition when ARIA is active.

**Wake ARIA:**

Say any of the following:

- "Hey ARIA"
- "Hi ARIA"

ARIA activates and listens for 30 seconds of idle time before returning to sleep automatically.

**Put ARIA to sleep:**

Say any of the following:

- "That would be all"
- "That will be all"
- "That's all"
- "Goodbye ARIA"
- "Bye ARIA"
- "Go to sleep"
- "Sleep ARIA"
- "Shut down"

ARIA mutes the microphone for 5 seconds after a sleep phrase to prevent its own TTS response from re-triggering the wake word.

### Text input

Click the chat icon in the left sidebar to open the conversation log. Type a message and press Enter or click Send.

---

## Environment Variables

All variables are read from `backend/.env`. The file is loaded automatically at server startup.

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required. Claude API key. |
| `ELEVENLABS_API_KEY` | — | Required for ElevenLabs TTS. |
| `ELEVENLABS_VOICE_ID` | `21m00Tcm4TlvDq8ikWAM` | ElevenLabs voice (Rachel). |
| `TTS_PROVIDER` | `elevenlabs` | Set to `browser` to use Web Speech API fallback. |
| `USE_OLLAMA` | `false` | Use local Ollama instead of Claude. |
| `OLLAMA_MODEL` | `llama3.2` | Ollama model name. |
| `WHISPER_MODEL` | `base` | faster-whisper model size (`tiny`, `base`, `small`, `medium`). |
| `AUDIO_ENABLED` | `true` | Set to `false` to disable the audio worker. |
| `PYTHON_BIN` | `python3` | Path to Python executable. |
| `PORT` | `8080` | Go server port. |
| `DEBUG` | `false` | Enable verbose server logging. |
| `KMP_DUPLICATE_LIB_OK` | — | Set to `TRUE` on M1/M2 if you hit OpenMP library conflicts. |

---

## Known Limitations

- **Single user only.** The WebSocket hub broadcasts to all connected clients; multi-user sessions are not supported.
- **Microphone device selection.** The audio worker uses the system default input device. Switching devices requires restarting the server.
- **Wake-word accuracy.** Whisper sometimes mishears "ARIA" as "area", "arya", or similar. Common variants are included in the wake-word set but edge cases will occur.
- **TTS latency.** ElevenLabs round-trip adds 1-3 seconds. Use `TTS_PROVIDER=browser` for lower latency at the cost of voice quality.
- **Vision requires a webcam.** The vision worker will exit if no camera is detected. Set `VISION_SCRIPT` to a no-op if running without a camera.
- **macOS only tested.** The Go server and Python workers have been developed and tested on macOS (Apple Silicon). Linux should work but is untested.
