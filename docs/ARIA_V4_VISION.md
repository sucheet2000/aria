# ARIA v4 — Autonomous Agent Vision

## What v4 Is
ARIA v4 is a voice-first autonomous agent that deploys itself across
your MacBook to build things. You speak the intent, ARIA handles the
execution. No typing required.

## The Jarvis Analogy
Like Jarvis, ARIA v4 can:
- Receive a spoken task ("build me a REST API for this")
- Spin up Claude Code autonomously
- Write files, run tests, fix errors, commit code
- Report back via voice when done

## Architecture (gitagent-based)

ARIA v4 is a gitagent with a voice interface on top.
The repo structure:

  aria/
  ├── agent.yaml              # ARIA manifest — name, version, skills
  ├── SOUL.md                 # Already exists — voice companion identity
  ├── agents/
  │   ├── code-builder/       # Writes code, runs tests, fixes errors
  │   │   ├── agent.yaml
  │   │   ├── SOUL.md
  │   │   └── DUTIES.md       # Cannot approve its own work
  │   ├── file-manager/       # Manages files and directories
  │   ├── researcher/         # Fetches docs, reads context, searches
  │   └── reviewer/           # Reviews code-builder's output
  │       └── DUTIES.md       # Cannot be same agent as code-builder
  ├── skills/
  │   ├── voice-pipeline/     # STT, wake word, TTS — from v1
  │   ├── gesture-input/      # Hand tracking — from v2 Week 8
  │   └── code-review/        # Wraps /codex:review
  ├── memory/
  │   └── runtime/            # Live session state
  ├── workflows/
  │   ├── build-feature.yaml  # "Build me X" → deterministic pipeline
  │   ├── fix-bug.yaml        # "Fix this" → investigate → patch → test
  │   └── review-code.yaml    # Pre-commit review gate
  └── compliance/
      └── DUTIES.md           # code-builder cannot approve own work

## Segregation of Duties
code-builder and reviewer are separate agents with a conflict matrix.
ARIA cannot approve its own code — prevents autonomous self-modification
without a review step.

## Token Efficiency (from ruflo architecture)
- Simple commands handled locally — no LLM call
- Medium tasks routed to Claude Haiku
- Complex architecture decisions use Claude Sonnet/Opus
- TurboQuant KV compression on any local models (from Week 4)

## The Voice Layer
v4 builds directly on v2's perception pipeline:
- Wake word triggers task intake
- Whisper STT captures the task
- ARIA confirms understanding before executing
- Progress updates via TTS ("Running tests... 2 of 5 passing")
- Completion reported via voice

## What Needs to Be Built First (Prerequisites)
- v2 complete (Weeks 1-9) — perception foundation
- v3 spatial canvas (optional but ideal)
- gitagent structure scaffolded in repo (agent.yaml + agents/)
- Codex plugin already installed ✓

## Version Progression
v1 — Voice companion (COMPLETE)
v2 — Smarter companion (IN PROGRESS — Weeks 1-9)
v3 — Spatial environment (TouchDesigner-inspired, multi-display)
v4 — Autonomous agent (THIS DOCUMENT)
