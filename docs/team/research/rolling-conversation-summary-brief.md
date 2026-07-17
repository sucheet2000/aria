# Research Brief — Rolling summary of dropped conversation turns

> Tooling note: this environment did not expose a sub-agent spawn tool, so the
> Security pre-check and Red-team sections below are my own analysis written
> faithfully against the `aria-security-team` agent definition
> (`.claude/agents/aria-security-team.md`) and `docs/STANDARDS.md`, not the
> output of a separately-spawned agent. Flagged honestly per PROTOCOL.

## Idea
- **Title:** Rolling summary of dropped conversation turns
- **Tag:** engineering · **Theme:** rag
- **Pitch:** Today the conversation history is hard-cut to the last 6 turns
  before it reaches the model (`backend/app/cognition/llm.py:155`,
  `conversation_history[-6:]`), and everything older simply disappears with no
  trace. Add a "conversation so far" block that only appears once the history
  overflows 6 turns, injected through a new slot in the prompt template. The
  first slice builds an **extractive** digest (verbatim selection, no generated
  text) with **no paid Claude call and no new dependency** — an abstractive
  Haiku version is a separate, later rung.

## Fit
**What exists**
- The 6-turn hard-cut is real and sits at `backend/app/cognition/llm.py:155`.
  Everything before `[-6:]` is dropped silently.
- There is **no** summary/compaction concept anywhere in cognition — a grep for
  `summariz|compact|consolidat` across `backend/app/cognition/` returns nothing.
- The prompt is assembled in `backend/app/cognition/prompt.py`. It returns two
  parts: a cached SOUL prefix (`soul_content`) and an **uncached** per-turn
  `observation_content` built from `_OBSERVATION_TEMPLATE` (lines 9-22). That
  template already has slots for working memory, episodic memory and a conflict
  instruction — a natural place to add one more slot.
- Prompt caching is a shipped optimisation: `llm.py:143-152` puts SOUL in an
  `ephemeral` cache block and the observation in a *separate uncached* block so
  the cache breakpoint actually hits.
- **Where the history lives:** the browser owns it. `ariaStore.ts:171` appends
  every turn to `conversationHistory` with no bound, and
  `useCognition.ts:143` sends the **entire** array every request. Go passes it
  through (`internal/cognition/handler.go`) under a 64 KB body cap
  (`handler.go:14`, `maxRequestBodyBytes = 64 << 10`). Python receives the whole
  list and then throws most of it away at the `[-6:]` slice. So the full history
  is already available at the Python `complete()` boundary today.
- Episodic memory already exists (ChromaDB 3-tier, `cognition/memory.py`).
  `cognition_route.py:83` calls `query_relevant()` and passes `episodic_memory`
  into the prompt — but it only stores/returns extracted **fact triples**, not
  conversational thread/topic continuity.

**What changes (first slice)**
- `backend/app/cognition/prompt.py` — add an optional `conversation_summary`
  parameter and a `{conversation_summary}` slot in `_OBSERVATION_TEMPLATE`
  (the uncached block, so caching is untouched).
- `backend/app/cognition/llm.py` — when `len(conversation_history) > 6`, build a
  bounded extractive digest of the dropped turns `conversation_history[:-6]` and
  pass it into `build_system_parts`. The `[-6:]` slice at line 155 stays.
- `backend/tests/test_llm_routing.py` (or a new `test_prompt.py`) — TDD.
- **No** proto/Go/TS contract change (this is internal to Python), so API-1
  one-source-of-truth is not triggered. No frontend or Go change needed.

## Prior art
This is a textbook, well-trodden pattern. LangChain's
`ConversationSummaryBufferMemory` keeps the most recent turns verbatim and folds
older ones into a running summary once a token limit is crossed — exactly the
"keep `[-6:]`, summarise `[:-6]`" shape here. The extractive-vs-abstractive split
(select verbatim segments vs. generate new text) and the "rolling digest"
approach are both standard. We are borrowing the *pattern*, not code: LangChain
(MIT) would be far too heavy to add and the idea is explicitly bound to no new
dependency.

## Dependencies (the contract list)
**None.** The extractive first slice is pure Python standard library
(string/list operations). The later abstractive rung would reuse the existing
`anthropic==0.85.0` client already in `requirements.txt` — still **no new dep**.

Considered and **rejected** (would violate the no-dep binding and DEP-1/DEP-2):
- `sumy` (Apache-2.0) — extractive summariser (LexRank/LSA), but pulls `nltk`
  and needs runtime data downloads.
- `nltk` (Apache-2.0) — needs a runtime `punkt` data fetch (network at import
  time = supply-chain surface). Out.

The build may add **only** deps named here, i.e. none.

## Effort & risks
**Effort: S.** Self-contained to two Python files plus tests; no schema/contract
change, no frontend/Go change, deterministic logic that is easy to test first.

**Top risks**
1. **Prompt-caching regression.** If the summary is placed in the cached SOUL
   block instead of the uncached observation block (`llm.py:143-152`), it breaks
   cache hits and *raises* cost. Mitigation: the summary must go only into
   `observation_content`.
2. **Extractive quality / budget bloat.** A naive "concatenate the dropped user
   turns" digest can be nearly as long as the original and read as low-signal
   noise, eating the budget it was meant to save and distracting the model.
   Mitigation: hard char/token cap on the block + select user utterances +
   dedup.
3. **Overlap with existing episodic memory.** ChromaDB already surfaces durable
   facts via `query_relevant` (`cognition_route.py:83`). The summary may
   duplicate facts already retrieved; net value is unproven without measurement.
4. **A cheaper, lossless alternative exists.** Widening `[-6:]` to, say,
   `[-12:]` is a one-line change with zero new surface and no information loss.
   For typical session lengths the summariser must justify its complexity over
   simply keeping more verbatim turns.
5. **Latent transport issue is not fixed.** The full history is re-sent every
   turn (`useCognition.ts:143`) under a 64 KB cap (`handler.go:14`). A
   Python-side summary improves the *model's* context but not the *wire* cost —
   do not over-claim that "the token-budget gap is closed."
6. **Restructure timing.** If conversation history moves server-side/persisted
   during the cloud restructure (SCALE-3 favours Postgres/pgvector), a stateless
   Python recompute could be reworked.

## Security pre-check
*(threat-model note, written to the aria-security-team Engagement-1 format)*

New attack surface — for the extractive first slice, **none**. The digest is
deterministic string work over `conversation_history[:-6]`, which is text the
user already authored and already transmits every turn. It flows into the same
LLM call that already receives those turns as messages, so there is no new
prompt-injection channel (arguably a smaller one). No new outbound call, so no
SSRF, no secret-in-URL (SEC-1), no new money path.

Data/PII — the digest is derived per request from the caller's own history and
is **not persisted**, so no new durable state and no owner-scoping surface
(SEC-3/DATA-6 unaffected). It **must stay stateless**; if a later rung persists
a summary it MUST be `owner`-keyed and written under `DATA_DIR` (DATA-1).

Money paths — extractive-first adds zero Claude/ElevenLabs spend. The later
abstractive (Haiku) rung would add one paid call per overflow turn; that rung
must satisfy REL-2 (timeout + bounded retry, guard `response.content[0]`), which
the existing client already wires (`llm.py:96-106,170`).

Rules the build must satisfy — for the first slice, only "keep the summary in
the uncached observation block so prompt caching is not broken." Any future dep:
DEP-1/DEP-2 (pinned + hashed + declared).

## Red-team verdict
*(adversarial pass, mandate: kill the idea)*

- **Wrong-priority / redundancy:** ARIA is a real-time *voice* companion;
  sessions may be short and the 6-turn cut may rarely bite. Durable facts are
  already captured as world-model triples and re-surfaced by episodic recall, so
  the summary partly re-does existing work. *Counter:* episodic memory stores
  triples, not topic/thread continuity — "what were we talking about 8 turns
  ago" is genuinely lost. Overlap is partial, not total.
- **Better alternative:** just widen the verbatim window (`[-6:]` → `[-12:]`) —
  one line, lossless, zero new surface, and Haiku's 200 K context makes the
  marginal turns cheap. Or lean on the sibling *distance-gated-recall* idea to
  retrieve the *relevant* old turns semantically rather than a lossy linear
  digest. Both are arguably better shapes than an extractive summary.
- **Hidden complexity:** doing extractive *well* (scoring, dedup, budget cap) is
  more than trivial, and doing it *badly* can degrade responses; there is no eval
  harness to tell whether the summary helped.
- **Verdict:** not a REJECT — the extractive framing is safe, cheap and real —
  but it is **not clearly the highest-value next move**, and it should not be
  built blind. Measure first (use the in-flight token-cost metric to confirm the
  verbose-history path actually hurts, and a manual long-session test to confirm
  the memory loss is felt), and decide summary-vs-wider-window-vs-semantic-recall
  before committing.

## Recommendation
**Phase.** The concept is sound, the first slice is genuinely small and carries
no new dependency, no new paid call and no new attack surface, so there is
nothing here to reject. But the red-team lands two fair blows: a one-line
"widen the window" alternative is lossless and nearly free, and the value
partly overlaps the episodic memory that already exists — so a blind green-light
is not warranted. Stage it: **Rung 0** — instrument with the in-flight
token-cost metric and a manual long-session check to confirm the gap is real and
that a wider verbatim window is not simply the better answer; **Rung 1** — the
bounded, pure-Python extractive digest in the uncached observation slot (no dep,
no paid call, S effort); **Rung 2**, behind its own gate — an abstractive Haiku
summary only if extractive proves too lossy, satisfying REL-2. Approve the
concept, gate the build on Rung 0.
