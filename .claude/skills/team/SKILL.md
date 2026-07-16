---
name: team
description: Run one autonomous ARIA team cycle — ideas → research → your approval gate → parallel builds → PRs on integration. Two touchpoints only. Use when Sucheet types /team or asks to run the agent team.
---

# /team — one full team cycle

You (the main session) are the conduit between the team and Sucheet. Agents
cannot talk to him; you present, he decides, you relay. Rules, caps, and
authority: `docs/team/PROTOCOL.md` — read it before starting.

## 0. Preflight
- Working tree must be clean-ish (no uncommitted changes in files the team
  may touch). Not on main.
- **Shakedown:** if `docs/team/cycles/` does not exist or is empty, this is
  the first-ever cycle: lower caps to 2 ideas researched / 1 build, and
  tell Sucheet you're in shakedown mode.
- **Resume:** if the newest `docs/team/cycles/*.md` contains the line
  `status: incomplete`, offer Sucheet resume-vs-fresh before spending
  anything.

## 1. Phase 1 — ideas + research (automatic)
1. Read `docs/team/backlog.md` yourself and pass its full contents into
   the phase as context (workflow scripts cannot read files).
2. Run the phase as a Workflow (this skill is your authorization):
   - stage A: one `aria-ideas` agent invocation (it fans out its own lens
     sub-generators) → idea objects.
   - stage B (plain code in the script): drop ideas whose slug/title
     matches a backlog row.
   - stage C: PM triage — spawn `aria-pm` with the survivors + backlog →
     top 3–5 (or 2 in shakedown).
   - stage D: pipeline the chosen ideas → one `aria-researcher` each
     (parallel; each pulls its pre-check from `aria-security-team`).
3. Collect the approval package from `aria-pm`.
4. Write the cycle file `docs/team/cycles/<YYYY-MM-DD>.md` with
   `status: incomplete` and the phase-1 results, so a dead session can
   resume without re-spending.

## 2. The gate (touchpoint 1)
Present the package: one page per idea in plain English. Then
AskUserQuestion (multiSelect): approve / park / reject per idea. Record
every decision + reason in the backlog via `aria-pm`. If nothing is
approved: finish the cycle report, mark the cycle `status: complete`, stop.

## 3. Phase 2 — builds (automatic)
Spawn `aria-pm` to coordinate: per approved idea, Lead plan → Engineer TDD
build (worktree `team/<idea-slug>`) → red goes to Debugger → Lead
conformance → Code Reviewer → Security Team → QA evidence → Scribe doc
sync → single push → PR to integration → DevOps watches CI. Max 3 builds
parallel (1 in shakedown); overlapping builds serialized; 3 fix rounds per
build; blocked builds stop with preserved worktrees.

While PM coordinates, you relay nothing to Sucheet unless something goes
`blocked` — no play-by-play.

## 4. Report (touchpoint 2)
Relay PM's cycle report verbatim: PRs opened (links, CI status, QA
evidence), blocked items with reasons, rough cost. Mark the cycle file
`status: complete`. PM opens the `chore(team): cycle record` housekeeping
PR from `team/cycle-<date>`. Remind Sucheet: merging is his call.

## Hard rails (repeat of PROTOCOL, enforce as the conduit)
- Push scope: `team/*` branches only. Never integration/main/dev.
- Commit messages batch-reviewed at the PR (his standing relaxation for
  team cycles ONLY — everywhere else his global rules apply unchanged).
- Any cap hit or scope change → blocked + report, never improvise.
