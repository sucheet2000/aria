# ARIA Professionalization & Restructure — Design

- **Date:** 2026-07-10
- **Status:** Approved (brainstorming complete)
- **Owner:** Boppana Sai Sucheet

## Context — why we're doing this

ARIA works, but the repo has drifted into disorganization that makes it slow to
navigate, easy to lose context in, and not production-grade. A comprehensive audit
(security, reliability, concurrency, accessibility, UI) surfaced launch-blocking
issues, and the tree itself carries duplicate config, orphaned experiments, and
missing "professional" plumbing. The goal is a clean, maintainable, cloud-deployed
codebase where a developer (or a Claude subagent) can find and change any part
without losing context.

## Locked decisions

| Decision | Choice |
|---|---|
| **Scope** | Full transformation **including** the audit's security/reliability hardening |
| **Deploy target** | Railway (Go + Python backend) + Vercel (Next.js frontend), internet-facing |
| **Tenancy** | Single-user auth **now**; data model **multi-user-ready** (`owner`/`user_id` keyed from the start) |
| **Execution** | Hybrid-phased: one low-risk structural Phase 0, then **one PR per phase**, ultracode-built, CI-verified, merged to `integration`, promoted to `main` on the weekly cadence |

## The mess (current state)

- **Config sprawl:** `.cursorrules`, `.windsurfrules`, `AGENTS.md`, `GEMINI.md` were four byte-identical copies; an empty `CLAUDE.md.tmp`; a legacy `agent.yaml` v3 orchestrator config.
- **Two competing "agent" systems:** a dead `agents/` dir (`reviewer`, `spatial-builder`, `gesture-engine`) vs `.claude/skills/` — and no `.claude/agents/` (the project subagents don't exist yet).
- **Orphans:** `ml/`, `shared/`, `agents/`, `workflows/` — unreferenced since the early sprints.
- **Missing pro layers:** no Dockerfiles (`docker-compose.yml` references a nonexistent `backend/Dockerfile`), no task runner, no pre-commit, no dependabot, no `.editorconfig`.
- **Root markdown clutter** overlapping the already-decent `docs/`.
- **Runtime gotcha:** `SOUL.md` is loaded from repo root by `backend/app/cognition/prompt.py` — it is a runtime asset, **not** clutter, and must stay at root.

## Target repo structure (end state)

```
aria/
├── AGENTS.md                # canonical cross-tool agent rules (.cursorrules/.windsurfrules/GEMINI.md → symlinks)
├── CLAUDE.md                # rich Claude Code context (points to this design + phase map)
├── README.md  CONTRIBUTING.md  SOUL.md   # SOUL.md is a runtime asset — stays at root
├── .claude/agents/          # project-specific subagents (Phase 1)
├── backend/                 # Go (cmd, internal) + Python (app) + tests
├── frontend/                # Next.js app
├── proto/                   # protobuf contracts (buf)
├── docs/                    # architecture, decisions, plans/, moved reference docs
├── deploy/                  # Dockerfiles, Railway/Vercel config (Phase 2/5)
└── .github/                 # CI, CODEOWNERS, dependabot
```

## Phase map

Each phase is one PR, reviewed and merged by the owner, CI-verified before the next.

| Phase | What | Risk | Runtime? |
|---|---|---|---|
| **0 · Foundation** | Dedupe rule files → 1 canonical + symlinks; remove `ml/`,`shared/`,`agents/`,`workflows/`,`agent.yaml`,`CLAUDE.md.tmp`; move stray docs into `docs/`; rewrite **CLAUDE.md**; add `.editorconfig`; this design doc | Low | No |
| **1 · Project agents** | `.claude/agents/`: `aria-go-backend`, `aria-python-pipeline`, `aria-frontend`, `aria-proto`, `aria-security-reviewer` — each preloaded with its subsystem file map, conventions, commands, gotchas | Low | No |
| **2 · Pro infra** | `deploy/backend.Dockerfile` + frontend build config, `.dockerignore`, `justfile`/`Makefile`, pre-commit (ruff/mypy/eslint/gofmt), dependabot, expand CI (`go test -race`, coverage) | Low–Med | Build only |
| **3 · Data layer** | Add `owner`/`user_id` to memory (Chroma metadata), anchors (SQLite column), sessions; request-scoped services instead of module-global singletons; move blocking Chroma/SQLite off the event loop | **High** | Yes |
| **4 · Auth + security** | Single-user auth gate (bearer/login) on `/api` + WS handshake; per-session broadcast scoping; rate-limiting; CORS allow-list; bind 127.0.0.1 + TLS via platform (fixes audit H1–H3) | **High** | Yes |
| **5 · Deploy** | Railway (Go + Python services + NATS) + Vercel (frontend); env/secrets; CI/CD-to-deploy; `wss`/https; configurable frontend base URL | Med | Deploy |
| **6 · Reliability** | Worker supervisor + backoff (H4), `Mute()` race (H5), error handling, remaining audit items | Med | Yes |

**Ordering note:** the data layer (3) precedes auth (4) deliberately — auth needs the `user_id` shape to exist first.

## Key technical decisions

- **Auth:** single-user gate (bearer token / simple login) enforced on all `/api/*` and the WS handshake; structured so a provider (Clerk on Vercel) drops in for real multi-user later.
- **Data model:** `owner`/`user_id` added to memory, anchors, sessions from the start (multi-user-ready), even though only one user exists now.
- **Deploy topology:** Railway services for the Go server + Python FastAPI (+ NATS); Vercel for the frontend; secrets via platform env; `wss`/https end-to-end.
- **Project agents:** one `.claude/agents/*.md` per subsystem so context isn't lost when searching/fixing/building.
- **Config:** `AGENTS.md` is the canonical cross-tool ruleset; `.cursorrules`/`.windsurfrules`/`GEMINI.md` are symlinks to it; `CLAUDE.md` remains the richer Claude-specific context.

## Risks & mitigations

- **High-risk phases (3, 4, 6) touch runtime** → strict TDD, CI green gate before merge, phased/feature-flagged where possible.
- **Deletions** are done via `git rm` (recoverable from history), never destructive shredding.
- **Runtime assets preserved:** `SOUL.md` stays at root; moved docs had their references updated.

## Verification strategy

Every phase must pass the relevant gates in CI before merge:
- Backend: `go build ./... && go vet ./... && go test ./...`; `ruff check . && mypy app tests && pytest`.
- Frontend: `npm run lint && npm run type-check && npm run build && npm test`.
- User-facing phases (auth, deploy): manual walk-through + Playwright re-verify, then a real deploy smoke test.
