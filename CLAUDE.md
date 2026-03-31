# ARIA — Claude Code Project Context

## What This Project Is
ARIA (Adaptive Realtime Intelligence Avatar) — a real-time multimodal
AI voice companion. Go WebSocket server, Python perception pipeline
(MediaPipe, faster-whisper, ElevenLabs), Next.js frontend with a
low-poly 3D avatar.

## Tech Stack
- Backend: Go 1.21+, Python 3.13, FastAPI, gRPC (buf), protobuf
- Frontend: Next.js 14, TypeScript, Three.js, Tailwind
- AI: Claude API (Haiku for cognition), ElevenLabs TTS, faster-whisper STT
- Data: ChromaDB (3-tier memory), WebSocket hub
- Tools: buf (proto codegen), pytest, Go test

## Startup Sequence (3 terminals)
Terminal 1: export $(grep -v '^#' ~/aria/backend/.env | xargs)
            cd ~/aria/backend
            PYTHONPATH=/Users/sucheetboppana/aria/backend \
            /Users/sucheetboppana/miniconda-arm64/bin/python3 \
            -m uvicorn app.main:app --port 8000

Terminal 2: pkill -f "audio_worker.py" 2>/dev/null
            cd ~/aria/backend && go run cmd/server/main.go

Terminal 3: cd ~/aria/frontend && npm run dev

## Python Binary
Always use: /Users/sucheetboppana/miniconda-arm64/bin/python3
Never use system python3 or conda base python

## Testing
Python: PYTHONPATH=backend python3 -m pytest backend/tests/ -v
Go: cd backend && go build ./... && go vet ./... && go test ./...
Frontend: cd frontend && npm run build
Current count: 93 Python tests, all must pass

## Branch Strategy
- main: stable releases only
- integration: all development
- Always push to integration, merge to main after each week

## Code Generation
Proto stubs: cd proto && buf generate
Python stubs: python3 -m grpc_tools.protoc -I. --python_out=../backend/gen/python --grpc_python_out=../backend/gen/python perception.proto

## Architecture Decisions
- Session IDs: UUIDs generated per client, stored in ariaStore
- gRPC ports: 127.0.0.1:50051 (PerceptionService), 127.0.0.1:50052 (CognitionService)
- Interrupt path: FaceExitDetector → gRPC → StreamRegistry.CancelActive() → WebSocket aria_interrupt
- SOUL.md: ARIA's identity loaded at runtime by backend/app/cognition/prompt.py
- Wake word: "Hey ARIA" — sleep: "that would be all"

## Improvement Roadmap
Weeks 0-4 complete. Week 5 next: NATS async transport.
See IMPROVEMENT_SCHEME.md for full roadmap.
See docs/ARIA_V4_VISION.md for long-term vision.

## Do Not
- Never commit backend/.env
- Never hardcode API keys
- Never use 0.0.0.0 for gRPC binds (use 127.0.0.1)
- Never skip tests before committing
- Never add --grpc or --coreml to default startup without benchmarking
