# ARIA Team Backlog

Single source of truth for every idea ever proposed. One row per idea,
forever. Statuses: `proposed | approved | parked | rejected | building |
pr-open | blocked | merged`. Rejected ideas keep their reason in Notes —
the Idea Generator must never re-propose them. See `docs/team/PROTOCOL.md`.

| ID | Title | Tag | Status | Brief | Branch | PR | Notes |
|----|-------|-----|--------|-------|--------|----|-------|
| A1 | Wire ARIA's emotion into the TTS request | product | pr-open | research/emotion-matched-voice-brief.md | team/emotion-matched-voice | #126 | 2026-07-16 shakedown: CHOSEN top-2 for research. Verified orphaned backend — useTTS.ts:53 posts `{text}` only; tts_route.py + handler.go already accept `emotion`. S effort, no trust-boundary change, no restructure conflict. 2026-07-17: APPROVED by user, flagship build (shakedown build cap=1). Built on team/emotion-matched-voice off integration; Lead CONFORMS, code-review APPROVE, security PASS, QA VERIFIED (2 paid calls). PR #126 open to integration, CI green (run 29556283295). Awaiting user merge. 0 fix rounds. |
| A2 | Populate token-cost/cache-hit metric | engineering | approved | research/token-cache-observability-brief.md | — | — | 2026-07-16 shakedown: CHOSEN top-2 for research. Verified: record_token_cost has zero callers; llm.py never reads response.usage. Backend-only, additive, verifies just-shipped prompt-caching ROI. 2026-07-17: APPROVED by user but QUEUED — shakedown build cap=1, A1 built first. Approved-and-queued for the top of next cycle; no build this cycle. |
| A3 | Streaming TTS playback (chunked) | engineering | parked | — | — | — | 2026-07-16 shakedown: DEFERRED at triage (not researched). M effort; MediaSource/Web-Audio chunked playback is fiddly/higher-risk — not shakedown-safe. Revisit next cycle. |
| A4 | Forget a specific stored memory fact | product | parked | — | — | — | 2026-07-16 shakedown: DEFERRED at triage (not researched). M effort; new owner-scoped DELETE endpoint touches the trust boundary (mandatory security review) and brushes Phase 3 data-model work. |
| A5 | Episodic-recall panel (surface episodic memory) | product | parked | — | — | — | 2026-07-16 shakedown: DEFERRED at triage (runner-up, not researched). Verified orphaned endpoint, frontend-only, near-zero risk. Held only to avoid two frontend builds this shakedown; top of next cycle. |
| A6 | Avatar gaze tracking (eye contact) | product | parked | — | — | — | 2026-07-16 shakedown: DEFERRED at triage (not researched). M effort canvas render-loop polish; lower priority than reliability/observability for a shakedown. |
| A7 | Bounded retry on the ElevenLabs call | engineering | parked | — | — | — | 2026-07-16 shakedown: DEFERRED at triage (not researched). Strong S/low-risk REL-2 fix (verified: no retry today), but lower felt value than the two picks. Strong candidate for next cycle. |
| A8 | Persist visible conversation across refresh | engineering | parked | — | — | — | 2026-07-16 shakedown: DEFERRED at triage (not researched). Small client-only papercut fix; lower value than the picks. Park for next cycle. |
