# Research Brief: Relevance-thresholded memory recall

## Idea
- **Title:** Distance-gated recall — stop injecting weak facts into every prompt
- **Slug:** `distance-gated-recall`
- **Theme / tag:** rag / engineering
- **Pitch:** ChromaDB already returns a *distance* for every recalled fact, but
  `_query_relevant_sync` (`backend/app/cognition/memory.py:188`) never reads it —
  it takes the top-k nearest facts no matter how far away they are, and feeds all
  of them into the Claude prompt. Add one config field (`RECALL_MAX_DISTANCE`) and
  read `response["distances"]` so semantically distant facts are dropped before they
  reach the model. The goal: ARIA's prompt carries only facts that are actually about
  what the user just said, instead of whatever five triples happened to be closest.

## Fit
**What exists today**
- `backend/app/cognition/memory.py:197-209` — `_query_relevant_sync` calls
  `collection.query(query_texts=[context], n_results=n_results_capped, where={"owner": owner})`
  and then loops over `response["documents"][0]` and `response["metadatas"][0]` only.
  The `distances` array is returned in the same response but is discarded.
- `backend/app/api/cognition_route.py:83` — the sole caller:
  `memory.query_relevant(req.message, owner=owner, n_results=5)`. So recall is capped
  at **5** facts, not 10.
- `backend/app/cognition/prompt.py:76` — `episodic_memory[:10]` renders the facts into
  the prompt. Because the query path caps at 5, this `[:10]` slice does not currently
  bind. (The idea's "up to 10 facts" framing is slightly off: the live ceiling is 5.
  The real problem is not the *count* — it's that all 5 are injected regardless of
  distance.)
- Recall is a **round-trip**: the facts `query_relevant` returns at
  `cognition_route.py:83` are sent back in the response (`:103`) and arrive next turn as
  `req.episodic_memory`, which `llm.py:134` passes to `build_system_parts`. So gating
  changes what the client stores and replays into the *next* prompt.
- `backend/app/config.py` — `Settings` (pydantic-settings). Adding a field is one line
  (e.g. next to `DEFAULT_OWNER`, `config.py:47`). Env-driven for free, so no STANDARDS
  `DATA-1`/config-hardcoding issue.

**What changes (paths)**
- `backend/app/cognition/memory.py` — in `_query_relevant_sync`, zip in
  `response["distances"][0]` alongside documents/metadatas and skip any doc whose
  distance exceeds the threshold. ~4 lines.
- `backend/app/config.py` — add `RECALL_MAX_DISTANCE: float` (one line + comment).
- `backend/tests/test_memory.py` — new tests: a near fact is kept, a far fact is
  dropped, and the default value leaves every current test green.

**Blast radius:** tiny and contained. Only one production caller
(`cognition_route.py:83`); the owner filter (`where={"owner": owner}`) is applied
*inside the query* and is untouched, so there is no Phase-3 owner-keying risk and no
change to the trust boundary. Nothing in Go or the frontend needs to change.

**Empirical check I ran** (chromadb 1.5.5, the pinned version, default embedding
function, default L2 space — `collection.metadata` is `None`): `distances` *is* in the
default response (`include` already covers it), so no change to the `query()` call is
needed — just read the field. Probe results for the query "programming language
preference" against three seeded triples:
```
dist=1.6864 | sucheet prefers Go          (the genuinely relevant one)
dist=1.6990 | user likes tea              (irrelevant)
dist=1.9727 | the weather in Tokyo is rainy (irrelevant)
```
The relevant fact and an irrelevant fact are **0.013 apart**. See risks — this is the
crux.

## Prior art
Relevance/score thresholding on top of top-k is a standard RAG pattern:
- **LangChain** — retriever `search_type="similarity_score_threshold"` with
  `search_kwargs={"score_threshold": ...}` (MIT). Note LangChain's threshold is a
  *distance*, matching what ChromaDB hands us — same shape as this idea.
- **LlamaIndex** — `SimilarityPostprocessor(similarity_cutoff=...)` node
  post-processor / `similarity_cutoff` (MIT).
We are re-implementing the *pattern* in ~4 lines against Chroma's native output; no code
is borrowed, so licences are informational only.
- Widely-cited rule of thumb: a relevance score needs ~0.80 AUC before a single global
  cutoff is trustworthy; below that a fixed threshold misclassifies too much in one
  direction. That directly bears on the probe above.

## Dependencies
**None.** `chromadb==1.5.5` (already pinned, `backend/requirements.txt:7`) returns
`distances` by default; `onnxruntime==1.24.4` (`:22`) already backs the default embedding
function. No new library, no version bump, no lockfile change. This contract list is
empty — the build may add nothing.

## Effort & risks
**Effort: S** (mechanically). The code is ~5 lines across two files plus tests. The *real*
work is not the code — it is choosing the threshold, which is an M-sized measurement task
if done honestly (log distances on real ARIA turns, look at the distribution, pick a
cutoff). Treat the coding as S and the calibration as a deliberate, measured follow-up.

**Risks (highest first):**
1. **The distances barely separate relevant from irrelevant (value risk).** My probe
   shows ~0.01 between a real hit and a miss on ARIA's short subject-predicate-object
   triples with the default MiniLM/L2 setup. Any global threshold loose enough to keep
   the good fact (1.686) also keeps the junk (1.699). So the headline win — "drop weak
   facts" — is *not guaranteed* by this embedding setup, and could be near-zero until the
   embedding model or the document text improves. This is the load-bearing risk and the
   reason the first slice must be measurement-first, not aggressive-cutoff-first.
2. **A too-tight default silently makes ARIA forget.** If the threshold ships aggressive,
   legitimate facts vanish from the prompt with no error — a quiet correctness/UX
   regression that's hard to notice. Mitigation: default must be a no-op (generous /
   effectively off) so every existing test in `test_memory.py` stays green and behavior is
   unchanged until a value is chosen from data.
3. **Metric fragility.** The threshold's meaning is tied to the L2 space + MiniLM model.
   If the collection's distance metric or embedding function ever changes, the magic
   number becomes wrong. Mitigation: comment the field with the metric/model assumption
   and the date measured; keep it env-driven.
4. **Empty/misaligned arrays.** `response["distances"]` could be `None` if a future
   `include` change drops it. Mitigation: guard for `None` and fall back to
   "keep the doc" (fail-open on recall, never crash the turn).

## Security pre-check
No agent-spawn tool was available in this workflow run, so the threat-model note below was
authored inline against the STANDARDS trust-boundary rules rather than delegated to
aria-security-team. Flag for the gate: if a formal aria-security-team sign-off is required,
it can be requested before build, but the surface here is essentially nil.

> **Threat model — distance-gated recall.** This change adds no new input, no new output,
> no network call, no dependency, no filesystem path, and no self-modifying or web-browsing
> behavior. It reads a float that ChromaDB already computes locally and compares it to a
> config constant — pure in-process post-filtering of data the service already holds.
> - **Owner-scoping (SEC-3/DATA-6):** unaffected. Filtering happens *after*
>   `where={"owner": owner}` inside the query (`memory.py:200`); the change can only ever
>   remove rows the owner already had access to, never widen the set. No cross-owner leak
>   is possible.
> - **Secrets (SEC-1/SEC-2):** none touched; `RECALL_MAX_DISTANCE` is a non-secret tuning
>   number, safe in env/logs.
> - **Fail-closed vs fail-open:** recall is best-effort context, not an authz decision, so
>   the guard should fail *open* (keep the fact, never drop the turn) if `distances` is
>   missing — this cannot escalate privilege.
> - **Injection / cost / DoS:** no new external call, so no timeout/retry surface
>   (REL-2 N/A) and no added token cost — if anything it *reduces* prompt tokens. Prompt
>   injection is out of scope: this filters which stored facts are shown, it does not
>   execute anything.
> - **Residual concern:** the only failure mode is *availability of memory* (a too-tight
>   threshold hides facts), which is a product-quality risk, not a security one. Ship with
>   a no-op default and measure before tightening.
> **Verdict: no security objection. Standard change.**

## Red-team verdict
Adversarial pass (self-run; no Opus sub-agent tool available in this workflow — logged
honestly). Angle that lands hardest: **hidden-complexity / unproven-value.**

The pitch sells this as "the cleanest, highest-certainty RAG win." The code is certainly
clean, but "high-certainty *win*" does not survive contact with the data. My probe shows
that on ARIA's actual memory shape — tiny "subject predicate object" strings embedded with
the default MiniLM model under L2 — the distance between a truly relevant fact and an
irrelevant one is ~0.01, inside a compressed 1.68–1.97 band. There is essentially no
daylight for a single global cutoff to exploit, which is exactly the regime the prior-art
"~0.80 AUC before a global cutoff works" rule of thumb warns against. So the mechanism is
trivial but the *benefit* is unmeasured and plausibly marginal until the embeddings or the
stored text get richer. Selling S-effort plumbing as a certain win overstates it.

Better-alternative angle: if the goal is genuinely-relevant context, the higher-leverage
move is improving *what gets embedded* (embed a natural-language sentence, or a richer
episodic summary, instead of three-word triples) or switching to a normalized-cosine space
— either widens the separation the threshold then depends on. Distance-gating on top of
poorly-separated embeddings is treating the symptom.

Wrong-priority angle: weaker. The change is cheap, reversible, owner-safe, and doesn't
collide with in-flight cycle-2 work (token-cost metric, TTS retry, WS validation, episodic
panel — different files). It won't hurt.

**Red-team conclusion: does NOT kill the idea, but kills the framing.** The honest version
is not "ship a relevance threshold and win"; it is "land the plumbing with a no-op default,
instrument the distance distribution on real turns, and choose a cutoff only if the data
shows separation." Ship the mechanism; earn the threshold.

## Recommendation
**Build — as a measurement-first first slice, not an aggressive cutoff.** The mechanism is
correct, cheap (~5 lines, S), owner-safe, dependency-free, has no security surface, and
does not touch any in-flight work. But the red-team and my own probe agree the *win* is
unproven on ARIA's current short-triple embeddings, where relevant and irrelevant facts sit
~0.01 apart. So the smallest shippable increment should land the wiring — read
`response["distances"]` in `_query_relevant_sync`, add `RECALL_MAX_DISTANCE` to config with
a **generous/no-op default that keeps every existing test green**, and log each recalled
fact's distance so we can see the real distribution — and *defer* choosing an aggressive
threshold to a follow-up once we've looked at that data. That way we get the plumbing and
the observability now, at near-zero risk, and only tighten the screw when the numbers say
it will actually help. Do not ship this as "smart recall is done"; ship it as "we can now
see and gate recall distance, default off."

**First slice (smallest shippable):** In `_query_relevant_sync`, zip
`response["distances"][0]` into the existing loop, `continue` past any doc whose distance is
`> settings.RECALL_MAX_DISTANCE`, and `logger.debug` the fact + distance. Add
`RECALL_MAX_DISTANCE: float = 2.0` (above the observed max, i.e. a no-op) to `Settings` with
a comment naming the L2/MiniLM assumption. Tests: (a) a near fact is kept and a far fact is
dropped when the threshold is set tight in the test; (b) the default value returns exactly
what recall returns today (regression guard). No changes to Go, frontend, or the query call
itself.
