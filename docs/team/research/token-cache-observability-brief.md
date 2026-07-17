# Research Brief: token-cache-observability

## Idea
- **Title:** Populate the token-cost / cache-hit metric to prove prompt-caching pays off
- **Tag:** engineering
- **Pitch:** `record_token_cost(model, cached, tokens)` already exists in
  `backend/app/observability/metrics.py:59`, with a `token_cost` bucket already in the
  `/metrics` snapshot (`metrics.py:82`). I confirmed it has **zero callers** and that
  `llm.py` **never reads `response.usage`**. So the prompt-caching that was just shipped to
  prod (the SOUL block split for ~90% system-prompt savings) is flying completely blind —
  we cannot tell whether the cache is actually hitting or silently paying full price. Wire
  the four usage fields off the Anthropic response into the existing recorder so `/metrics`
  finally shows real cache-hit rate and per-tier token volume.

## Fit (what exists, what changes)
**What already exists (all verified):**
- `backend/app/observability/metrics.py:59` — `record_token_cost(model, cached: bool, tokens: int)`
  writes into a per-model `{"cached": N, "uncached": M}` bucket (`metrics.py:43`).
- `backend/app/observability/metrics.py:82` — the `token_cost` bucket is **already** in the
  `snapshot()` output, so `/metrics` will expose it the moment data flows in. No route or
  serializer change needed.
- `backend/app/api/metrics_route.py:8-10` — `/metrics` returns `MetricsCollector().snapshot()`.
- `backend/app/cognition/llm.py:160-166` — the single Anthropic call site
  (`self._client.messages.create(...)`). Its `response` object carries `.usage`, but the code
  only touches `response.content[0]` (`llm.py:170`) and drops `.usage` on the floor.
- `backend/app/api/cognition_route.py:70` — the established pattern
  (`MetricsCollector().record_cognition_latency(...)`) shows exactly how metrics are recorded
  in this codebase.

**Verified negatives:**
- `grep record_token_cost` across the backend → only the definition, **no callers**.
- `grep "\.usage"` across `app/` → **no matches** anywhere.
- `anthropic==0.85.0` (pinned, `backend/requirements.txt:6`) already exposes the needed fields.
  I introspected the installed SDK: `Usage` has `cache_read_input_tokens`,
  `cache_creation_input_tokens`, `input_tokens`, `output_tokens` (plus others). No SDK bump.

**What changes (small, additive, backend-only):**
- `backend/app/cognition/llm.py` — after the API call (`llm.py:166`), read `response.usage`
  **defensively** and call the recorder. Suggested mapping so the existing 2-bucket shape
  proves the cache:
  - cached bucket += `cache_read_input_tokens`
  - uncached bucket += `input_tokens + cache_creation_input_tokens`
  This makes `cached / (cached + uncached)` a direct cache-hit ratio on input tokens — exactly
  the "did prompt-caching pay off?" number. Record under the tier's model string
  (`_MODEL_HAIKU` / `_MODEL_SONNET`) so you get a per-tier breakdown for free. Tier-0 makes no
  API call, so it correctly records nothing.
- `backend/tests/test_llm_routing.py` — the `_fake_response` MagicMock helper (`:151`) has no
  `.usage`; it must be given a realistic integer-valued usage stub, or naive recording would
  break the existing reliability tests. Plus 2–3 new tests (cache-hit records to `cached`;
  missing/None usage is a no-op; tier-0 records nothing).
- `backend/tests/test_metrics.py` — extend to assert the two-bucket accumulation semantics.

**Deliberately NOT changed:** `CognitionResponse` / pydantic / proto / Go / TS. Recording
inside `llm.py` (where `.usage` lives) keeps this **off the contract source-of-truth** — no
API-1/API-2 surface, no cross-language edit. `metrics.py` itself needs no change: the recorder
and snapshot already exist. No import cycle: `metrics.py` imports nothing from `app`.

## Prior art
- Anthropic's own docs and community write-ups describe exactly this: read
  `cache_read_input_tokens` / `cache_creation_input_tokens` / `input_tokens` off `message.usage`
  to measure cache hit rate; cache reads bill at ~10% of input rate, cache writes at a ~25%
  premium. Two well-documented pitfalls to note:
  1. If the cached prefix is below the model's minimum cacheable size (~1024 tokens),
     `cache_creation_input_tokens` returns 0 and you **silently pay full price** — the single
     most common "caching does nothing" cause. Our metric would surface exactly this, which is
     the point of building it.
  2. Naive dollar-cost math on cached responses is error-prone (see the litellm cost-calc bug).
     We intentionally record **token counts, not dollars**, which sidesteps that class of bug.
- **License:** no third-party code borrowed. We use our already-pinned SDK to read fields off a
  response object. Nothing to vendor, nothing to attribute.

## Dependencies (the contract list)
**NONE.** `anthropic==0.85.0` is already pinned + hashed in `backend/requirements.txt:6` and
already exposes every field this idea reads (verified by SDK introspection). This build adds no
library. Per PROTOCOL Authority §5, the build may add nothing beyond this list — i.e. nothing.

## Effort & risks
**Effort: S (small).** ~10–15 lines of defensive recording in `llm.py`, plus test updates. No
new route, no new dep, no contract change, no Go/TS/proto touch. Single specialist
(`aria-python-pipeline`), single file of production code.

**Top risks:**
1. **Hot-path safety (highest).** Metrics recording must **never** crash the cognition response.
   If `response.usage` is missing/None or a field is non-int, recording must be a silent no-op —
   mirror the existing `response.content[0]` guard at `llm.py:170`. A metric that throws would
   turn a successful Claude call into a 500.
2. **Existing-test breakage.** `_fake_response` (`test_llm_routing.py:151`) is a bare MagicMock;
   `int(response.usage.cache_read_input_tokens)` on it would raise. The mock must be updated in
   the same PR. Known, small, in-scope.
3. **Lossy 2-bucket mapping.** Folding `cache_creation` (25% write premium) into "uncached" is
   directionally correct for a hit-rate signal but not dollar-accurate. Acceptable for
   "is the cache working?"; dollar-precision is a separate, future idea — do not expand scope.
4. **Scope-creep magnet.** p95 percentiles, output-token cost, per-owner attribution, TTL
   breakdown, dollar cost will all be tempting. Hold the line: wire the existing recorder with
   the four fields, defensively. Anything else is a new brief.

## Security pre-check
> **Process note (honest):** this environment exposes no agent-spawn tool, so I could not launch
> `aria-security-team` as a separate process. The threat-model note below is my inline
> stand-in, performed to the same checklist. It should be re-run by `aria-security-team`
> proper at the build gate before merge.

**Threat-model note (token-cache-observability):**
- **New trust-boundary surface: none.** No new route, no new auth, no new external call, no
  secret handling, no config. It reads integer fields off an Anthropic response already in
  memory and increments an in-process counter.
- **Data sensitivity: low.** The metric stores **token counts only** — no prompt text, no user
  utterances, no PII. It is aggregated per-model (haiku/sonnet), not per-owner, so SEC-3 /
  DATA-6 owner-scoping does not apply: this is global operational telemetry by design, not user
  data.
- **Endpoint exposure (the one real note).** `/metrics` is mounted **without**
  `require_internal_auth` (`backend/app/main.py:116`; the `:113` comment says `/health` and
  `/metrics` stay open) — and OBS-3 (`docs/STANDARDS.md:169-171`) *requires* `/metrics` reachable
  through the public edge. So adding token counts means aggregate token volume becomes visible to
  anyone who can reach `/metrics`. Sensitivity is low (counts, no content), and the endpoint's
  openness is a pre-existing, standards-endorsed decision — not introduced here. Flag it, do not
  fix it in this idea.
- **Fail-closed / availability.** The single hard requirement: recording must not raise on the
  cognition hot path (see Risk 1). Guard `usage` and coerce each field safely; a metrics failure
  must degrade to a no-op, never to a 500.
- **DATA-1 (ephemeral FS): N/A.** In-memory singleton, resets on restart — same as every other
  metric today. No persistence path added.
- **OBS-1 (log hygiene).** If usage is logged at all, log integer counts only — never prompt text.
- **Verdict: approve.** Negligible new attack surface. This change *advances* OBS-3 (a MUST rule
  that Claude token spend "is counted" — currently unmet because the recorder is dead) rather than
  eroding any standard. Sole conditions: defensive recording, and counts-not-content in any log.

## Red-team verdict
> **Process note (honest):** no separate Opus adversary could be spawned in this environment. The
> following is my own adversarial pass, run under an explicit "try to kill it" mandate across the
> four kill lenses. I did not soften it.

- **Wrong-priority?** Weak kill. This verifies a **just-shipped prod investment** that is
  currently 100% unmeasurable — we literally cannot tell if the SOUL prefix is above the ~1024-token
  cache floor or silently paying full price. And OBS-3 is a **MUST** that requires Claude token
  spend be counted; the recorder is dead, so this closes a standards MUST gap. High leverage, not
  a nice-to-have. Survives.
- **Hidden complexity?** Partial hit, not fatal. Real gotchas exist — hot-path safety, the
  `_fake_response` mock lacking `.usage`, and the lossy 2-bucket mapping — but all are S-effort and
  named above. Nothing here escalates to M. Survives.
- **Better alternative?** Weak kill. "Just use the Anthropic Console / grep logs." Console is
  per-account aggregate, not per-tier, and not wired into the `/metrics` surface OBS-3 mandates;
  logs aren't the mandated path either. Relying on Console leaves OBS-3 unmet and the recorder dead.
  Survives.
- **Conflicts-with-restructure?** No. Backend-only, `aria-python-pipeline`, no contract change, no
  shared files with the in-flight CSP-nonce / DATA_DIR-storage / whisper-prebake work. Clean pair
  with the frontend idea it was slated against — truly parallel. Survives.
- **Overall: NOT killed.** Small, additive, standards-closing, near-zero blast radius. The only
  thing that would make it a bad build is sloppiness on hot-path safety — which is a build-quality
  bar, not a reason to reject.

## Recommendation
**Build.** This is close to the ideal shakedown pick: a single line of dead code sitting one hop
from live, verifying a production investment (prompt-caching) that is otherwise completely
unmeasurable, while advancing a standards MUST (OBS-3) that is currently unmet. It is purely
additive, backend-only, touches no trust boundary, changes no contract, and adds no dependency —
the dependency contract is literally empty. The build must clear exactly two quality bars:
recording must be defensive so a missing `usage` can never crash the cognition hot path, and the
existing `_fake_response` test mock must gain a usage stub in the same PR. Hold scope tightly to
"wire the four usage fields into the existing recorder" — no dollar-cost math, no percentiles, no
per-owner attribution. Under those conditions, this is a fast, safe, high-signal build.
