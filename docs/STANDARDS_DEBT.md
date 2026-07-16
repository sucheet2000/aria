# ARIA Standards Debt (grandfathered violations)

This is the burn-down list for [`STANDARDS.md`](STANDARDS.md). Every row is a **pre-existing**
violation the July 2026 audit found. These are **tracked, not blocking** — new/changed code is held
to the full bar, but unrelated work is not blocked by old debt (the ratchet).

**How this file works**
- When you fix a debt item, delete its row *and* flip its CI check from report-only to gating in the
  same PR.
- Do not add new rows for *new* code — a new MUST violation blocks the merge instead of landing here.
- Severity mirrors the audit (critical → high → medium). Overall audit readiness at capture: **4/10**.

Dimension scores at capture (0–10): security 6 · reliability 6 · cleanliness 6.5 · testing 5 ·
architecture 5 · frontend 4.5 · dependencies 3.5 · api 3.5 · observability 3 · scalability 2.5 ·
**data 2**.

---

## Resolved (kept here briefly for traceability, then delete)

| Rule | Item | Resolved by |
|------|------|-------------|
| `DATA-1` | Ephemeral FS wiped all memory + anchors on every redeploy; persist paths hardcoded to `/app`, no volume env var | **A.1** — `DATA_DIR` setting; ChromaDB + SQLite anchors write to the Railway volume at `/data`; verified live on prod (commit `38afeb6`) |
| `SEC-2` | Go→Python trust boundary was **fail-open** — no production startup guard on the Python side | **SEC-2 PR** — `validate_internal_auth` in `app.main` lifespan fails closed when `INTERNAL_AUTH_SECRET` is empty and `ENV != "local"` |
| `REL-2` | Anthropic cognition call had **no timeout or retry**; `response.content[0]` unguarded against empty completions | **REL-2 PR** — `AsyncAnthropic` wired with config-driven `timeout`/`max_retries` (SDK backoff on 429/5xx); empty/non-text completion now returns a safe fallback instead of `IndexError` |
| `DATA-3` | Episodic **30-day TTL never enforced** — unbounded growth, PII retained forever | **DATA-3 PR** — `MemoryStore.sweep_expired` deletes episodic docs where `expires_at < now`; runs on `load()`, throttled (`SWEEP_INTERVAL_SECONDS`) on the episodic write path; read-time filter kept as defense-in-depth |
| `TEST-1` | Frontend vitest suites never ran in CI — all 5 non-gating | **B2** (#60) — `npm test` (vitest) is now a gating CI step |
| `DATA-5` | Unwired, unscoped GraphMemory subsystem shipped as latent risk | **#70** — deleted (proven dead: referenced only by its own test); dropped the `networkx` dep |
| `REL-1` | Graceful shutdown mis-ordered — `cancel()`/SIGKILL before `Stop()`, then an unconditional 10s sleep | **#71** — ordered drain bounded to 8s: HTTP listener close → worker `Stop()` → gRPC `GracefulStop` w/ hard fallback → `cancel()` last; no fixed sleep |
| `API-1` | Single-hand gestures dropped: frontend/Go send `gesture`, Python read `hand_gesture` | **#74** — renamed pydantic field to `gesture` (one canonical name); frontend/Go were already correct |
| `OBS-1/2/3/4/5` | Production observability blind — non-JSON logs, no request correlation, `/metrics` not through the edge, no failing readiness, unhandled 500s silent | **#75 + #76** — structlog/zerolog JSON on prod; `X-Request-ID` generated at the Go edge + forwarded + bound into Python logs; public `/ready` (Go pings Python + worker probes) + `/metrics` proxied through the edge; global error handler logs + increments an error metric |
| `DEP-1` | Python deps non-deterministic — ~18/28 unpinned | **#79** — all direct deps pinned exact. *(Hash-locking deferred: needs a Linux-side lock step; can't generate Linux wheel hashes from macOS dev.)* |
| `DEP-2` | `webrtcvad` imported but undeclared — audio worker hard-exits on a clean machine | **#79** — declared (`==2.0.10`, with `setuptools==80.10.2` so `pkg_resources` stays); CI import-smoke flipped from report-only to **gating** |
| `SEC-1` | Clerk session JWT carried in the WebSocket URL query string (leakage) | **#83** — token moved to the `Sec-WebSocket-Protocol` subprotocol; server echoes only the `aria-ws` marker; a `?token=` URL is now rejected. *(Prod promotion held for a live signed-in WS check.)* |
| `FE-1` | WCAG 2.1 AA: contrast + labels/focus/reduced-motion + no error boundary | **#69 + #82** — error boundary on the live Canvas; icon labels, visible focus, reduced-motion; faint-text contrast raised to AA (`#4a4957→#828193`, 2.1:1→5.06:1) |
| `SCALE-1` | Perception read the container's physical camera/mic — dead in the cloud, un-multi-tenant | **A.2 (#85, #86, #87, #89)** — vision (MediaPipe) + mic capture moved **browser-side**; server vision worker + dead gRPC/NATS transports deleted; server `/ws/audio` feeds the existing STT pipeline (STT stays server). *(Prod-held for a live camera+mic test + a MediaPipe binary-provisioning choice.)* |
| `ARCH-1/2/3` | Emotion logic in the transport layer; duplicated `broadcastFrame` + 3 near-identical proxy handlers + `localhost:8000` in 3 places | **A.2a-2 + #88** — broadcastFrame/vision dup deleted with the dead transports; emotion classification went with the vision path; one `PythonBaseURL` config + a shared `proxyToPython` helper. *(ARCH-3, the 4-way emotion enum, left as a small follow-up.)* |

## Open debt

_All audit findings are addressed._ Two items are **code-complete on `integration` but held from prod** pending your action:

| Item | What's needed |
|------|----------------|
| `SCALE-1` (A.2) | A **live camera+mic test** (headless CI can't exercise the real pipeline) + a **MediaPipe binary-provisioning** choice (git-lfs / build-step / asset host) before it promotes to prod. |
| `SEC-1` | A **live signed-in WS check** before its prod promotion. |

Deferred/known gaps (none block current prod): dependency **hash-locking** (needs a Linux CI lock step), a formal **backup/restore** path (DATA-4), **end-to-end tests**, `ARCH-3` (emotion-enum consolidation), and orphaned tooling (`scripts/benchmark_nats.py`).

---

*Source: the July 2026 ultracode audit. Full findings in the audit artifact; this table is the
actionable subset mapped to rule IDs.*
