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

## Open debt

| Rule | Item | Severity | Where | Target |
|------|------|----------|-------|--------|
| `SCALE-1` | Perception reads the **container's physical camera/mic** — the headline feature cannot run in the cloud; capture must move browser-side | critical | `backend/app/pipeline` vision/audio workers | **Phase A.2** (browser-side perception rewrite) |
| `DEP-2` | `webrtcvad` imported but **undeclared** — audio worker hard-exits(1) on any machine but the author's | high | audio worker + `requirements` | Phase E |
| `API-1` | Single-hand gestures silently dropped: frontend sends `gesture`, Python reads `hand_gesture` — contract drift across 4 hand-maintained copies | high | proto / Go / pydantic / TS | Phase E |
| `TEST-1` | Frontend **vitest suites never run in CI** — all 5 are non-gating | high | `.github/workflows/ci.yml` frontend job | **Phase B2** (gate `npm test`) |
| `OBS-1/2/3` | Production observability blind — `/metrics` unreachable through the edge, health check that can't fail, non-JSON logs | high | Go edge + Python | Phase E |
| `DEP-1` | Python dependency graph non-deterministic — ~18/28 unpinned, no lockfile, no hashes | high | `backend/requirements.txt` | Phase E |
| `SEC-1` | Clerk session JWT carried in the **WebSocket URL query string** (token leakage → account takeover) | medium | frontend WS URL + Go | Phase E |
| `REL-1` | Graceful shutdown broken — `cancel()` SIGKILLs workers before `Stop()`, then a hard 10s sleep | medium | Go server shutdown | Phase E |
| `FE-1/FE-2` | WCAG 2.1 AA failures (labels, contrast, focus, reduced-motion) plus **no error boundary** on any live rendered path | medium | `frontend/src` | Phase E |
| `DATA-5` | Unwired, unscoped **GraphMemory** subsystem shipped as latent risk (drop `networkx` if deleted) | medium | memory pipeline | Phase E |
| `ARCH-1/2/3` | Business logic (emotion) in the transport layer; duplicated `broadcastFrame` + 3 near-identical proxy handlers + `localhost:8000` in 3 files; 4 divergent emotion enums | low–med | Go + frontend | Phase E / v2 |

---

*Source: the July 2026 ultracode audit. Full findings in the audit artifact; this table is the
actionable subset mapped to rule IDs.*
