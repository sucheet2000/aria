# Research brief — single-page-reader

## Idea
**Title:** Lightweight single-page reader (httpx on-ramp before full browser)
**Tag:** engineering · **Theme:** browsing

**Pitch:** When the owner pastes or speaks a URL, ARIA fetches that one page
server-side (timeout + bounded retry), turns the HTML into plain text, and
summarizes it so ARIA can ground an answer in a real page. Deliberately the
first, smallest rung on the browsing risk ladder — the Playwright flagship and
the voice "research for me" experience stack on top of this once the
fetch-and-allowlist plumbing is proven.

## Fit
**What exists today (verified):**
- No web-fetch, crawler, or HTML-parsing code exists anywhere in the Python
  backend. The only outbound HTTP call is the ElevenLabs TTS request at
  `backend/app/api/tts_route.py:45` (`httpx.AsyncClient(timeout=10.0)`).
  Grep for `requests/urllib/aiohttp/bs4/httpx` across `backend/app` returns
  only that one file.
- `httpx==0.28.1` is already pinned (`backend/requirements.txt:17`) and in use,
  so the HTTP client itself is **not** a new dependency.
- The route pattern this would follow is `backend/app/api/cognition_route.py`:
  routes are registered in `backend/app/main.py:115-119`; the internal ones
  (`cognition_router`, `tts_router`) are mounted behind
  `Depends(require_internal_auth)` (`main.py:115,118`).
- Owner-scoping seam already exists: `get_current_owner`
  (`backend/app/api/deps.py:20`) reads the `X-Aria-Owner` header that the Go
  edge sets after verifying the Clerk JWT. `require_internal_auth`
  (`deps.py:25`) fails closed when `INTERNAL_AUTH_SECRET` is set.
- Fact storage already exists and is owner-scoped:
  `MemoryStore.store_triple(..., owner=owner)` (`backend/app/cognition/memory.py:118`),
  called from `cognition_route.py:74`.
- The internal targets an SSRF would attack are real and local: gRPC binds
  `127.0.0.1:50051/50052` (per `CLAUDE.md` architecture decisions), and the
  Railway host exposes a cloud metadata endpoint.

**What changes (proposed first slice):**
- New file `backend/app/api/research_route.py` — one owner-scoped, internal-auth
  route `POST /api/research` with a typed pydantic `response_model` (API-6).
- New file `backend/app/pipeline/url_guard.py` (or similar) — the SSRF harness:
  scheme check, deny-by-default domain allowlist, DNS-resolve-then-validate-IP,
  connect to the pinned IP, block RFC1918 / loopback / link-local
  (169.254.0.0/16) / IPv6 ULA / `::1` / IPv4-mapped ranges,
  `follow_redirects=False`, response size cap, content-type gate.
- A small HTML-to-text extractor (stdlib `html.parser`) — new file, no new dep.
- New setting in `backend/app/config.py` (`class Settings`, `config.py:12`):
  `RESEARCH_ALLOWLIST: str = ""` (comma-separated hosts), fail-closed in cloud
  (empty allowlist in `ENV != local` = route refuses, per SEC-2 spirit).
- `backend/app/main.py` — mount the new router behind `require_internal_auth`.
- Tests under `backend/tests/` (TDD-first): allowlist accept/deny, each blocked
  IP range, redirect refusal, size cap, timeout/retry, owner-scoping,
  response_model shape.

**Not tool-wiring in slice 1.** Wiring `read_page` as an autonomous Claude tool
would mean adding `tools=` + a tool-use agentic loop to `LLMClient.complete`
(`backend/app/cognition/llm.py:160`, which today calls `messages.create` with no
tools). That is a materially larger and riskier change (see red-team) and is
explicitly deferred.

## Prior art
- **OWASP SSRF Prevention Cheat Sheet** and 2025-2026 write-ups converge on the
  same defense: allowlist > IP-allowlist > IP-blocklist, and crucially
  **resolve-the-hostname-then-connect-to-that-exact-IP** to defeat DNS
  rebinding; disable redirect-following (or re-validate every hop). The naive
  "validate the URL then fetch it" pattern is broken by design (rebinding).
- **Anthropic native `web_fetch` server tool** (models overview / release
  notes): Anthropic now offers a server-side `web_fetch` tool supported on
  **Claude Haiku 4.5 and Sonnet 4.5** — the exact models ARIA routes to. It
  fetches the page on Anthropic's infrastructure and hands content to the model,
  so the SSRF surface lives on Anthropic's network, not ours. Limitation: no
  JavaScript-rendered pages (same limitation httpx has). Priced at standard
  tokens (this is `web_fetch`, not the `$10/1k` `web_search`). This is a serious
  alternative to building a bespoke fetcher — see red-team.
- HTML-extraction landscape: `trafilatura` gives the best article quality but a
  heavy transitive tree (lxml C-extension, courlan, htmldate, dateparser);
  `selectolax` is fast MIT/0-dep but a compiled C-extension wheel; `html2text`
  is GPL-3.0 (copyleft — unusable in a proprietary product). For a first slice
  where Claude does the summarizing, stdlib `html.parser` is sufficient.

## Dependencies (the contract)
The build may add ONLY what is named here, pinned. (Repo note: `requirements.txt`
is pinned but **not hashed** — full hash-locking is deferred debt per
`docs/STANDARDS_DEBT.md:32`, "needs a Linux-side lock step"; so the idea's
"pinned+hashed" phrasing is currently pinned-only. This idea does not change
that; new deps are pinned exact.)

- **Primary path — ZERO new dependencies.** `httpx==0.28.1` (already present,
  BSD-3-Clause) + Python stdlib `html.parser`. This is the strongest DEP posture
  and the recommended slice-1 path.
- **Pre-authorized fallback — `beautifulsoup4==4.15.0`** (MIT, released
  2026-06-07). Pure-Python, uses the stdlib `html.parser` backend so it adds
  **no** C-extension; transitive deps `soupsieve` (MIT) + `typing_extensions`
  (already present via pydantic). Named here so the engineer MAY add it *without
  a scope-stop* if the stdlib extractor proves inadequate mid-build. If added,
  pin `beautifulsoup4==4.15.0` and `soupsieve` to its then-current exact pin.
- **Explicitly NOT approved (flagged heavy / license):**
  `html2text` (GPL-3.0 copyleft — reject), `trafilatura` (heavy lxml-based
  tree — park for a later article-quality phase), `selectolax` (compiled
  C-extension binary wheel + Linux-wheel hashing friction — not needed for the
  first slice).

## Effort & risks
**Effort: M** (not S — the idea's "just use httpx" framing undersells it). The
httpx call is ~5% of the work; the SSRF harness (resolve-validate-pin,
IPv4+IPv6 private/loopback/link-local blocking, deny-by-default fail-closed
allowlist, no-redirects, size/content-type caps, REL-2 timeout+bounded retry),
the `response_model`, owner-scoping, and the security test matrix are the bulk.
If the team instead adopts Anthropic's native `web_fetch`, effort drops to **S**
but shifts to a different (smaller) test surface.

**Top risks:**
1. **SSRF is the whole ballgame.** A naive fetcher on Railway (loopback gRPC +
   cloud metadata endpoint) is a genuine internal-network read primitive. The
   guard must land as part of slice 1, not after.
2. **DNS rebinding / redirect bypass** defeats validate-then-fetch. Mandatory:
   resolve-then-connect-to-pinned-IP and `follow_redirects=False`.
3. **Cost / DoS via summarization.** Fetch is free but summarize spends Claude
   tokens; a fetch→summarize loop with no per-owner rate limit is a cost hole.
   This has a real sequencing dependency on the **in-flight token-cost metric**
   (OBS-3) — this idea should land after/with it, with a per-owner rate cap.
4. **Memory poisoning via "store a fact."** If page text can autonomously write
   a triple, an injected page poisons owner-scoped memory. Slice 1 must NOT
   auto-store facts from page content.
5. **Response-based resource exhaustion** (huge body, decompression bomb) — cap
   bytes and content-type before reading.

## Security pre-check
*(Threat-model note. The `aria-security-team` sub-agent could not be spawned from
this researcher run — no delegation tool was available — so this is my own Opus
threat model, written to that agent's bar; a full `aria-security-team` review
must gate the build.)*

**Trust context:** single-user today (Clerk, owner-scoped), so the "attacker" is
(a) the authenticated owner supplying a hostile URL, and (b) prompt-injection —
critical the moment `read_page` becomes an autonomous tool, where a malicious
page could instruct ARIA to fetch an internal URL or write a fact. The
endpoint-first slice keeps the URL owner-supplied and the output text-only,
which contains (b) but leaves the SSRF surface identical.

**Assets:** loopback gRPC `127.0.0.1:50051/50052`, the Railway cloud metadata
endpoint, the Go↔Python internal-auth boundary, env secrets (Anthropic /
ElevenLabs / `INTERNAL_AUTH_SECRET`), owner-scoped ChromaDB memory.

**Required controls for a safe slice 1 (all first-class, not follow-ups):**
- Scheme allowlist `http/https` only (block `file://`, `gopher://`, `ftp://`).
- Deny-by-default **domain allowlist** from env; **fail closed** in
  `ENV != local` if unset (SEC-2 posture).
- **Resolve host → validate IP → connect to that pinned IP** (Host header
  preserved). Block RFC1918, loopback, link-local `169.254.0.0/16`, IPv6 ULA
  `fc00::/7`, `::1`, IPv4-mapped-IPv6. Defeats DNS rebinding.
- `follow_redirects=False` for slice 1 (re-validate every hop only if enabled
  later).
- **Timeout + bounded retry-with-backoff** on 429/5xx (REL-2), max response-size
  cap, content-type gate (`text/html`, `text/plain`).
- Route behind `require_internal_auth` + `get_current_owner`; per-owner rate
  limit; structured-log the URL + outcome, never the internal secret.
- **No autonomous fact-write from page content** in slice 1. If later added:
  provenance `web:<url>`, lower confidence, subject/predicate never chosen by
  page text.

**Verdict:** the safe version is clear and achievable, but only if the SSRF
harness is slice 1 and fact-write + tool-autonomy are explicitly deferred.

## Red-team verdict
*(Adversarial pass — I could not spawn a separate Opus killer sub-agent from this
run, so I ran the adversarial analysis myself, honestly trying to kill it.)*

Three substantive hits; none is fatal, but together they move the call off a
plain "build":
- **Hidden complexity (strong):** "lightweight httpx reader" disguises that the
  bulk and the entire risk is a correct SSRF harness in a cloud host with a
  metadata endpoint. A rushed version is a real internal-read vuln. Re-scopes
  effort S→M and mandates the guard as slice 1.
- **Wrong-priority / sequencing (real):** summarize spends tokens; without the
  **in-flight token-cost metric** and a per-owner rate cap, fetch→summarize is a
  cost/DoS hole. This should not land *before* that metric.
- **Better alternative (strong):** Anthropic's native `web_fetch` server tool is
  supported on the exact Haiku 4.5 / Sonnet 4.5 models ARIA already calls at
  `llm.py:160`. It delivers the same user value (ARIA reads a real page and
  grounds an answer), moves the SSRF surface off our Railway network, and needs
  **no HTML-extraction dependency**. A short spike should confirm/deny it before
  committing to bespoke fetch+SSRF code.

The red-team does **not** kill the idea — the concept (a safe browsing on-ramp)
is sound and is the right first rung. It kills the *implementation-as-scoped*
(bespoke server-side fetcher, "S", with auto-fact-store) and pushes to a staged
build behind guardrails.

## Recommendation
**Phase.** Approve the concept; do not green-light the bespoke fetcher as an "S"
task. First run a ~1-day spike on Anthropic's native `web_fetch` tool (the SDK is
already pinned at `anthropic==0.85.0`); if it fits, it obviates most of this work
and its SSRF risk. If it does not fit (e.g. beta not usable, cost, or we want
control of the fetch), build slice 1 as the **guarded read-only endpoint**:
`POST /api/research` behind `require_internal_auth` + owner-scoping, with the full
SSRF harness (deny-by-default allowlist, resolve-and-pin IP validation, no
redirects, size/type/timeout+bounded-retry caps), a stdlib `html.parser`
extractor, a typed `response_model`, and a per-owner rate cap — with
**no autonomous fact-write and no Claude-tool wiring**. Sequence it after/with the
token-cost metric. Defer the fact-store and the agentic tool to later phases,
each behind its own guardrails. In plain English: good idea, real value, but the
safe version is bigger than it looks, it leans on cost-metering that is still
being built, and Anthropic may already give us this for free — so approve it as a
staged build, not a quick win.
