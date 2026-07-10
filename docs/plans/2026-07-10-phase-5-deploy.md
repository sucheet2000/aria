# Phase 5 — Deploy Prep (containers + platform config + runbook)

**Goal:** Make ARIA deployable to real infrastructure — the backend to Railway,
the frontend to Vercel — by producing containers and platform config only. No
cloud API is called and nothing is deployed in this phase; the runbook is executed
by a human.

**Scope (config only, this phase):**

- `backend/Dockerfile` — multi-stage image: a Go builder, a Python builder (with a
  Rust toolchain to compile `deepfilterlib`), and a slim `python:3.13-slim` runtime
  that carries the built venv + the Go binary. `start.sh` runs uvicorn on
  `127.0.0.1:8000` in the background and execs the Go server on `$PORT`.
- `backend/.dockerignore` — excludes `.venv data __pycache__ *.db .env node_modules`
  (plus caches / `.git`).
- `backend/start.sh` — the two-process entrypoint.
- `docker-compose.yml` — rewritten to build the real Dockerfile, expose only the Go
  port, keep Python internal, and disable the (device-less) audio worker.
- `deploy/railway.json` + `deploy/README.md` — Railway backend config.
- `frontend/vercel.json` — Next.js build config (env is dashboard-managed).
- `docs/DEPLOY.md` — the go-live runbook and the full secret list.

**Out of scope (flagged in DEPLOY.md, not fixed here — they are app code):**
frontend hardcoded `localhost:8080` URLs, the vision worker's hardcoded macOS
`cmd.Dir`, server-local camera/mic capture in a device-less container, `SOUL.md`
living outside the build context, and enforcing the `X-Internal-Auth` header.

---

## The topology decision

**One backend image, two processes, one public port.**

The Go server is the public front door: it terminates the WebSocket, verifies
Clerk JWTs, rate-limits, and is the single auth boundary. It also *spawns* the
Python vision/audio workers and *proxies* cognition/TTS to the Python FastAPI
service. Because Go launches and talks to Python over loopback, the two cannot be
split into separate Railway services without re-plumbing that spawn/proxy path —
so they ship together in one container.

- Go binds `0.0.0.0:$PORT` (Railway requires a public bind on its injected `PORT`).
- Python (uvicorn) binds `127.0.0.1:8000` — **internal only, never mapped or routed
  publicly.**

**Why Python stays private (security invariant):** Python trusts the
`X-Aria-Owner` header that Go sets *after* verifying the token. If `:8000` were
reachable, anyone could forge that header and impersonate any user. So only the Go
port is exposed, and `INTERNAL_AUTH_SECRET` is set as defense-in-depth for the day
the `X-Internal-Auth` check is enforced.

**Why amd64 is pinned:** Railway runs linux/amd64. The Python stages pin
`--platform=linux/amd64` so the wheels (torch, mediapipe, onnxruntime, …) and the
compiled venv match the runtime, and the Go binary is cross-compiled `GOARCH=amd64`.

**Build gotcha handled:** `deepfilternet`'s `deepfilterlib` has no cp313 wheel and
compiles from Rust source. CI succeeds because GitHub runners ship Rust; the slim
image does not, so the Python builder stage installs a Rust toolchain, and the
final runtime stays slim (toolchain excluded).

## Verification

- `docker build -f backend/Dockerfile -t aria-backend-test backend` succeeds
  (heavy: ML deps + a Rust compile, several minutes).
- `docker compose config` and `vercel.json` validate.
