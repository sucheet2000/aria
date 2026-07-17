# Research brief — Bounded retry + backoff on the ElevenLabs TTS call

## Idea
- **Title:** Bounded retry + backoff on the ElevenLabs TTS call
- **Tag:** engineering
- **Pitch:** Wrap the single ElevenLabs POST in `tts_route.py` with a bounded
  retry-with-backoff on transient 429 / 5xx responses, while keeping the
  existing 402 handling and the browser-voice fallback exactly as they are.
  This closes the half of the REL-2 standard that was left open when only the
  Anthropic cognition call got hardened.

## Fit
**What exists today**
- The only place ARIA actually calls ElevenLabs is
  `backend/app/api/tts_route.py:44-46`: a single `httpx.AsyncClient(timeout=10.0)`
  `client.post(...)` with **no retry**. On any non-200 it returns immediately
  (402 → 503 so the browser falls back; other non-200 → passthrough status;
  exception → 500).
- The emotion-matched voice (PR #126) feeds this route through
  `voice_engine.build_request_payload(..., emotion=req.emotion, use_turbo=True)`
  at `tts_route.py:31-36`. Any change must preserve that call untouched.
- The reference pattern already in the repo is the Anthropic fix:
  `backend/app/cognition/llm.py:96-106` wires `AsyncAnthropic(timeout=..., max_retries=...)`
  from `settings.ANTHROPIC_TIMEOUT_SECONDS` / `ANTHROPIC_MAX_RETRIES`
  (`backend/app/config.py:28-31`). We mirror that shape for ElevenLabs.
- Callers / blast radius:
  - `frontend/src/hooks/useTTS.ts:47-55` calls `POST /api/tts` directly with a
    **15 s** `AbortSignal.timeout` and falls back to browser `speechSynthesis`
    on any failure. This is the live production path.
  - The Go client `backend/internal/tts/client.go:75-111` is a *proxy* to the
    same Python `/api/tts` (30 s timeout, `say` fallback) — it does **not** call
    ElevenLabs itself, so fixing retry in `tts_route.py` covers both callers.
- `docs/STANDARDS_DEBT.md:25` records REL-2 as "Resolved by" the Anthropic PR
  only. REL-2 (`docs/STANDARDS.md:76-79`) is a MUST that names **both** Anthropic
  and ElevenLabs, so the ElevenLabs half is a live, uncovered MUST gap — not a
  grandfathered one.

**What changes**
- `backend/app/api/tts_route.py` — wrap the POST in a bounded retry loop:
  retry only on 429 and 5xx, honor a `Retry-After` header when present,
  exponential backoff with jitter, cap attempts. 402 must still short-circuit
  to 503 (browser fallback); 4xx other than 429 must **not** retry.
- `backend/app/config.py` — add `ELEVENLABS_TIMEOUT_SECONDS` and
  `ELEVENLABS_MAX_RETRIES` mirroring the Anthropic settings.
- `backend/tests/` — new test file (none exists today; grep found no
  `tts_route` test) covering: 429-then-200 succeeds, 5xx exhausts and returns
  the last status, 402 returns 503 with **zero** retries, 200 first-try makes
  one call, and the total retry budget fits inside the frontend abort window.

## Prior art
- **httpx built-in retries do not help here.** The `retries=` param on
  httpx's transport only retries connection errors (`ConnectError`/`ConnectTimeout`),
  never HTTP status codes like 429/5xx. The httpx docs explicitly point you at
  a general-purpose retry tool or an application-level wrapper for status-code
  retries. So retry must be hand-rolled or added as a library.
- **ElevenLabs transient errors** are 429 (`too_many_concurrent_requests` or
  `system_busy` — very common on lower tiers under concurrency) and 5xx, and
  responses may carry a `Retry-After`. ElevenLabs' own guidance is to back off
  with jitter rather than retry immediately. This validates the design.
- **In-repo reference:** the Anthropic SDK's `max_retries` (already merged) is
  the pattern to imitate; we reproduce equivalent behavior over raw httpx.

## Dependencies
**None.** (This list is the build contract — the build may add nothing else.)

Rationale: the retry loop is ~15-25 lines of `asyncio.sleep` backoff over the
existing `httpx==0.28.1` (`backend/requirements.txt:17`). Candidate libraries
were considered and rejected to keep the diff minimal and honor ARIA's
dependency discipline (DEP-1..3, and CLAUDE.md "no unsolicited dependencies"):
- `tenacity` (Apache-2.0) — clean, but a new pinned+hashed+audited dep for ~15
  lines is not worth it.
- `httpx-retries` (MIT) — same objection; adds a transport layer for one call.
- ElevenLabs official Python SDK — heavy new dep, would rewrite the streaming
  call; CLAUDE.md warns against unpinned heavy deps / pip backtracking. Rejected.

If the build decides a library is genuinely needed, that is a scope/contract
change and must come back through research — it may not be added mid-build.

## Effort & risks
**Effort: S** — one route function, two config lines, one focused test file.
Slightly more than trivial only because the tests must mock httpx to simulate
429→200 and exhausted-5xx sequences and assert the no-retry-on-402 branch.

**Top risks**
1. **Retry budget vs. the 15 s frontend abort (the sharp one).** The live path
   is `useTTS.ts` with `AbortSignal.timeout(15000)`. Today each attempt gets
   10 s. Naive "keep 10 s per attempt + backoff" means a first attempt that
   hangs ~10 s then a retry pushes total server time past 15 s — the browser
   aborts mid-retry and falls back to browser TTS anyway, making the retry
   *pointless on the live path*. The plan MUST shrink the per-attempt timeout
   (≈4-6 s) and bound backoff so the whole budget fits inside ~14 s. If this is
   not done, the feature is theater for the browser caller.
2. **Money path / retry amplification.** ElevenLabs is paid and usage-metered.
   Retries must be capped (2-3) and must never fire on 402 (quota/payment) or
   other 4xx — only 429/5xx — or a persistent upstream fault becomes a cost
   multiplier. Honoring `Retry-After` avoids hammering.
3. **File overlap with A2 (observability), contra the idea's "no overlap"
   claim.** A2 is a backend observability build; a natural place to emit a
   TTS success/429/5xx metric is exactly these lines in `tts_route.py`. Both
   builds plausibly touch the same handler. Flag for the Lead to sequence or
   merge-coordinate; the "builds in parallel, distinct file" assumption is
   shaky.
4. **Regression on the emotion/402 paths (PR #126).** The wrap must leave
   `build_request_payload(emotion=...)` and the 402→503 fallback byte-for-byte
   intact. Tests must pin both.

## Security pre-check
*Threat-model note (aria-security-team Engagement-1 lens; produced inline —
this environment has no sub-agent spawn tool, so it was not run as a separate
`aria-security-team` process):*

New attack surface: none. Same `/api/tts` route, same ElevenLabs endpoint,
same auth. No new inbound surface, no new stored data. Data/PII: the request
`text` (ARIA's spoken reply) is already sent to ElevenLabs; a retry re-sends
the identical text — no new exposure, nothing persisted. Money path: yes —
ElevenLabs is paid and metered, so retries are the risk. The build MUST cap
attempts (2-3), retry ONLY on 429/5xx, never on 402 or other 4xx, and honor
`Retry-After` so a sustained upstream fault cannot become a cost/retry storm.
Secrets: `xi-api-key` stays in the request header (SEC-1 satisfied, no secret
in a URL); the Go→Python trust boundary is unchanged. STANDARDS the build must
satisfy: REL-2 (the target — service-side timeout + bounded backoff on
429/5xx), REL-4 (partial-write — safe here because the response is buffered and
nothing is written to the client until a 200), OBS (structured log + error
metric per outcome — coordinate with A2), DEP-1..3 (moot: no new dep). API
contract unchanged. Verdict: low risk; the only thing to police is the
money-path retry bound.

## Red-team verdict
*Adversarial pass (prompted to KILL the idea; run inline — no Opus sub-agent
spawn tool is available in this environment, so this is the researcher applying
the adversarial lens honestly, not a separate agent process).*

- **Wrong-priority?** Weak kill. The frontend already degrades to browser TTS
  and the Go path to macOS `say`, so an ElevenLabs failure is never fatal.
  *Survives:* REL-2 is a binding MUST that the debt doc implies is closed (it
  isn't, for ElevenLabs), and a single retry on the common `system_busy` 429
  preserves the just-shipped emotion-matched premium voice instead of dropping
  the user to robotic browser TTS. Real, if modest, value.
- **Hidden complexity?** Strong hit, not a kill. The 15 s frontend abort means
  a naive retry helps nobody on the live path (risk #1). This is a genuine
  landmine, but it is a design constraint to bake into the plan, not a reason
  the idea can't work.
- **Better alternative?** No. Frontend-side retry violates REL-2 ("no call
  relies solely on the caller's timeout"); adding a retry library loses on
  dep-discipline; doing nothing leaves a live MUST gap. Hand-rolled server-side
  retry is the right shape.
- **Conflicts-with-restructure?** No. Orthogonal to the cloud/auth move. The
  only coordination cost is possible file overlap with A2 (risk #3).

**The red-team does not kill the idea.** It downgrades the idea's own
confidence on two points: the retry budget must fit inside the 15 s abort to be
worth anything on the live path, and the "no file overlap with A2" claim is
not safe to assume.

## Recommendation
**Build.** This closes a real, currently-uncovered MUST-rule gap (REL-2 for
ElevenLabs) with a small, low-risk, zero-dependency change that mirrors an
existing in-repo pattern (the Anthropic retry) and preserves every current
fallback. Two conditions must be written into the build plan or the value
evaporates: (1) the total retry-and-backoff budget must fit inside the 15 s
frontend abort — shrink the per-attempt timeout to ~4-6 s and cap backoff — or
the retry is invisible to the live browser path; and (2) the retry must fire
only on 429/5xx, never on 402/other 4xx, capped at 2-3 attempts and honoring
`Retry-After`, so the paid ElevenLabs path cannot turn a sustained fault into a
cost storm. Coordinate sequencing with A2, which may also want to touch
`tts_route.py` for its TTS outcome metric — the "parallel, no overlap"
assumption should be confirmed by the Lead before both build at once.
