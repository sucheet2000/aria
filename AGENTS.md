# AGENTS

This document records which agent owns which parts of the repository.
Do not modify another agent's owned paths without coordinating first.

## Agent 1 — Go WebSocket Server

**Owns:** `backend/cmd/` and `backend/internal/`

Responsibilities:
- Go HTTP/WebSocket server (`cmd/server/main.go`)
- Hub, client management, WebSocket upgrade (`internal/server/`)
- Runtime configuration (`internal/config/`)
- Python vision subprocess management (`internal/vision/`)

The server reads JSON lines from the Python vision worker's stdout and
broadcasts them verbatim to all connected browser WebSocket clients on
`ws://localhost:8080/ws`.

## Agent 2 — Python Vision Pipeline

**Owns:** `backend/app/` and related Python tooling

Responsibilities:
- MediaPipe face/hand landmark extraction
- Emotion classification
- Head pose estimation
- Writing one JSON line per frame to stdout (the contract consumed by Agent 1)

## Agent 3 — Frontend

**Owns:** `frontend/`

Responsibilities:
- Browser WebSocket client connecting to `ws://localhost:8080/ws`
- Real-time rendering of landmarks, emotion, and pose data
