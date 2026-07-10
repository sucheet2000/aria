# Phase 6 — Reliability (implementation plan)

**Goal:** Close the reliability/concurrency findings from the codebase audit that are
*still open* after Phases 0–5, using three parallel, conflict-free worktrees.

**Approach:** Same flow as Phase 5 — one worktree per workstream (disjoint file
ownership so PRs never conflict), TDD, `go test -race` / ruff+mypy+pytest, self-merge
each green PR to `integration`, then promote `integration → main`.

**Scope discipline:** fix-safe / flag-risky. Risky items (dependency cleanup, behaviour
changes) are documented as follow-ups, not changed autonomously.

---

## What is already fixed (verified — excluded from Phase 6)

Confirmed by reading current code on `integration`, these audit findings are resolved:

- **hub.go CRITICAL data race** (map write under `RLock`) — `unregister` now uses `Lock()`;
  broadcast is read-only. Hub tests exist (`broadcast_test.go`, `websocket_test.go`).
- **Vision worker orphaned at shutdown** — `main.go` already calls both `audioWorker.Stop()`
  and `worker.Stop()`.
- **main.go `workDir` hardcoded** — already derived from `filepath.Dir(execPath)` with an
  `os.Getwd()` fallback.
- **schemas.py duplicate class definitions** — no duplicates remain (reorganised into
  `app/models/schemas.py` during the restructure).
- **Frontend cognition field mapping** (`useCognition.ts`) — correctly reads
  `natural_language_response` / `avatar_emotion` / `symbolic_inference` / `world_model_update`.
- **MemoryPanel port / localhost hardcoding** — fixed in Phase 5a (`config.ts`).
- **backend/memory/ gitignore** — `.gitignore` already covers it (but the file is still
  tracked — see 6c).

---

## Workstreams (disjoint file ownership)

### 6a — Go worker lifecycle & concurrency
Owns: `backend/internal/audio/worker.go`, `backend/internal/vision/*.go`,
`backend/cmd/server/main.go`, `backend/internal/server/server.go` (+ Go tests).

1. **H5 — Mute() data race.** `audio/worker.go` reads/writes `w.stdinPipe` in `Mute()`
   with no synchronisation while `run()` sets it to `nil` on exit. Add a mutex (mirror the
   vision worker's existing `stdinMu`); snapshot the pipe under lock in `Mute()` so there is
   no check-then-write-to-nil TOCTOU. Test with `-race` (concurrent Mute + restart).
2. **H4 — reader goroutines not joined before restart.** In vision (and audio) `run()`,
   the stdout/stderr scanner goroutines are not awaited before the loop restarts the
   subprocess, so two goroutines can briefly read overlapping streams. Join them with a
   `sync.WaitGroup` before `run()` returns. Test the restart path with `-race`.
3. **Vision worker hardcoded path (deploy blocker).** `vision/worker.go:105`
   `cmd.Dir = "/Users/sucheetboppana/aria/backend"` and the derived PYTHONPATH break on any
   other machine / in the container. Inject `workDir` into `vision.New(...)` (exactly like
   `audio.New`), using the `workDir` main.go already computes. Default unchanged locally.
4. **Readiness gate (first-request 500).** On startup the Go HTTP server accepts cognition
   before FastAPI is ready, so the first request 500s (connection refused). Poll Python
   `/health` with a bounded retry/timeout before serving; non-fatal (log and proceed after
   the timeout so startup never hangs).

### 6b — Go proxy robustness
Owns: `backend/internal/cognition/client.go`, `backend/internal/tts/client.go` (+ tests).

1. **Non-200 not checked.** The cognition client never inspects `httpResp.StatusCode`; a 422/500
   from Python surfaces as a confusing "decode cognition response" error. Check the status and
   return a meaningful error. Same for the tts client. Test with a stub 500.
2. **`suggestAvatarEmotion` covers 5 of 7 emotions.** `sad`, `angry`, `disgusted` fall through
   to `neutral`. Add keyword cases so all seven avatar emotions are reachable. Table test.

### 6c — Python robustness & hygiene
Owns: `backend/app/config.py`, `backend/app/main.py`, `backend/app/cognition/memory.py`,
`backend/app/api/routes.py`, `.gitignore`, and untracking `backend/memory/`.

1. **No `ANTHROPIC_API_KEY` validation.** Defaults to `""`; `AsyncAnthropic(api_key="")`
   initialises fine and fails only at call time. Validate at startup — warn loudly (and fail
   fast when a strict flag is set) so misconfig is obvious, without breaking key-less local runs.
2. **`query_relevant` on an empty collection is fragile.** Relies on an `except` swallowing a
   ChromaDB error. Add an explicit empty-collection guard that returns `[]` deterministically.
3. **`backend/memory/` is tracked despite being gitignored.** `git rm --cached -r backend/memory/`
   so the ChromaDB data (potential PII) stops being committed; `.gitignore` already covers it.
4. **(cheap, optional)** Add the missing tests the audit flagged: VAD `process_chunk`
   speech/silence, memory dedup + TTL expiry.

---

## Flagged — NOT changed autonomously (follow-ups for review)

- **requirements.txt conflicts/unused deps** — `silero-vad` (code uses `webrtcvad`),
  `openai-whisper` alongside `faster-whisper`, `langchain` imported nowhere. Touching pins
  risks CI pip-backtracking (see CLAUDE.md); needs a deliberate, tested change.
- **`--denoise` never passed to the audio worker** — DeepFilterNet is permanently off. Enabling
  it is a behaviour change (latency/quality) that should be benchmarked, not flipped silently.
- **`SymbolicStatePanel.tsx` missing** — a feature gap, not a reliability defect.
- **`.env.example` missing vars / no descriptions** — documentation debt.
- **Deploy gaps** (server-local vision/audio capture, `SOUL.md` outside the build context) —
  tracked in `docs/DEPLOY.md`; addressed at go-live.

---

## Execution
- Branches: `feat/phase-6a-worker-reliability`, `feat/phase-6b-proxy-robustness`,
  `feat/phase-6c-python-robustness`, from `origin/integration`.
- Per branch: green CI (`go test -race` / ruff+mypy+pytest) → self-merge to `integration`.
- After all three merge green → promote `integration → main`. No cloud go-live.
