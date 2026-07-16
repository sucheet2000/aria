# ARIA Autonomous Agent Team — Design Spec

**Date:** 2026-07-16
**Status:** Approved by Sucheet (design sections 1–5, this document is the written record)
**Owner touchpoints:** exactly two — approve ideas after reading research, and merge the resulting PRs.

---

## 1. Summary

An autonomous agent team for the ARIA repo that takes work from "idea" to "PR opened on
`integration`" with exactly two human touchpoints. Eleven new coordinating agents (all
Opus 4.8, all able to spawn sub-agents) sit above the five existing `aria-*` specialist
agents, which remain the hands-on workers. One command — `/team` — runs a full cycle.

Everything between the two touchpoints is automated: idea generation, research,
planning, TDD implementation, debugging, code review, security review, in-browser QA,
documentation sync, and CI watching.

## 2. Goals

- Sucheet sees: new ideas + the research behind them (touchpoint 1), and finished,
  evidence-backed PRs (touchpoint 2, the final call). Nothing else requires him.
- The restructure investment is protected: `docs/STANDARDS.md` is enforced on every
  build (the ratchet never loosens), and docs never drift from code.
- Debugging never bloats the codebase: root-cause-first, smallest-fix discipline.
- Cost is bounded everywhere: agent tokens, CI minutes, and runtime API money.

## 3. Architecture decision

**Hybrid orchestration** (chosen over "one PM agent does everything" and "fully
scripted end-to-end"):

- **Phase 1 (ideas + research) is scripted** — a deterministic, resumable workflow:
  parallel lens-based idea generation → dedup against the backlog → parallel
  research, one researcher per idea. Mechanical fan-out work suits a script.
- **Phase 2 (builds) is judgment-driven** — the PM coordinates Lead → Engineer →
  Debugger → Code Reviewer → Security → QA → Scribe per approved idea. Build work
  needs judgment loops that rigid scripts handle poorly.
- **Hard platform constraint:** sub-agents cannot talk to the user. All approvals
  flow through the main Claude Code session, which presents packages and collects
  decisions.

## 4. Team roster

### New agents (11) — all `model: opus` (Opus 4.8), `memory: project`, may spawn sub-agents

| Agent | Role |
|---|---|
| `aria-pm` | Project Manager. Owns the cycle: backlog, triage, approval package assembly, phase-2 coordination, serialization of overlapping builds, end-of-cycle report. Writes no code. |
| `aria-lead` | Project Lead (tech lead). Turns approved idea + research into a file-by-file plan honoring `docs/STANDARDS.md`; assigns specialists; checks the finished diff **matches the plan** (conformance only — quality is the Code Reviewer's question, safety is Security's). Flags file-overlap between parallel builds. |
| `aria-engineer` | Project Engineer. Implements the Lead's plan TDD (red/green/refactor) by delegating to the five `aria-*` specialists. Works in an isolated `team/<idea-slug>` worktree. Runs `make check` until green. Does **not** fix its own red builds — that goes to the Debugger. |
| `aria-researcher` | Researcher. Produces the brief Sucheet reads: feasibility, what already exists in the codebase (code-review-graph MCP), libraries needed (pinned + licence-checked per DEP rules), effort estimate, risks. Spawns an adversarial red-team sub-agent that tries to kill the idea before it reaches the gate. Uses web search for prior art. |
| `aria-security-team` | Security coordinator. Two engagements per idea: a threat-model pre-check during research (risk visible *before* approval) and the full build-time review, spawning the existing `aria-security-reviewer` plus adversarial verifiers. A PR cannot open until it passes. |
| `aria-ideas` | Idea Generator. Spawns lens sub-generators (product/UX, voice & audio, memory & cognition, avatar/3D, reliability/cost/DX). Every idea tagged `product` or `engineering`. Aware of the in-flight restructure program and the backlog: never proposes conflicts or previously rejected ideas. |
| `aria-code-reviewer` | Code Reviewer — the restructure's guard dog. Reviews every diff before Security: no new `docs/STANDARDS.md` MUST-violations, diff minimality (nothing the plan didn't call for), convention match, real test coverage. Spawns dimension sub-reviewers (correctness, simplification, standards-compliance, test coverage, a11y, performance) and uses code-review-graph MCP (`detect_changes`, `get_impact_radius`). Findings are adversarially verified before reporting. |
| `aria-debugger` | Debugger — the only agent allowed to fix a failing build. Discipline: reproduce → root cause → state it → smallest fix that addresses the root cause. No refactor-while-fixing, no defensive sprinkling, no module rewrites. If minimal fix and proper fix genuinely differ, it says so in its report rather than over-building. Invocable standalone with identical rules. |
| `aria-qa` | QA Verifier. After code review passes: boots the app, drives the changed feature in a real browser (Playwright), captures screenshots/network evidence, attaches it to the PR. Exercises only paths inside the change's impact radius; hard budget ≤5 paid API calls per verification; changes not touching cognition/TTS paths trigger zero paid calls. |
| `aria-scribe` | Docs Curator. Inside the same PR as the change: updates whatever went stale (`CLAUDE.md`, agent file maps, `docs/STANDARDS_DEBT.md`, architecture docs). Maintains `docs/team/backlog.md` and cycle records. |
| `aria-devops` | CI & Deploy Watcher. Enforces the one-push policy, watches the CI run after the single push, diagnoses failures (env deltas: CPU-only torch, pinned deps), routes fixes through the Debugger, re-checks. Watches Railway/Vercel deploys **only after Sucheet's merges** — the team never deploys. |

### Existing agents (5) — roles unchanged, workers under the Engineer

`aria-frontend`, `aria-go-backend`, `aria-python-pipeline`, `aria-proto`,
`aria-security-reviewer`. Each gains a short team-protocol handoff section.
`aria-frontend`'s stale file-map lines (hardcoded-localhost claims superseded by
`lib/config.ts`) get corrected. `aria-security-reviewer`'s tool grant is verified
against its read-only contract (a Write/Edit discrepancy was observed between the
file frontmatter and the loaded config).

### Sub-agent model tiering (approved)

The 11 named leads are Opus 4.8. Sub-agents are tiered by task: judgment work
(verification, review, debugging, research analysis) on Opus; mechanical work
(grep sweeps, dedup, doc formatting) on Haiku/Sonnet.

## 5. Cycle pipeline

Trigger: Sucheet types **`/team`**. (A schedule may be added later once the loop is
proven; out of scope now.)

**Phase 1 — automatic, scripted, resumable:**
1. PM loads `docs/team/backlog.md`.
2. Idea Generator fans out lens sub-generators → candidates.
3. Dedup against backlog (rejected ideas never reappear; parked ideas surface with
   their existing briefs).
4. PM triages to the top 3–5.
5. One Researcher per idea in parallel; Security Team contributes a threat-model
   pre-check to each brief.
6. PM assembles the approval package.

**Touchpoint 1 — the approval gate:** the main session presents one page per idea
(idea, why now, research summary, effort, risk, PM recommendation). Sucheet
approves / rejects / parks each. Approval of an idea is the standing "go" for that
idea's entire build, including its commits.

**Phase 2 — automatic per approved idea (parallel across ideas, serialized when
plans overlap on files):**
1. Lead writes the file-by-file plan.
2. Engineer builds TDD in the `team/<idea-slug>` worktree via the specialists.
3. `make check` — red goes to the **Debugger** (root cause → minimal fix), never
   back to the Engineer to pile on code.
4. Lead confirms the diff matches the plan.
5. Code Reviewer runs (verified findings only); confirmed findings are fixed under
   the Debugger's minimal-fix discipline.
6. Security Team reviews; blockers loop back (see caps).
7. QA verifies in-browser with evidence.
8. Scribe syncs docs into the same branch.
9. Conventional commit(s), **one push**, PR to `integration` with DoD checklist,
   commit list, links to idea + research, QA evidence.
10. DevOps watches CI to green (one amended-fix + force-push attempt max).

**Touchpoint 2 — the final call:** PM posts the cycle report (PRs opened, CI
status, anything blocked and why, rough cost). Sucheet merges. A tiny
`chore(team): cycle record` housekeeping PR carries backlog/cycle-record updates.

## 6. Authority boundaries

**Standing authority once an idea is approved (scoped to team cycles):**
1. Create worktrees and `team/<idea-slug>` branches.
2. Commit to those branches — conventional format, authored as Sucheet, never any
   Claude attribution. *Approved relaxation:* per-commit message approval is
   replaced by batch review — the PR body lists every commit message.
3. Push `team/*` branches to origin. *Approved relaxation:* scoped push authority —
   `integration`, `main`, `dev` remain forbidden to the team, always.
4. Open PRs to `integration`.
5. Add a dependency **only** if named in the approved research brief (pinned +
   hashed per DEP rules). A mid-build dependency discovery = build blocked and
   reported, never silent.
6. Spend bounded test tokens during QA (see cost controls).

**Reserved to Sucheet, no exceptions, restated in every agent brief:**
- Merging any PR; promoting to dev/prod; approving/rejecting/parking ideas.
- Any touch of `backend/.env` or secrets.
- Deleting any file the approved plan didn't explicitly cover.
- Any push to a protected branch.

**Rails:** scope is frozen at approval (material scope change = build stops as
`blocked — scope change`); everything traceable (backlog links idea → research →
branch → PR); rules live in `docs/team/PROTOCOL.md` **and** in each agent file, so a
standalone-invoked agent obeys the same boundaries.

## 7. Cost controls

- **CI minutes:** one build = one push = one CI run. All fix rounds happen locally
  before anything leaves the machine; the full local gate (`make check` — the same
  four suites CI runs) must be green pre-push. CI failure → diagnose → one amended
  commit → one force-push (the existing `concurrency` group cancels the superseded
  run). Worst case two CI runs per build.
- **Agent tokens:** hard caps — max 5 ideas researched per cycle, max 3 parallel
  builds, max 3 fix rounds per build (across debugger/review/security combined).
  Hit a cap → stop and report. Dedup + persisted briefs mean nothing is researched
  twice. Sub-agent model tiering per §4.
- **Runtime API money:** QA exercises only impact-radius paths, scripted short
  interactions, ≤5 paid API calls per verification, zero paid calls when the change
  doesn't touch paid paths.
- **Deploys:** the team never deploys. Railway/Vercel activity only follows
  Sucheet's merges. Batched pushes also prevent per-push Vercel preview builds.

## 8. State & memory

All team state is versioned in the repo, human-readable:

- `docs/team/backlog.md` — every idea ever proposed: status (`proposed / approved /
  parked / rejected / building / pr-open / blocked / merged`), tag, links to brief,
  branch, PR; rejection reasons.
- `docs/team/research/<idea>-brief.md` — one brief per idea; survives parking.
- `docs/team/cycles/<date>.md` — one report per cycle, including rough cost.
- `docs/team/PROTOCOL.md` — the shared rulebook (handoffs, §6 boundaries, §7 caps,
  model tiers). One place to change the rules; all 16 agents reference it.

State reaches git via the end-of-cycle `chore(team): cycle record` PR.
Every team agent carries `memory: project` so learnings compound across cycles.

## 9. Failure handling

- **Agent dies mid-build:** PM retries once; second death → idea `blocked`,
  worktree preserved for inspection, surfaced in the cycle report.
- **Session interrupted mid-cycle:** durable state is on disk; phase 1 is a
  resumable workflow; next `/team` detects the unfinished cycle and resumes
  instead of restarting (and re-spending).
- **Parallel builds overlap on files:** Lead detects from plans; PM serializes.
- **CI red after the single push:** one amended-fix attempt; still red → PR flips
  to draft, `blocked`, in the report.
- **Blocked ideas never auto-retry.** Next cycle surfaces them to Sucheet with the
  reason; retrying is his call.

## 10. File-by-file implementation breakdown

**New (14):**

| File | Purpose |
|---|---|
| `.claude/agents/aria-pm.md` | Project Manager agent |
| `.claude/agents/aria-lead.md` | Project Lead agent |
| `.claude/agents/aria-engineer.md` | Project Engineer agent |
| `.claude/agents/aria-researcher.md` | Researcher agent |
| `.claude/agents/aria-security-team.md` | Security Team coordinator agent |
| `.claude/agents/aria-ideas.md` | Idea Generator agent |
| `.claude/agents/aria-code-reviewer.md` | Code Reviewer agent |
| `.claude/agents/aria-debugger.md` | Debugger agent |
| `.claude/agents/aria-qa.md` | QA Verifier agent |
| `.claude/agents/aria-scribe.md` | Docs Curator agent |
| `.claude/agents/aria-devops.md` | CI & Deploy Watcher agent |
| `.claude/skills/team/SKILL.md` | The `/team` command — two-phase cycle, gate, caps, resume |
| `docs/team/PROTOCOL.md` | Shared rulebook |
| `docs/team/backlog.md` | Seeded empty backlog (`research/` and `cycles/` are created by the first cycle) |

**Modified (6):**

| File | Change |
|---|---|
| `.claude/agents/aria-frontend.md` | Team-protocol section; fix stale localhost file-map lines |
| `.claude/agents/aria-go-backend.md` | Team-protocol section |
| `.claude/agents/aria-python-pipeline.md` | Team-protocol section |
| `.claude/agents/aria-proto.md` | Team-protocol section |
| `.claude/agents/aria-security-reviewer.md` | Team-protocol section; verify read-only tool grant |
| `CLAUDE.md` | List the team + `/team` in the Project Agents section |

**Dependencies:** none — markdown plus one skill. No libraries, no lockfile changes.

## 11. Risks

- Agent briefs are instructions, not code — behavior is strong but probabilistic.
  Mitigations: branch-name scoping, hard caps, PROTOCOL.md restated per agent, and
  the shakedown cycle.
- First-cycle Opus 4.8 cost is an estimate until one runs; caps bound the worst case.

## 12. Testing plan

The first `/team` run is a **shakedown cycle** with caps lowered to 2 ideas / 1
build, watched end-to-end, before trusting the pipeline at full size.

## 13. Decision log (from the design conversation)

| Decision | Choice |
|---|---|
| Approval gates | One gate: idea + research; PR merge is the final call |
| Trigger | Slash command (`/team`); schedule deferred until the loop is proven |
| Idea scope | Product + engineering, tagged; restructure-aware |
| Architecture | Hybrid: scripted phase 1, judgment-driven phase 2 |
| Extra agents | Code Reviewer, Debugger (requested); QA, Scribe, DevOps (recommended, accepted) |
| Rule relaxations | Batch commit review at the PR; push scope `team/*` only — both confirmed |
| Sub-agent models | Right-sized tiers: Opus leads, Opus judgment sub-agents, Haiku/Sonnet mechanical |
