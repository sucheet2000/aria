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

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.

## Response Style for Claude Code Sessions
- Action first. No preamble.
- No "I'll help you with that" or "Let me search for you" before doing it.
- No narrating tool calls. Tool output speaks for itself.
- No restating what was just done in a summary after completion.
- If result is obvious, stop. No explanation needed.
- Commit messages: one line, no body unless critical.
- Test output: show only failures and final count. Not every PASS.
