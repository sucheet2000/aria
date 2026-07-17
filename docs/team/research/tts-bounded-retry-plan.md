# Build Plan — tts-bounded-retry

Closes the ElevenLabs half of REL-2: bounded retry + backoff on the single
ElevenLabs POST in `tts_route.py`, mirroring the Anthropic SDK retry pattern.

- **Base branch:** `integration`
- **Specialist (all files):** `aria-python-pipeline`
- **Dependencies added:** NONE (hand-rolled `asyncio.sleep` backoff over the
  already-pinned `httpx==0.28.1`; brief's contract list is empty).

## Hard design constraints baked into this plan
1. **Fits inside the 15 s frontend abort.** `useTTS.ts:54` uses
   `AbortSignal.timeout(15000)`. The retry loop enforces a hard
   `_RETRY_BUDGET_SECONDS = 14.0` deadline: it never *starts* an attempt or a
   backoff sleep that would push total server time past 14 s, so the browser
   never aborts mid-retry.
2. **Money-path safety.** Retry ONLY on `429` or `>= 500`. NEVER on `402` or any
   other 4xx. Cap = `ELEVENLABS_MAX_RETRIES` (default 2 → 3 attempts max). Honor
   `Retry-After` but clamp it to the remaining budget (a large `Retry-After`
   simply means "don't retry", not "hang").
3. **Byte-for-byte preservation.** The `402 → 503` browser-fallback short-circuit
   and the `voice_engine.build_request_payload(..., emotion=req.emotion,
   use_turbo=True)` call (PR #126) are untouched and pinned by tests.

## Files (TDD — test file written first)

| # | File | Owner | Change (one line) |
|---|------|-------|-------------------|
| 1 | `backend/tests/test_tts_route.py` **(new)** | aria-python-pipeline | Red-first suite (list below); mocks `app.api.tts_route.httpx.AsyncClient` with sequenced `httpx.Response` objects via `fastapi.testclient.TestClient` — no new dep. |
| 2 | `backend/app/config.py` | aria-python-pipeline | Add `ELEVENLABS_TIMEOUT_SECONDS: float = 4.0` and `ELEVENLABS_MAX_RETRIES: int = 2`, directly after the Anthropic settings (config.py:29-31). |
| 3 | `backend/app/api/tts_route.py` | aria-python-pipeline | Wrap the `client.post(...)` (tts_route.py:44-46) in a bounded retry loop with capped backoff + budget deadline; add module constants; preserve 402→503 and the exception→500 path unchanged. |

## Retry loop shape (file 3)
Module constants: `_BACKOFF_BASE_SECONDS = 0.5`, `_BACKOFF_MAX_SECONDS = 2.0`,
`_RETRY_BUDGET_SECONDS = 14.0`.

- Create `httpx.AsyncClient(timeout=settings.ELEVENLABS_TIMEOUT_SECONDS)` **once**
  (reused across attempts); record `start = time.monotonic()`.
- Loop `attempt` in `range(settings.ELEVENLABS_MAX_RETRIES + 1)`:
  - `200` → return audio `Response(content=resp.content, media_type="audio/mpeg")`.
  - `402` → existing warn log + `Response(status_code=503, content=b"")`; no retry.
  - `429` or `>= 500`, and attempts + budget remain → backoff =
    `Retry-After` (if present/parseable) else
    `min(_BACKOFF_BASE * 2**attempt, _BACKOFF_MAX)`; **budget guard**: skip the
    retry if `elapsed + backoff + per-attempt-timeout > _RETRY_BUDGET`, returning
    the last status instead; else `await asyncio.sleep(backoff)` and continue.
  - Any other status (non-402 4xx), or retryable-but-exhausted/over-budget →
    existing error log + `Response(status_code=resp.status_code)`.
- `except Exception` → `Response(status_code=500)` (unchanged).

Worst case: 3 × 4 s timeouts + (0.5 + 1.0) s backoff = 13.5 s < 14 s < 15 s.

## Red-first test list (file 1)
1. `test_tts_success_first_try_single_call` — 200 first try → exactly **1** POST, audio/mpeg body.
2. `test_tts_429_then_200_succeeds` — `[429, 200]` → 2 POSTs, returns 200 audio.
3. `test_tts_5xx_exhausts_returns_last_status` — `[500,500,500]` → 3 POSTs (max), returns **last** 500.
4. `test_tts_402_returns_503_zero_retries` — `[402]` → exactly 1 POST, 503, empty body (pins fallback).
5. `test_tts_non_402_4xx_no_retry` — `[400]` → exactly 1 POST, returns 400 (retry ONLY on 429/5xx).
6. `test_tts_retry_after_header_honored_within_budget` — `[429 Retry-After:1, 200]` → sleeps ~1 s (patched), 2 POSTs, 200.
7. `test_tts_worst_case_budget_under_frontend_abort` — exhaust-5xx with `asyncio.sleep` patched to accumulate; assert `total_slept + ELEVENLABS_TIMEOUT_SECONDS * attempts < 15.0` and static `_RETRY_BUDGET_SECONDS < 15.0`.
8. `test_tts_emotion_payload_passed_through` — patch `voice_engine.build_request_payload`; assert called once with `text=req.text, voice_id=VOICE_ID, emotion=req.emotion, use_turbo=True` (pins PR #126).
9. `test_tts_missing_api_key_returns_503` — `ELEVENLABS_API_KEY=""` → 503, **zero** POSTs (existing behavior).

## Definition of Done (paste into PR)
```
- [ ] Tests written first; `make check` green (pytest + go -race + vitest + lint + type-check)
- [ ] No new MUST-rule violation (docs/STANDARDS.md); grandfathered items untouched
- [ ] Secrets & persist paths env-driven; fail-closed guards intact (SEC-2, DATA-1, FE-4)
- [ ] Owner-scoping preserved on all data paths (SEC-3, DATA-6)
- [ ] New deps pinned + hashed + declared + audited (DEP-1..5)  — N/A, zero new deps
- [ ] New routes: structured JSON log + error metric + request-id + response_model (OBS/API)  — no new route
- [ ] Contract changes in one source of truth, versioned (API-1, API-2)  — N/A, API unchanged
- [ ] a11y checked on any UI change (FE-1)  — N/A, no UI change
- [ ] Commit message shown in plain English and approved before commit
```

## Standards note
Advances REL-2 (the target). No MUST-rule violation introduced: `xi-api-key`
stays in the header (SEC-1), no new inbound surface, no persistence, no contract
change, no new dependency. Scoping decision to flag: retries fire on `429/5xx`
**status codes only** — a per-attempt timeout/connection error still returns 500
without retry (matches the brief's "retry ONLY on 429 and 5xx" literally and
keeps the diff minimal).

## File-overlap verdict
tts-bounded-retry file set `{tts_route.py, config.py, test_tts_route.py}` is
**disjoint** from all three sibling builds — no serialization required:
- **A2 token-cache-observability** → `{llm.py, test_llm_routing.py, test_metrics.py}`. Confirmed A2's frozen scope is the `llm.py` cognition site ONLY; it explicitly does not touch `tts_route.py` or `config.py`. The researcher's flagged "A2 might emit a TTS metric in tts_route.py" is NOT in A2's scope. ∅ intersection.
- **ws-frame-validation** → all `frontend/`. ∅ intersection.
- **episodic-recall-panel** → `{server.go, proxy_test.go, page.tsx, EpisodicPanel.tsx}` (and is recommended PARK). ∅ intersection.
