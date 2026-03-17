# ARIA — Adaptive Real-time Intelligence Avatar

A multimodal AGI avatar system combining real-time vision, gesture recognition, speech processing, and Claude-powered cognition in a live interactive interface.

## Architecture

The system is composed of three layers that communicate over WebSocket and stdio:

- **Go WebSocket server (port 8080)** — the central hub. It manages all browser connections, spawns the Python vision worker as a subprocess, reads JSON frames from its stdout, and broadcasts vision state to every connected client.
- **Python vision worker** — reads the webcam via MediaPipe, runs face mesh and head pose estimation at 15 fps, and writes JSON to stdout. It is started and supervised by the Go server; you do not run it directly in production.
- **Next.js frontend (port 3000)** — connects to the Go WebSocket server, renders a live landmark overlay on a canvas, and hosts the conversation UI.
- **FastAPI (port 8000)** — reserved for LLM orchestration and memory endpoints in future sprints. Not active in Sprint 2.

## Tech Stack

| Layer | Technologies |
|---|---|
| Backend server | Go, gorilla/websocket, chi, zerolog |
| Vision pipeline | Python, MediaPipe, OpenCV |
| Frontend | TypeScript, Next.js, Zustand |
| 3D rendering (Sprint 7) | Three.js |

## Setup

### Prerequisites

- Go 1.25+
- Python 3.11+
- Node 20+

### Backend (Go server — starts Python automatically)

```bash
cd backend
go run cmd/server/main.go
```

### Vision preview (optional, developer tool)

Run the vision worker standalone to verify webcam and landmark output before starting the full stack:

```bash
cd backend
source .venv/bin/activate
python app/pipeline/vision_worker.py --preview
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at http://localhost:3000 and connects to the Go server at ws://localhost:8080.

### Environment variables

Create `backend/.env`:

```
ANTHROPIC_API_KEY=your_key
ELEVENLABS_API_KEY=your_key
DEBUG=false
```

## Development

| Command | Description |
|---|---|
| `go test ./...` | Run backend Go tests |
| `pytest tests/ -v` | Run Python vision tests |
| `npm run lint` | Lint frontend |
| `npm run type-check` | Type-check frontend |

## Versions

| Version | Description |
|---|---|
| v0.1.0 | Monorepo scaffold |
| v0.2.0 | Go WebSocket server, Python MediaPipe vision pipeline, Next.js frontend |
