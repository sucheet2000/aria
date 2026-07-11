# ARIA Engineering Standards

Status: **binding**. Every change to ARIA must meet the bar below before it merges to `integration`.
Calibrated for a solo→small-team AI product going multi-user on Railway (backend) + Vercel
(frontend) with Clerk auth. These are checkable rules, not aspirations. If a rule cannot be met,
the PR description must say why and link a tracking issue — see "Rollout & ratchet" at the bottom.

Rule IDs (e.g. `DATA-1`) are stable; CI, hooks, and the PR checklist reference them. Pre-existing
violations are catalogued in [`STANDARDS_DEBT.md`](STANDARDS_DEBT.md) — that is the burn-down list,
not a blocker for unrelated work.

---

## 0. How to read this doc
- **MUST** = blocks merge. CI or review will reject.
- **SHOULD** = strongly expected; a reviewer may waive with a written reason in the PR.
- **Grandfathered** = pre-existing violations are tracked in `STANDARDS_DEBT.md`, not blocking, but
  no *new* violations may be added (the ratchet). New/changed code is held to the full bar.

The ten dimensions below map 1:1 to the audit. Each opens with the non-negotiables.

---

## 1. Security (`SEC`)
Baseline: OWASP ASVS L2 for anything reachable from the network.

- **SEC-1 (MUST)** No secret in a URL. Auth tokens (Clerk session JWT, internal auth secret)
  travel in headers or the WebSocket subprotocol/`Sec-WebSocket-Protocol` header or a
  first-message auth frame — never in a query string, path, or `?token=`. Grep gate:
  `token=` in any `.go`/`.ts`/`.tsx` WS-URL construction fails review.
- **SEC-2 (MUST)** Every process that trusts an internal header (`X-Aria-Owner`,
  `X-Internal-Auth`) MUST fail closed at startup: if `INTERNAL_AUTH_SECRET` is empty/unset and
  `ENV != "local"`, the process refuses to boot (log.Fatal / `raise SystemExit`). Mirror the Go
  edge guard in Python `app.main` lifespan. No fail-open trust boundary.
- **SEC-3 (MUST)** All cross-owner data access is `owner`/`user_id`-scoped at the query layer,
  never filtered in app code after a broad fetch. Every new store method takes `owner` as a
  required first argument. Never derive `owner` from a client-supplied body field — only from the
  verified Clerk `sub` (Go) or the validated `X-Aria-Owner` header (Python, behind SEC-2).
- **SEC-4 (MUST)** Clerk JWTs are verified against JWKS with issuer + `sub` present and
  expiry checked, on every request/connection — not once at connect and cached forever. WS
  connections re-check expiry on a timer or reject on the first authenticated message past `exp`.
- **SEC-5 (MUST)** No hardcoded API keys, no `backend/.env` committed. All secrets via env.
  `gitleaks` (pre-commit + CI) must pass. gRPC binds `127.0.0.1` only, never `0.0.0.0`.
- **SEC-6 (MUST)** Global mutable auth/state that any client can seize is forbidden in the
  multi-user runtime: `activeOwner`, global audio mute, and StreamRegistry cancellation are
  per-owner keyed. A frame from owner A can never cancel/mute owner B.
- **SEC-7 (SHOULD)** Untrusted text that reaches the LLM (user speech, recalled memory facts) is
  delimited and trust-labeled in the prompt so it cannot override SOUL.md. Memory writes derived
  from model output are marked lower-trust than SOUL.md.
- **SEC-8 (MUST)** Request bodies are size-capped (existing 64KB WS cap stays); all POST bodies
  validated by a pydantic model before use. Rate limits (per-caller + global) stay in place.
- **SEC-9 (MUST)** `gosec` (Go), `bandit` (Python), `npm audit`/`govulncheck`/`pip-audit`
  (deps) run in CI. No new High/Critical findings introduced by the PR.

## 2. Scalability & runtime topology (`SCALE`)
The data model is multi-user-ready; the runtime must not silently assume single-machine.

- **SCALE-1 (MUST)** No server-side capture of physical devices for per-user media.
  `cv2.VideoCapture(<int>)` and `sounddevice` input streams are forbidden in any code path that
  runs in the cloud image. Per-user camera/mic capture happens in the browser (getUserMedia →
  frames/audio over the WS/gRPC path); the server does inference only. New use of a local device
  index fails review.
- **SCALE-2 (MUST)** No new in-process singleton that holds per-user state and would break at
  `numReplicas > 1` without a written note. If a store/hub/worker is inherently single-writer,
  its constraint is documented in the module docstring and the PR.
- **SCALE-3 (SHOULD)** Any new durable state goes to an external/managed store (Postgres/pgvector)
  or an env-configured mounted volume path (`DATA_DIR`) — never an implicit local dir. See DATA-1.
- **SCALE-4 (SHOULD)** List/query endpoints are paginated and bounded (see API-5). No unbounded
  full-collection scans on a hot path.

## 3. Reliability (`REL`)
- **REL-1 (MUST)** Graceful shutdown is real: on SIGTERM the server drains in-flight work, then
  stops workers via their Stop()/SIGTERM handler (not a blanket `cancel()`/SIGKILL first),
  bounds `GracefulStop` with a timeout, and does not use a fixed unconditional `sleep`. Total
  shutdown must complete inside Railway's grace window (default 10s minus margin, so budget ≤8s).
- **REL-2 (MUST)** Every outbound call to a third party (Anthropic, ElevenLabs) has a
  service-side timeout AND bounded retry-with-backoff on transient (429/5xx) errors. No call
  relies solely on the caller's timeout. Guard array indexing on model responses
  (`response.content[0]`) against empty completions.
- **REL-3 (MUST)** Long-running loops (the hub, worker supervisors) honor context cancellation
  (`ctx.Done()`) and exit promptly. No goroutine/loop that ignores its cancel signal.
- **REL-4 (MUST)** Partial-write fallbacks cannot corrupt output: the TTS fallback path must not
  emit audio after a partial primary write. Write-then-swap or buffer-then-commit.
- **REL-5 (SHOULD)** Blocking I/O (Chroma, SQLite, disk) stays off the async event loop
  (`run_in_executor`/threadpool). Shared mutable state stays mutex-guarded (keep the current
  discipline). `go test -race` stays green.

## 4. Data & persistence (`DATA`)
The audit's most severe dimension. These are hard blockers for cloud.

- **DATA-1 (MUST)** No durable state on the ephemeral container FS. Every persistence path
  (ChromaDB dir, SQLite files) is read from the `DATA_DIR` setting (shipped in A.1) that defaults
  to a local dev path (`backend/`) but is set to the mounted Railway volume (`/data`) in
  production. Hardcoded `/app/memory`, `./data`, etc. fail review. A volume attached without
  env-driven paths is not a fix — both are required together.
  *Status: the ChromaDB memory dir and the SQLite anchors DB are `DATA_DIR`-driven as of A.1; any
  new durable store must follow the same pattern.*
- **DATA-2 (MUST)** Schema/collection changes ship with a migration (versioned, forward-only) and
  a rollback note. No implicit boot-time "migrate the whole collection" that can OOM under load.
- **DATA-3 (MUST)** Retention that is advertised is enforced by deletion, not read-time filtering.
  The episodic 30-day TTL runs a real deletion sweep. No collection grows unbounded; PII is not
  retained past its stated window (GDPR/CCPA).
- **DATA-4 (MUST)** Backup/restore path exists and is documented before any real user data lands
  (Litestream for SQLite, or managed-DB snapshots). A redeploy must never be the only "backup."
- **DATA-5 (MUST)** Dead/unwired stores are not shipped. The unwired, unscoped GraphMemory
  subsystem is either wired with owner-scoping + tests or deleted — not left as latent risk.
- **DATA-6 (MUST)** Every store row/document is owner-scoped at write and read (keep the current
  bright spot; extend it to any new store).

## 5. Testing (`TEST`)
- **TEST-1 (MUST)** All four suites gate merge in CI: Python pytest, Go `-race` test, frontend
  `npm test` (vitest), plus lint/type-check. The frontend `npm test` step MUST run and MUST be
  gating (this is currently missing — see CI gates).
- **TEST-2 (MUST)** New code ships with tests in the same PR (TDD: red→green→refactor). New
  branch logic without a covering test fails review.
- **TEST-3 (MUST)** The two highest-risk paths have direct tests: the Clerk JWT verifier
  (valid/expired/wrong-issuer/missing-sub/forged) and the LLM response parser + Claude call path
  (well-formed, malformed, empty completion, upstream 429/5xx → retry).
- **TEST-4 (SHOULD)** At least one integration test crosses the real trust boundary end-to-end:
  WS→gRPC→interrupt, and the `X-Aria-Owner`/`X-Internal-Auth` Go→Python hop with a wrong/absent
  secret rejected. Neighbors are not both mocked.
- **TEST-5 (SHOULD)** Coverage is measured and reported per suite (pytest-cov, `go test -cover`,
  vitest coverage). New code SHOULD land ≥70% line coverage; the number ratchets up, never down.
- **TEST-6 (MUST)** No test is skipped or deleted to make CI green. Fix or flag with an issue.

## 6. Frontend (`FE`)
Baseline: WCAG 2.1 AA on all interactive, rendered surfaces.

- **FE-1 (MUST)** Every interactive control has an accessible name (icon-only buttons get
  `aria-label`). Body text meets ≥4.5:1 contrast (≥3:1 for large text). Visible keyboard focus on
  all focusable elements. `prefers-reduced-motion` is honored by every animation.
  `eslint-plugin-jsx-a11y` (error level) gates.
- **FE-2 (MUST)** An error boundary wraps every live rendered path — especially the WebGL
  `<Canvas>` — so a WebGL context loss or a thrown render cannot white-screen the app. The
  boundary must wrap *live* code, not dead code.
- **FE-3 (MUST)** The WebSocket message boundary is typed and validated (zod or a discriminated
  union + runtime guard). A malformed frame is dropped/logged, never allowed to poison the store
  or crash cognition. No `any` at the WS boundary.
- **FE-4 (MUST)** `NEXT_PUBLIC_API_BASE` (and any required public env) fails loudly at startup in
  production if unset — no silent `localhost:8000` fallback shipped to Vercel. No hostname
  hardcoded in more than one place; use one config module.
- **FE-5 (SHOULD)** Effects do not tear down and recreate expensive resources (the avatar render
  loop) on unrelated store changes. Render loops are created once; store values feed them via refs.
- **FE-6 (MUST)** No `any` in app code (keep). Zustand access via selectors. `npm run lint`,
  `type-check`, and `test` all pass.

## 7. Dependencies (`DEP`)
- **DEP-1 (MUST)** Python deps are fully pinned with a lockfile + hashes (uv or pip-tools →
  `requirements.txt` compiled from `requirements.in`, with `--generate-hashes`). No unpinned
  package (`numpy`, `fastapi`, `pydantic`, `uvicorn`, etc.) reaches `main`/`integration`. A
  Railway rebuild must be byte-reproducible.
- **DEP-2 (MUST)** Every module the code imports is declared in the lockfile — including
  `webrtcvad` (audio worker hard-exits without it), and any coremltools/openai-whisper that a
  runtime path imports. CI's "import smoke" step (import the worker entrypoints) must pass on a
  clean image. No package is "hand-installed in the author's venv."
- **DEP-3 (MUST)** No declared-but-unused heavy dep (remove `networkx` if GraphMemory is deleted).
  `CLAUDE.md`'s dependency claims must match reality.
- **DEP-4 (MUST)** Go (`go.mod`+`go.sum`) and frontend (exact pins + committed
  `package-lock.json`) stay locked. `npm ci`, never `npm install`, in CI.
- **DEP-5 (MUST)** `pip-audit`, `npm audit --audit-level=high`, and `govulncheck` run in CI; no
  new High/Critical. `setuptools>=78.1.1` floor stays.

## 8. Observability (`OBS`)
- **OBS-1 (MUST)** Logs are structured JSON in production (zerolog/structlog JSON renderer),
  keyed for aggregation. No human-only formatted logs on the prod path.
- **OBS-2 (MUST)** Health checks actually check dependencies. `/health` (liveness) may be cheap,
  but a `/ready` (readiness) probe MUST verify the Python service, the DB/volume, and return
  non-200 when a dependency is down. A static `"ok"` string is not a readiness probe.
- **OBS-3 (MUST)** `/metrics` is reachable through the public Go edge (proxied), not
  loopback-only. Metrics include request count, error rate, and latency percentiles (p50/p95/p99)
  — not just a reset-on-restart mean. Claude/ElevenLabs token/character spend is counted.
- **OBS-4 (MUST)** A correlation/request ID is generated at the Go edge and propagated through
  Go→Python→Claude and into every log line, so one request is traceable across services.
- **OBS-5 (MUST)** The cognition route (and every route) has an exception handler that logs +
  increments an error metric; no unhandled 500 leaves the service silent.

## 9. API & contracts (`API`)
- **API-1 (MUST)** Cross-service message contracts have ONE source of truth. Fields shared across
  proto/Go/pydantic/TS are generated or validated against a shared schema — not hand-copied into
  four places. Adding a field to one side without the others fails review. (The `gesture` vs
  `hand_gesture` drift is the canonical bug this prevents.)
- **API-2 (MUST)** The live HTTP+WS contract is versioned (`/v1/...` or a version field) so a
  split Vercel/Railway deploy can detect a mismatch instead of silently dropping fields.
- **API-3 (MUST)** One error envelope across all endpoints (`{error: {code, message, request_id}}`).
  No three different shapes.
- **API-4 (MUST)** Side-effecting POSTs that the frontend auto-retries (the 15s retry path) accept
  an idempotency key and de-duplicate. No duplicate anchor/write on retry.
- **API-5 (MUST)** List endpoints are paginated with a bounded default page size. No unbounded
  list response.
- **API-6 (MUST)** FastAPI routes declare a `response_model` (typed pydantic out), so responses
  are schema-validated and OpenAPI is generated. No raw untyped `dict` responses on new routes.

## 10. Architecture & cleanliness (`ARCH`)
- **ARCH-1 (MUST)** Business logic does not live in the transport layer. Emotion classification and
  similar logic move out of the Go WS/proxy layer into a service/domain package (or Python).
- **ARCH-2 (MUST)** No copy-pasted logic across packages (the duplicated `broadcastFrame`, the
  three near-identical proxy handlers, `localhost:8000` in three files). Extract once; import.
- **ARCH-3 (MUST)** One canonical enum for a shared vocabulary (the emotion enum has four
  divergent definitions with unrenderable values — collapse to one, generated/shared).
- **ARCH-4 (SHOULD)** No god components/files. `Avatar3D` (460-LOC, hardcoded geometry) is flagged
  for component-level decomposition; no new 400+ LOC single-responsibility-violating file.
- **ARCH-5 (MUST)** No dead/unwired subsystem merged as "future." Wire it with tests, or leave it
  out. No new TODO/FIXME debt without a linked issue.

---

## Definition of Done (every PR)
A change is done only when ALL of these hold (see the CLAUDE.md checklist for the paste-ready list):
1. Tests written first, all four suites green locally (`make check`).
2. No new violation of any MUST rule above; grandfathered items untouched or improved.
3. Secrets/paths env-driven (SEC-5, DATA-1, FE-4); fail-closed guards intact (SEC-2).
4. Owner-scoping preserved on any data path (SEC-3, DATA-6).
5. New deps pinned+hashed+declared+audited (DEP-1..5).
6. Structured logs + a metric + request-id on any new route (OBS-1,3,4,5).
7. Contract changes made in one source of truth, versioned (API-1,2).
8. Commit message shown in plain English and approved before commit.

## Rollout & ratchet
These standards are enforced as a **ratchet**, not a big-bang gate. New code meets the full bar;
pre-existing violations are catalogued in [`STANDARDS_DEBT.md`](STANDARDS_DEBT.md) and burned down,
not used to block unrelated work. In CI, new scanners (gosec, bandit, pip-audit, govulncheck, npm
audit, gitleaks, jsx-a11y, import-smoke, contract-drift) start **report-only** and flip to
**gating** per rule ID as each debt item is cleared. When a debt item is fixed, delete its row from
`STANDARDS_DEBT.md` and flip its CI check to gating in the same PR.
