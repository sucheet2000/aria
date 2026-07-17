# ARIA — Claude Code Project Context

## What This Project Is
ARIA (Adaptive Realtime Intelligence Avatar) — a real-time multimodal
AI voice companion. Go WebSocket server, Python perception pipeline
(MediaPipe, faster-whisper, ElevenLabs), Next.js frontend with a
low-poly 3D avatar.

## Active Initiative — Professionalization & Restructure
The repo is being professionalized and moved to cloud (Railway backend +
Vercel frontend) in phases. **Read the design + phase map before large changes:**
`docs/plans/2026-07-10-aria-restructure-design.md`.
- Execution: one PR per phase, ultracode-built, CI-verified, merged to `integration`.
- Locked decisions: full scope incl. audit hardening; single-user auth now with a
  multi-user-ready (`owner`/`user_id`-keyed) data model.

## Engineering Standards — Binding (read `docs/STANDARDS.md`)
Every change to ARIA must satisfy `docs/STANDARDS.md`. That file is the enforceable bar; this
section is how you obey it on each change. Rule IDs like `DATA-1` refer to `docs/STANDARDS.md`.
Pre-existing violations live in `docs/STANDARDS_DEBT.md` (tracked, not blocking — the ratchet).

### Non-negotiables (a PR that breaks any of these does not merge)
- **No secret in a URL** — Clerk/internal tokens go in headers or a WS auth frame, never `?token=` (SEC-1).
- **Fail closed** — any process trusting `X-Aria-Owner`/`X-Internal-Auth` refuses to boot without
  `INTERNAL_AUTH_SECRET` when `ENV != local` (SEC-2). gRPC binds `127.0.0.1` only.
- **Owner-scope every data access** at the query layer, from the verified identity — never a body field (SEC-3, DATA-6).
- **No durable state on ephemeral FS** — every persist path is env-driven via `DATA_DIR`; no hardcoded `/app`/`./data` (DATA-1).
- **No server-side physical camera/mic capture** — `cv2.VideoCapture(<int>)` / `sounddevice` input are banned in cloud paths; capture is browser-side (SCALE-1).
- **Every declared import is in the lockfile, pinned + hashed** — including `webrtcvad`. No hand-installed deps (DEP-1, DEP-2).
- **Every third-party call has a timeout + bounded retry**; guard `response.content[0]` (REL-2).
- **Advertised retention is enforced by deletion**, not read-time filtering (DATA-3).
- **Contracts change in one source of truth**, versioned — never hand-edit one of proto/Go/pydantic/TS alone (API-1, API-2). The `gesture` vs `hand_gesture` bug is why.
- **Never commit `backend/.env`; never hardcode API keys; never `git push` without an explicit instruction.**

### Definition of Done checklist (paste into every PR description)
```
- [ ] Tests written first; `make check` green (pytest + go -race + vitest + lint + type-check)
- [ ] No new MUST-rule violation (docs/STANDARDS.md); grandfathered items untouched
- [ ] Secrets & persist paths env-driven; fail-closed guards intact (SEC-2, DATA-1, FE-4)
- [ ] Owner-scoping preserved on all data paths (SEC-3, DATA-6)
- [ ] New deps pinned + hashed + declared + audited (DEP-1..5)
- [ ] New routes: structured JSON log + error metric + request-id + response_model (OBS/API)
- [ ] Contract changes in one source of truth, versioned (API-1, API-2)
- [ ] a11y checked on any UI change: label, contrast, focus, reduced-motion (FE-1)
- [ ] Commit message shown in plain English and approved before commit
```

### Which agent to use when (delegate so subsystem context isn't lost)
- Go server (hub/WS, auth edge, gRPC, tts/vision proxy, shutdown, metrics) → **aria-go-backend**
- Python FastAPI, perception/cognition/memory pipeline, LLM client, persistence → **aria-python-pipeline**
- Next.js, three.js avatar, hooks, zustand, spatial canvas, a11y, WS boundary → **aria-frontend**
- protobuf/buf contracts + the live HTTP/WS contract source-of-truth → **aria-proto**
- Before merging anything touching auth, owner-scoping, secrets, data access, or the trust
  boundary → **aria-security-reviewer** (read-only review, must pass).

### Order of operations for any change
1. Plan (file-by-file) and get explicit "go" before code.
2. Delegate to the owning agent above.
3. TDD: red → green → refactor.
4. `make check` locally; fix all four suites.
5. Run `aria-security-reviewer` if the change touches the trust boundary/data.
6. Show the plain-English commit message; wait for approval; commit.
7. Open PR to `integration` (never push to dev/prod without an explicit instruction).

## Tech Stack
- Backend: Go 1.26, Python 3.13, FastAPI, gRPC (buf), protobuf
- Frontend: Next.js 14, TypeScript, Three.js, Tailwind
- AI: Claude API (Haiku for cognition), ElevenLabs TTS, faster-whisper STT
- Data: ChromaDB (3-tier memory), SQLite (spatial anchors), WebSocket hub
- Tools: buf (proto codegen), pytest, Go test

## Repo Layout
- `backend/cmd`, `backend/internal` — Go server (hub, cognition, tts, vision, nats, memory)
- `backend/app` — Python FastAPI + perception/cognition pipeline
- `backend/tests` — Python tests · `backend/gen` — generated proto stubs
- `frontend/src` — Next.js app (components, hooks, spatial, store)
- `proto/` — protobuf contracts · `docs/` — architecture, decisions, plans, reference docs
- `.claude/agents/` — project-specific subagents (below); `.claude/skills/` — project skills
- `SOUL.md` (repo root) — ARIA's runtime identity; **do not move** (loaded by `backend/app/cognition/prompt.py`)

## Project Agents (`.claude/agents/`)
Delegate to these preloaded subagents so subsystem context isn't lost:
- `aria-go-backend` — Go server: hub/WS, gRPC cognition, tts/vision/audio workers, NATS, config
- `aria-python-pipeline` — FastAPI + perception/cognition/memory pipeline (Python)
- `aria-frontend` — Next.js, three.js avatar, zustand store, spatial canvas
- `aria-proto` — protobuf/buf contracts, Go+Python stub generation
- `aria-security-reviewer` — read-only, audit-aware security review of changes

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
Python: PYTHONPATH=/Users/sucheetboppana/aria/backend python3 -m pytest /Users/sucheetboppana/aria/backend/tests/ -v
Go: cd backend && go build ./... && go vet ./... && go test ./...
Frontend: cd frontend && npm run lint && npm run type-check && npm run build && npm test
Current count: 234 Python tests, all must pass
ruff and mypy must also pass: cd backend && ruff check . && mypy app tests
ruff>=0.9.0 and mypy>=1.0.0 are pinned in backend/requirements.txt

## CI (.github/workflows/ci.yml)
Triggers on push + PR to `integration` and `main`; a `concurrency` group cancels superseded runs.
Three jobs:
- python-tests: Python 3.13 → CPU-only torch pre-install → `pip install` → ruff → mypy → pytest
  (ruff and mypy must pass before pytest runs)
- go-backend: Go version read from `backend/go.mod` (`go-version-file`) → build → vet → test
- frontend: npm ci → eslint → type-check → build
Dependencies are pinned in backend/requirements.txt — update pins when bumping versions locally.
setuptools>=78.1.1 required (3 CVEs below that version).
CI installs the CPU-only torch build (`torch==2.10.0+cpu`) to skip ~3 GB of unused CUDA wheels;
requirements.txt is unchanged so local macOS dev is unaffected.

## Branch Strategy
- main: stable releases only
- integration: all development
- Always push to integration, merge to main after each week

## Code Generation
Proto contract: proto/perception/v1/perception.proto (package aria.perception.v1)
Stubs (Go + Python): cd proto && buf generate
One command generates both Go (backend/gen/go/perception/v1) and self-contained
nested Python (backend/gen/python/perception/v1). No separate grpc_tools step.

## Architecture Decisions
- Session IDs: UUIDs generated per client, stored in ariaStore (a per-user `owner` key is added in Phase 3)
- gRPC ports: 127.0.0.1:50051 (PerceptionService), 127.0.0.1:50052 (CognitionService)
- Interrupt path: FaceExitDetector → gRPC → StreamRegistry.CancelActive() → WebSocket aria_interrupt
- Spatial anchors: SQLite via app/spatial/anchor_registry.py (create/get/list/update/delete)
- SOUL.md: ARIA's identity loaded at runtime by backend/app/cognition/prompt.py
- Wake word: "Hey ARIA" — sleep: "that would be all"

## Roadmap
Weeks 0–11 complete (through NATS async transport and the spatial canvas).
Current work is the professionalization program — see
`docs/plans/2026-07-10-aria-restructure-design.md`,
`docs/IMPROVEMENT_SCHEME.md`, and `docs/ARIA_V4_VISION.md`.

## Config & Rules Files
- `AGENTS.md` is the canonical cross-tool agent ruleset.
- `.cursorrules`, `.windsurfrules`, `GEMINI.md` are symlinks to `AGENTS.md` (edit `AGENTS.md` only).
- `CLAUDE.md` (this file) is the richer Claude Code context.

## Do Not
- Never commit backend/.env
- Never hardcode API keys
- Never use 0.0.0.0 for gRPC binds (use 127.0.0.1)
- Never skip tests before committing
- Never add --grpc or --coreml to default startup without benchmarking
- Never use unpinned heavy deps (torch, chromadb, faster-whisper) — pip backtracking breaks CI
- Never add code that fails ruff check . in backend/
- Do not attempt to make mypy strict across the full codebase — this is v3 scope.
  app.cognition.memory and app.observability.* use ignore_errors=true (chromadb
  and metrics singleton patterns are not mypy-compatible without major refactoring).
  vision_worker uses deferred imports inside try blocks — noqa: F821 is intentional.
  coremltools and openai-whisper are macOS-only — use mock.patch.dict(sys.modules)
  NOT sys.modules.setdefault() in tests.

## MCP Tools: code-review-graph
**IMPORTANT: This project has a knowledge graph. Prefer the code-review-graph
MCP tools BEFORE Grep/Glob/Read to explore the codebase.** It is faster, cheaper
(fewer tokens), and gives structural context (callers, dependents, test coverage)
that file scanning cannot. (If the graph is empty/unbuilt, fall back to Grep/Glob/Read.)

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

## Response Style for Claude Code Sessions
- Action first. No preamble.
- No "I'll help you with that" or "Let me search for you" before doing it.
- No narrating tool calls. Tool output speaks for itself.
- No restating what was just done in a summary after completion.
- If result is obvious, stop. No explanation needed.
- Commit messages: one line, no body unless critical.
- Test output: show only failures and final count. Not every PASS.

## Codex Review Workflow
- After each sprint: /code-review-graph:review-delta first
- Then: /codex:adversarial-review --background
- Check: /codex:status then /codex:result
- Max 3 Codex rounds per sprint
- Document architectural findings as v2 scope instead of looping
- Start a fresh Claude Code session for each sprint to keep Codex skill enabled

## Known Test Gaps (tracked)
- NATS subscriber reconnect path (DisconnectErrHandler, ReconnectHandler)
  has no Go unit test. Follow-up: add embedded nats-server test.
