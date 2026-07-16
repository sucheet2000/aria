# ARIA Agent Team Protocol

The shared rulebook for the ARIA agent team. Every team agent references this
file; when an agent brief and this file conflict, this file wins. When this
file conflicts with `CLAUDE.md` or `docs/STANDARDS.md`, those win.

## Roster

**Team agents** (all Opus 4.8, all may spawn sub-agents):
- `aria-pm` — cycle owner: backlog, triage, approval package, phase-2 coordination, cycle report
- `aria-lead` — file-by-file build plans; plan-conformance diff check; overlap detection
- `aria-engineer` — TDD builds in worktrees via the specialists; never fixes its own red builds
- `aria-researcher` — research briefs: feasibility, codebase fit, deps, risks; adversarial red-team
- `aria-security-team` — threat-model pre-check at research; full review at build
- `aria-ideas` — lens-based idea generation, tagged `product` | `engineering`
- `aria-code-reviewer` — standards ratchet, minimal-diff, verified findings
- `aria-debugger` — sole fixer of red builds; root cause first, smallest fix
- `aria-qa` — drives the real app in a browser; evidence attached to the PR
- `aria-scribe` — docs sync in the same PR; backlog + cycle records
- `aria-devops` — one-push policy, CI watch, deploy watch after merges

**Specialists** (workers under aria-engineer): `aria-frontend`,
`aria-go-backend`, `aria-python-pipeline`, `aria-proto`,
`aria-security-reviewer` (read-only, spawned by aria-security-team).

## The cycle

Phase 1 (automatic): backlog load → idea generation (lens fan-out) → dedup
against backlog → PM triage to top 3–5 → parallel research (one researcher
per idea, security pre-check included) → approval package.

Gate (touchpoint 1): the user approves / rejects / parks each idea. Approval
is the standing "go" for that idea's entire build, including its commits.

Phase 2 (automatic, per approved idea): Lead plan → Engineer TDD build in a
`team/<idea-slug>` worktree → red `make check` goes to the Debugger →
Lead conformance check → Code Reviewer → Security Team → QA in-browser
evidence → Scribe doc sync → conventional commits, ONE push, PR to
`integration` → DevOps watches CI to green.

Report (touchpoint 2): PM's cycle report; the user merges. Backlog/cycle
records land via a `chore(team): cycle record` PR.

## Authority

After an idea is approved, the team MAY without asking:
1. Create worktrees and `team/<idea-slug>` branches.
2. Commit to those branches — Conventional Commits, authored as Sucheet,
   never any Claude/AI attribution. Commit review is batched at the PR:
   the PR body lists every commit message.
3. Push `team/*` branches to origin. Nothing else, ever.
4. Open PRs to `integration` (DoD checklist, commit list, links to idea +
   research, QA evidence).
5. Add a dependency ONLY if named in the approved research brief, pinned +
   hashed per DEP rules. Mid-build dependency discovery = build blocked.
6. Spend bounded QA tokens (see Caps).

The team may NEVER: merge a PR; push `integration`/`main`/`dev`; promote to
dev/prod or deploy; touch `backend/.env` or any secret; delete a file the
approved plan didn't explicitly cover; change scope (material scope change =
stop, mark `blocked — scope change`, report).

## Caps

- Max 5 ideas researched per cycle.
- Max 3 parallel builds.
- Max 3 fix rounds per build (debugger + review + security combined).
- QA: ≤ 5 paid API calls per verification; zero when the change doesn't
  touch cognition/TTS paths.
- One push per build, plus at most one amended force-push after CI diagnosis.
- Cap hit → stop, mark `blocked`, report. Never loop.

## Model tiers

Team agents: Opus 4.8. Judgment sub-agents (verification, review, debugging,
research analysis): Opus. Mechanical sub-agents (grep sweeps, dedup,
formatting, doc sync): Haiku or Sonnet.

## Handoff format

Every delegation states: **GOAL** (one sentence), **SCOPE** (exact files),
**CONSTRAINTS** (what must not change), **DONE-WHEN** (verifiable condition).
Every report returns: **WHAT CHANGED** (file:line), **EVIDENCE** (command +
actual output), **CONCERNS** (anything the next agent must know).

## Statuses

`proposed | approved | parked | rejected | building | pr-open | blocked | merged`

Rejected ideas keep their reason in the backlog and are never re-proposed.
Blocked ideas never auto-retry; they surface to the user next cycle.

## State files

- `docs/team/backlog.md` — every idea ever proposed, one row forever.
- `docs/team/research/<idea>-brief.md` — one brief per idea; survives parking.
- `docs/team/cycles/<YYYY-MM-DD>.md` — one report per cycle, incl. rough cost.

PM and Scribe maintain these; they reach git via the end-of-cycle
`chore(team): cycle record` PR.
