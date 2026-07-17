# Research Brief: emotion-matched-voice

## Idea
- **Title:** Wire ARIA's own emotion into the TTS request so her voice actually emotes
- **Tag:** product
- **Pitch:** ARIA already has a 12-profile ElevenLabs prosody engine
  (`backend/app/pipeline/voice_engine.py`) and a full emotion-carrying request
  chain — `frontend` → Go `/api/tts` handler → Python `tts_route.py` — that all
  accept an `emotion` field. The one broken link is the browser: `useTTS.ts`
  `speak()` posts `body: JSON.stringify({ text })` (line 53) and never sends
  ARIA's mood. So the prosody engine is orphaned — every line ARIA speaks uses
  the flat default voice regardless of how she "feels." Thread her own mood into
  the TTS POST and the existing engine lights up.

## Fit (what exists, what changes)
**What already exists (verified against current code):**
- `frontend/src/hooks/useTTS.ts:39` — `async function speak(text: string)`; the
  request body at `:53` is `{ text }` only. `speakRef` (`:13`) is typed
  `((text: string) => Promise<void>) | null`.
- `frontend/src/hooks/useCognition.ts` (~`:152`) — the `onResponse` callback
  already receives the cognition `data` payload; it just doesn't forward
  `data.avatar_emotion` to the speak call.
- `frontend/src/app/page.tsx:98` and `frontend/src/components/ChatPanel.tsx:24`
  pass `speak` / `speakRef` straight through — no change needed.
- `backend/app/pipeline/voice_engine.py` — `EMOTION_VOICE_PROFILES` (12 profiles)
  + `apply_prosody_tags` + `voice_settings`. The Go `/api/tts` handler and
  Python `tts_route.py` already accept and thread `emotion`.

**Verified correctness traps (the naive one-field pitch is wrong):**
1. **v3 audio tags do not work on the configured model.** `voice_engine.py`
   sets `MODEL_ID = "eleven_turbo_v2_5"` and `apply_prosody_tags` prepends v3
   audio tags (`[cheerfully]`, `[softly]`, `[thoughtful pause]`). Audio tags are
   **eleven_v3-only / experimental**; on turbo_v2_5 they may be **read aloud**.
   The `voice_settings` half (stability / style / similarity_boost) genuinely
   works on turbo. So the build must skip `apply_prosody_tags` on turbo while
   still applying `voice_settings`.
2. **`avatar_emotion` is ARIA's mood, derived in Go.** Python's cognition
   response does not itself set `avatar_emotion`; Go's
   `internal/cognition/client.go` `suggestAvatarEmotion()` maps
   `symbolic_inference` to one of {frustrated, fearful, sad, angry, disgusted,
   neutral, happy, surprised}, and the payload reaching the frontend carries
   `data.avatar_emotion`. **This** is the field to send.
3. **Do NOT read the store.** `frontend/src/store/ariaStore.ts` `setVisionFrame`
   (~`:147`) overwrites `avatarEmotion` with the **user's webcam facial emotion**
   every frame, so `store.avatarEmotion` is racy and wrong-sourced, and
   `store.emotion` is the user's face, not ARIA's. Correct source is
   `data.avatar_emotion` threaded through `onResponse` into `speak()`.

**What changes (small, cross-stack):**
- `frontend/src/hooks/useTTS.ts` — `speak()` gains an optional `emotion` arg,
  added to the POST body; widen the `speakRef` type. Degrade cleanly when
  absent (send text only).
- `frontend/src/hooks/useCognition.ts` — widen `onResponse` to also pass
  `data.avatar_emotion` into the speak call.
- `frontend/src/hooks/useTTS.test.ts` (new) — assert the POST body carries
  `emotion` when supplied and omits/degrades cleanly when absent (TDD red→green).
- `backend/app/pipeline/voice_engine.py` — one-line guard to skip
  `apply_prosody_tags` on the turbo model; `voice_settings` still carries the
  emotion. Cover with a Python test.

**Deliberately NOT changed:** proto / pydantic contract / Go handler — all
already accept `emotion`. Call sites `page.tsx:98` and `ChatPanel.tsx:24` pass
through unchanged.

## Prior art
- ElevenLabs docs: audio tags (`[cheerfully]` etc.) are an `eleven_v3` feature;
  `eleven_turbo_v2_5` supports `voice_settings`-based prosody but not inline
  tags. This is why the turbo guard is required, not optional.

## Dependencies (the contract list)
**NONE.** No new library on either side. Frontend uses `fetch` already in
`useTTS.ts`; backend change is a conditional around an existing call.

## Effort & risks
**Effort: S (small, cross-stack).** ~1 field + type widening on the frontend,
one new frontend test; a one-line guard + one test on the Python side. Two
specialists (`aria-frontend`, `aria-python-pipeline`) over disjoint files.

**Top risks:**
1. **Wrong emotion source.** Sending `store.emotion` (user's face) or
   `store.avatarEmotion` (racy) instead of `data.avatar_emotion` would make ARIA
   emote the user's mood or a stale one. Correctness hinges on Trap 2/3 above.
2. **Tags spoken aloud.** Without the turbo guard ARIA may literally say
   "cheerfully." The guard is a hard requirement, not a nicety.
3. **`frustrated` has no profile** → flat "idle" fallback. Out of scope: mapping
   it is a separate future idea; degrading to flat here is acceptable.
4. **Silent degrade.** If `data.avatar_emotion` is absent, speak must send
   text-only and behave exactly as today — covered by the "degrades cleanly"
   test.

## Security pre-check
> **Process note (honest):** the researcher environment exposed no agent-spawn
> tool, so `aria-security-team` was not launched at research time. The note
> below is the inline stand-in and **must be re-run by `aria-security-team` at
> the build gate** before the PR opens.

**Threat-model note (emotion-matched-voice):**
- **New trust-boundary surface: none.** No new route, no new auth, no new
  external call shape, no secret handling. The `emotion` value is a short enum
  string chosen server-side (Go) from a fixed set; the frontend only forwards a
  value it already received.
- **Data sensitivity: low.** `emotion` is an operational label, not user content
  or PII. No owner-scoped data path touched (SEC-3 / DATA-6 N/A).
- **Injection surface: negligible.** `emotion` is a bounded label consumed as a
  dict key into `EMOTION_VOICE_PROFILES`; an unknown value degrades to the
  default profile. No string is interpolated into a prompt, shell, or query.
- **Fail-closed / availability.** TTS already degrades to browser speech on any
  failure; adding an optional field cannot make the path less safe.
- **Verdict: approve, LOW.** No gate-worthy change; confirm at build.

## Red-team verdict
> **Process note (honest):** no separate Opus adversary was spawnable at research
> time; this is the researcher's own adversarial pass under a "try to kill it"
> mandate across the four kill lenses.

- **Wrong-priority?** Weak kill. This activates an already-built, already-shipped
  engine that is 100% dormant — high visible product value (ARIA finally sounds
  like she feels something) for S effort. Survives.
- **Hidden complexity?** Partial hit, not fatal. Three real traps (turbo tags,
  Go-derived source, racy store) — all named, all S-effort, none escalating to M.
  Survives.
- **Better alternative?** Weak kill. The only alternative is doing nothing or
  server-side plumbing that already exists. The missing piece is genuinely the
  one browser field. Survives.
- **Conflicts-with-restructure?** No. Frontend wiring + a one-line Python guard;
  no contract change, no shared files with in-flight restructure work. Survives.
- **Overall: NOT killed.** Small, high-value, low-risk — provided the three
  correctness traps are honored.

## Recommendation
**Build.** Near-ideal shakedown pick: a dormant, fully-built prosody engine one
browser field from live, with clear product value. The build must honor three
correctness bars: (1) send `data.avatar_emotion` (ARIA's Go-derived mood), never
the store; (2) guard `apply_prosody_tags` off on `eleven_turbo_v2_5` so tags are
not spoken aloud; (3) degrade cleanly to text-only when emotion is absent. No new
dependency, no contract change, no trust-boundary surface. `frustrated`→profile
mapping stays out of scope as a future idea.
