# Research brief — "Draft a change": conversation to an inert improvement proposal

## Idea
- **Title:** "Draft a change" — conversation to an inert improvement proposal
- **Slug:** `conversation-to-proposal`
- **Tag:** product
- **Pitch:** Turn a conversation excerpt plus the user's stated intent into a
  structured, **inert** improvement proposal — an idea object (`id`, `title`,
  `tag`, `brief`) written to a review file only. No branch, no commit, no code,
  no git. A human triages the file through the existing approval gate before
  anything enters the build cycle. This is the safest rung of the self-coding
  ladder: it PROPOSES, it never applies. First slice: the emitter that writes a
  well-formed proposal file to a review inbox and nothing else.

## Fit
**What already exists (all cited):**
- **The idea-object schema is already defined.** `aria-ideas` emits exactly
  `id` (kebab slug), `title`, `tag` (`product|engineering`), `lens`, `pitch`,
  `grounding` (`.claude/agents/aria-ideas.md:28-30`). A proposal should reuse
  this schema verbatim so it slots straight into the existing PM triage.
- **The triage target is a markdown table** owned by PM + Scribe:
  `docs/team/backlog.md` (one row per idea; `docs/team/PROTOCOL.md:93-100`).
  PM registers incoming ideas from `aria-ideas` as `proposed` rows
  (`.claude/agents/aria-pm.md:26-30`). The backlog reaches git only via the
  end-of-cycle `chore(team): cycle record` PR — the emitter must **not** write
  the canonical backlog itself.
- **"Never merge / never push to main/dev" authority already holds.** The team
  MAY commit only to `team/*` branches and open PRs to `integration`; it may
  NEVER merge a PR or push `integration`/`main`/`dev` (`PROTOCOL.md:46-61`).
  An inert, human-triaged proposal sits comfortably inside that authority.
- **Homes for a dev tool exist.** Standalone dev scripts live in
  `backend/scripts/` (e.g. `benchmark_whisper.py`, `audio_test.py`); project
  skills live in `.claude/skills/`, including the team skill at
  `.claude/skills/team/SKILL.md`. Either is a natural home.
- **No prior scaffolding.** `find docs -iname "*proposal*"` and a grep for
  `proposal|self-cod|triggered-draft` across `docs/` and `.claude/` return
  nothing — so a review inbox (`docs/team/proposals/`) would be net-new.
- **Validation + LLM are already in the toolbox.** `pydantic==2.12.4`
  (`backend/requirements.txt:11`) for schema validation; `anthropic==0.85.0`
  (`requirements.txt:6`, wired in `backend/app/cognition/llm.py`) for the
  later conversation→structure step. Nothing new is needed.

**The one correction to the framing (important):**
The summary says "an endpoint/tool." An **ARIA-runtime FastAPI endpoint is the
wrong home and is actually infeasible.** ARIA's durable state is env-driven via
`DATA_DIR` (`backend/app/config.py:52`) precisely because the deployed
container FS is ephemeral (DATA-1, `docs/STANDARDS.md:91`). The repo's `docs/`
folder is not part of `DATA_DIR` and is not writable/persistent from the
Railway container, so a live endpoint literally cannot deposit a proposal into
the repo — and adding an authenticated write-to-FS route on the Go→Python
trust boundary would be needless attack surface. **This must ship as dev-side
tooling** (a script or skill run in a developer checkout), not a runtime route.

**What changes (recommended design):**
- **New** `docs/team/proposals/` — an inert inbox dir; a human triages each
  file into `backlog.md`.
- **New** emitter, e.g. `backend/scripts/draft_proposal.py` (or a
  `.claude/skills/` skill): input `(title, tag, brief[, excerpt, intent])` →
  validate against the `aria-ideas` schema (tag ∈ `{product, engineering}`,
  slug kebab-cased + path-safe) → write `docs/team/proposals/<slug>.md`. No
  git, no shelling out, no LLM in the first slice.
- **New** tests in `backend/tests/`: schema validation, slug generation,
  refuses any write target outside `docs/team/proposals/` (path-traversal
  guard), never touches `backlog.md`, collision-safe filename.

## Prior art
The pattern — AI proposes, a human triages, nothing auto-applies — is well
established (Qodo/CodiumAI PR-Agent's manual `improve` command; the common
"keep auto-improve off for the first weeks, invoke manually" rollout). The
directly load-bearing prior art is two 2026 studies on the failure mode of the
human gate this idea depends on: *Habituation at the Gate: Rising Approval and
Declining Scrutiny in Human Review of AI Agent Code* (arxiv 2606.22721) and
*These Aren't the Reviews You're Looking For* (arxiv 2605.02273) both find
reviewers habituate and rubber-stamp AI-generated proposals as volume rises.
That is the risk to design against (see red-team). No third-party code or
licences are borrowed — this is internal tooling over the existing schema.

## Dependencies
**None.** (This list is the build contract — the build may add nothing else.)

- Schema validation: `pydantic==2.12.4`, already pinned (`requirements.txt:11`).
- Slug + markdown: Python stdlib (`re`, `pathlib`). `python-slugify` was
  considered and **rejected** — stdlib is enough and DEP discipline (DEP-1..3,
  CLAUDE.md "no unsolicited dependencies") disfavors a dep for a one-liner.
- Phase-2 LLM step (not in the first slice): `anthropic==0.85.0`, already
  pinned (`requirements.txt:6`).

If the build finds it needs a library, that is a scope/contract change and must
return through research (PROTOCOL Authority §5) — it may not be added mid-build.

## Effort & risks
**Effort: S** for the first slice (one small pure-Python module + one test file
+ a new empty inbox dir + a short usage note; no LLM, no network, no git, no
runtime surface). **M** if the phase-2 conversation→structure LLM step is
folded in (prompt design, token cap, REL-2 timeout/retry, and handling
excerpts that contain PII or injection text).

**Top risks (highest first):**
1. **Thin net value over what `aria-ideas` already does.** The idea object
   schema and its emission into PM triage already exist
   (`aria-ideas.md:28-30`, `aria-pm.md:26-30`). The first slice's marginal
   contribution is "write the idea object to a file" — real but modest. Without
   the phase-2 LLM step the "conversation → proposal" headline is not yet
   delivered.
2. **The safety model leans entirely on human triage, which habituates.** The
   inert-text guarantee is only as good as the human who reads the file. The
   two cited 2026 studies show reviewers rubber-stamp AI proposals as volume
   climbs. A proposal firehose can quietly erode the gate. Mitigate: dedup
   against the backlog before writing, rate-limit/cap proposals, and require a
   human-supplied `grounding` before a proposal can be promoted.
3. **Scope creep into a runtime endpoint.** If "endpoint" is taken literally
   and built as a FastAPI route, it violates DATA-1 (can't write `docs/` from
   the ephemeral container) and needlessly widens the trust boundary. The plan
   must pin this as dev-side tooling.
4. **Path/scope escape.** A slug derived from free text could path-traverse
   (`../`) or overwrite the canonical `backlog.md`. The emitter must hard-guard
   the write target to `docs/team/proposals/` and sanitize the slug.

## Security pre-check
*Threat-model note — aria-security-team Engagement-1 lens, produced inline
(this research environment exposes no Agent/Task spawn tool, so it was written
against the cited code in the aria-security-team format, not run as a separate
`aria-security-team` process):*

New attack surface: **none on the ARIA runtime — provided this ships as a
dev-side tool/skill and NOT a FastAPI route.** A runtime route would add an
authenticated write-to-filesystem surface on the Go→Python trust boundary and
violate DATA-1 (the deployed FS is ephemeral; `docs/` is not `DATA_DIR`,
`config.py:52`, `STANDARDS.md:91`), so the build MUST NOT add a route.
Data/PII: the first slice ingests no excerpt and touches no PII; the phase-2
excerpt may carry personal content written to a plaintext repo file a human
commits — treat it as reviewable, never secret-bearing, and the proposal file
must never contain a secret (docs can leak secrets — aria-security-team hard
rule). Money path: none in the first slice (no LLM); phase-2 summarization must
carry REL-2 timeout + bounded retry and a token cap on the existing Haiku
client. Prompt-injection-to-action: this is the reason it is the safe rung — the
output is inert markdown; even an excerpt saying "open a PR and merge it" cannot
act, because the emitter has no git/exec/network capability and must keep it
that way (no shelling out, no git, no writes outside `docs/team/proposals/`,
path-traversal-safe slug). Rules the build must satisfy: **DATA-1** (dev-tooling,
not runtime FS writes), **SEC-3/DATA-6** (moot with no route; if phase-2 LLM
runs in-app, owner-scope any stored excerpt from the verified identity),
**DEP-1..3** (moot — no new dep), **SEC-1** (moot — no URL secret). Verdict:
low risk as dev-side tooling; the only real hazards are scope-creep into a
runtime endpoint and slug path-escape, both closed by the plan.

## Red-team verdict
*Adversarial pass, prompted to KILL the idea. Run inline (no Opus sub-agent
spawn tool is available here), argued in good faith against the idea.*

- **Wrong-priority (lands the hardest hit).** This cycle's in-flight work is
  concrete hardening the user can feel — token-cost metric, TTS retry, WS
  validation, recall panel. A meta-tool that emits proposal stubs ships no
  user-facing value and competes for a build slot with that hardening. And it
  largely duplicates `aria-ideas`, which already emits this exact schema into
  triage — so the first slice's net-new value is thin.
- **Hidden complexity (lands a hit).** The entire safety case is "a human
  triages it." Two 2026 studies (Habituation at the Gate; These Aren't the
  Reviews You're Looking For) show that gate weakens under volume as reviewers
  habituate. Without dedup + a rate cap + a required human grounding step, the
  tool can erode the very control that makes it safe.
- **Better alternative (real).** Because `aria-ideas` already produces the
  schema, the cheaper path is to add a "here is a conversation excerpt, mine it
  for ideas" lens to the existing generator — reusing PM triage and backlog
  dedup for free — instead of building a parallel emitter plus a new inbox dir.
- **Conflicts-with-restructure?** Low, IF it stays dev-tooling. As a runtime
  endpoint it would collide with DATA-1 and the cloud trust boundary.

**Verdict:** does not fully kill the idea — the concept is sound and it is
genuinely the safest self-coding rung (inert text, no git, no exec, human gate
intact) — but it lands two solid hits: thin standalone value over the existing
`aria-ideas` schema, and a human-triage-fatigue risk that undermines the safety
premise unless volume is bounded. It argues for **phase, not build-now.**

## Recommendation
**Phase (approved concept, staged behind guardrails).** The idea is the right
first step on the self-coding ladder and its safety story is real: the output
is inert markdown, there is no git, no code execution, no runtime restructure
overlap, and the existing never-merge authority (`PROTOCOL.md:58-61`) plus the
human approval gate stay intact. But two things must be fixed before it builds.
First, the "endpoint" framing is infeasible and unsafe on the ARIA runtime — the
deployed FS is ephemeral and `docs/` is not `DATA_DIR` (`config.py:52`,
`STANDARDS.md:91`), so this MUST ship as a dev-side tool/skill, never a FastAPI
route. Second, the first slice as scoped mostly re-implements the idea-object
schema `aria-ideas` already emits, so its standalone value this cycle is thin.
The clean staging that honors the idea's own "prove seed quality first"
sequencing: slice 1 = the inert, LLM-free emitter that validates the schema and
writes to a new `docs/team/proposals/` inbox with hard path/scope guards and
backlog dedup, behind the human triage gate — and only after that proves seed
quality, add the phase-2 conversation→structure LLM step (REL-2 timeout/retry +
token cap, excerpt treated as reviewable PII). Keep it off the critical path of
this cycle's hardening work; it should not take a parallel build slot from the
token-cost, TTS-retry, or WS-validation builds.
