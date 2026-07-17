# Research brief: ws-frame-validation

## Idea
- **Title:** Runtime-validate the WebSocket message boundary (FE-3)
- **Tag:** engineering
- **Pitch:** Right now every message the browser receives on the live WebSocket
  is run through `JSON.parse` into an untyped `any` value and then branched on by
  reading fields blind (`msg.type`, `msg.payload`, `t.is_final`...). A frame that
  parses as JSON but has the wrong shape either quietly poisons the app's state
  store or throws and gets swallowed with no log at all. This idea replaces that
  with a small "discriminated union + runtime guard": one place that checks each
  incoming frame against the handful of message shapes we actually accept, hands
  back a properly typed value, and logs (never silently swallows) anything it
  drops. Frontend-only. Closes binding rule FE-3.

## Fit
**What exists today**
- The boundary lives entirely in one file: `frontend/src/hooks/useWebSocket.ts`.
  Line 84 does `const msg = JSON.parse(event.data as string)` — that `msg` is
  `any`, which is exactly what FE-3 forbids ("No `any` at the WS boundary").
- The `onmessage` handler (lines 82–142) branches on `msg.type` for six cases:
  `aria_sleep`, `wake_word`, `vision_state` (or *no* type), `aria_interrupt`,
  `transcript`, `anchor_registered`. Everything else falls through and is ignored
  with no log.
- The wire envelope is **inconsistent**, and this is the load-bearing detail for
  the build:
  - `transcript` reads `msg.payload` directly (`const t = msg.payload; t.is_final`).
    If `payload` is missing, `t.is_final` throws → caught by the bare `catch {}`
    on line 139 → dropped with zero log.
  - `vision_state` and `anchor_registered` read `msg.payload ?? msg` — payload is
    sometimes nested, sometimes the frame *is* the payload.
  - `aria_interrupt` reads `msg.session_id` at the **envelope top level**, not
    inside `payload`.
- The store writes are unguarded: `setVisionFrame` (`ariaStore.ts:140-150`) spreads
  `frame.face_landmarks`, `frame.head_pose`, `frame.emotion`, `frame.timestamp`
  etc. straight into the store. A malformed `vision_state` frame writes `undefined`
  into `headPose`/`emotion`, which the avatar renderer then reads. (A white-screen
  is already prevented by the FE-2 error boundary, but the wrong-state / swallowed
  state-change failure mode is real.)
- The server side that produces these frames is authoritative for the shape:
  `backend/internal/server/messages.go` defines the `{type, payload}` envelope and
  the type constants; `backend/app/pipeline/audio_worker.py` emits `wake_word` /
  `aria_sleep`.

**What already does this well (in-repo prior art)**
- `frontend/src/spatial/useSpatialSync.ts:8-9` already uses a hand-written
  discriminated union (`{ type: "anchor_added"; ... } | { type: "anchor_removed"; ... }`)
  with a `satisfies` guard for its cross-tab BroadcastChannel. That is the exact
  pattern FE-3 asks for, already proven in this codebase — the WS boundary just
  never got the same treatment. No new concept to introduce.

**What changes**
- New file, e.g. `frontend/src/lib/wsMessages.ts`: the discriminated-union types
  for the six accepted frames plus a `parseWsFrame(raw: string): AriaWsMessage | null`
  guard that returns a typed message or `null` (and logs metadata on a drop).
- Modify `frontend/src/hooks/useWebSocket.ts`: replace the `JSON.parse`→`any`
  branching with a call to `parseWsFrame`, then a `switch` over the narrowed type.
  Removes the `any`; the bare `catch {}` becomes an explicit logged drop.
- Tests: new `frontend/src/lib/wsMessages.test.ts` (valid frames narrow correctly;
  malformed / unknown frames return null and log metadata only) and an added case
  in `frontend/src/hooks/useWebSocket.test.ts` for the drop path.
- **No file overlap with in-flight work.** A2 this cycle is a backend observability
  build; the in-flight CSP-nonce, whisper pre-bake, useVisionCapture device-follow
  and "frustrated" voice items touch none of these files. Parallelism-safe.
- Blast radius: contained to the one hook plus one new lib module. `useWebSocket`
  is a leaf consumer — nothing imports its internals except React mount.

## Prior art
- **Zod discriminated unions** (`z.discriminatedUnion`) are the industry-standard
  way to validate a tagged message boundary in TypeScript; MIT-licensed, zero
  runtime deps. Widely used for exactly this (WS / postMessage / API response
  validation).
- **Hand-written discriminated union + type guard** — the lighter option the FE-3
  rule text explicitly allows ("zod *or* a discriminated union + runtime guard"),
  and the pattern this repo already ships in `useSpatialSync.ts`. For ~6 fixed,
  internally-produced message shapes this is the proportionate choice; a schema
  library is more machinery than the problem needs.
- No external code is being copied, so there is no third-party licence to inherit
  beyond the optional dependency below.

## Dependencies
This list is the contract — the build may add nothing not named here.

- **Default / recommended: none.** Hand-written discriminated union + guard, matching
  the existing `useSpatialSync.ts` pattern. No package added.
- **Named fallback (discouraged): `zod@4.4.3`** — MIT licence, zero runtime
  dependencies, ~2 kB gzipped tree-shaken core (verified via `npm view zod` →
  4.4.3 / MIT). Named here *only* so that, if the build genuinely hits a wall with
  the hand-written guard, it has a pre-cleared, licence-checked option instead of a
  blocked build. If used it must be DEP-4 pinned + hashed in the lockfile.
  **Recommendation: do not add it** — six fixed message types do not justify a new
  runtime dependency, and the repo already has the union pattern.

## Effort & risks
**Effort: M** (leans S). The logic is small, but three things add care beyond a
trivial guard: (1) modelling the *actual, inconsistent* envelope shapes precisely,
(2) TDD tests for both the happy path and the drop path, (3) not regressing any
live frame. Scoped to structural checks it is closer to S.

**Top risks**
1. **Over-strict validation regresses live prod frames (highest).** The envelope is
   inconsistent — `transcript` reads `msg.payload`, `vision_state`/`anchor_registered`
   read `msg.payload ?? msg`, `aria_interrupt` reads top-level `msg.session_id`. A
   validator that assumes one uniform shape will start dropping frames that work
   today. Mitigation: model the observed shapes exactly and keep an explicit
   `default: log-and-drop` for genuinely unknown types.
2. **Per-frame CPU.** Vision frames carry large landmark arrays and can arrive at
   ~10–30 fps. Deep-validating every array element each frame is wasteful.
   Mitigation: validate structurally (right `type`, required top-level keys present
   and of the right primitive kind) rather than element-wise; vision frames are
   already dropped when the browser is the local producer (`visionCaptureActiveRef`),
   so they rarely reach the store anyway.
3. **PII in drop logs.** `transcript` payloads are the user's actual speech. A
   "logs drops" feature must log only metadata (`type` + a shape-error reason),
   never the raw payload/transcript text, or we leak PII into the browser console
   (and any log shipper). This is a build constraint, not optional.
4. **Dependency creep.** The temptation to reach for zod mid-build is real; DEP-4
   blocks any unnamed dep. Contained by naming zod above as a discouraged fallback.
5. **Future contract drift (minor).** A hand-written TS union is a fourth place a
   message shape lives (proto / Go / pydantic / TS), which sits in slight tension
   with API-1/API-2's "one source of truth." Flag as a follow-up (generate the TS
   union from the contract later), not a blocker now.

## Security pre-check
*Threat-model note. The `aria-security-team` sub-agent could not be spawned from
this researcher's tool set in this run (no Task/delegate tool available), so this
note was produced by the researcher directly and is flagged as such rather than
presented as that agent's verbatim output. It should be re-run by the security team
at the build gate.*

- **Trust boundary:** this is the client's inbound edge of an already-authenticated
  channel (Clerk token in the WS subprotocol, SEC-1; WSS in prod). The frame source
  is ARIA's own Go server, not an arbitrary internet peer, so the realistic threat is
  a **buggy or compromised backend, or a future multi-user broadcast bug**, not a
  MITM. Adding validation is a defense-in-depth improvement, net-positive.
- **Severity of the gap being closed:** low-to-moderate. The unvalidated
  `aria_interrupt` path reads `msg.session_id` and, on a match, aborts the local
  user's cognition and fires an interrupt event — validating that `session_id` is a
  string and matches the current session removes an easy way for a malformed/spoofed
  frame to disrupt a session. `vision_state`/`transcript` gaps are reliability
  (wrong or swallowed state), not privilege escalation.
- **New attack surface introduced:** effectively none for the hand-written guard
  (no dependency, no new I/O). If zod were added: MIT, zero deps, well-audited, no
  known critical CVE at 4.4.3; our schemas are simple discriminated unions with no
  user-supplied regex, so no ReDoS exposure. Supply-chain cost = one more pinned +
  hashed dep.
- **No changes to** auth, owner-scoping, secrets, data access, gRPC binds, or any
  server code. This is not a SEC-3 / DATA trust-boundary change.
- **One hard build guardrail:** dropped-frame logs must be metadata-only (`type` +
  reason). Never log the raw payload — `transcript` frames are user speech (PII).
- **Verdict: LOW risk, security-positive.** Proceed; security team re-checks the
  drop-logging implementation at the build gate.

## Red-team verdict
*The adversarial Opus sub-agent likewise could not be spawned from this tool set;
the following is the researcher's own best-effort attempt to KILL the idea, run
across the four required angles and reported honestly.*

- **Wrong-priority?** Tempting kill: FE-3 is a MUST rule that isn't even tracked in
  `STANDARDS_DEBT.md`, so arguably nobody has felt its absence — and part of the
  "reliability" upside is already covered (vision frames are dropped when the browser
  produces them locally; FE-2 stops a white-screen). But this understates it: the
  `transcript`, `aria_interrupt` and `anchor_registered` paths are *not* covered by
  the vision drop and do reach the store / trigger actions, and line 84 is a literal
  `any` at the boundary the rule names. It is a genuine live violation, cheap to fix.
  Not killed.
- **Hidden-complexity?** Strongest kill angle: the envelope is inconsistent
  (payload-vs-frame for vision/anchor, top-level `session_id` for interrupt), so a
  naive union validator will *under*-validate (pointless) or *over*-validate and drop
  frames that work in prod today (a regression). This is real and must shape the build
  plan — but it is a known, bounded hazard with a clear mitigation (model observed
  shapes + explicit log-and-drop default), not a reason to abandon.
- **Better-alternative?** The obvious "just add zod" is the *worse* alternative here;
  the leaner hand-written guard is already the recommended path and already exists in
  the repo (`useSpatialSync.ts`). The idea pre-empts its own strongest counter.
- **Conflicts-with-restructure?** No file overlap with A2 (backend) or any in-flight
  item. Only soft tension: API-1/API-2 want one source of truth for contracts, so a
  hand-written TS union is a small artifact that may later be regenerated. Minor,
  flagged as follow-up.
- **Verdict: SURVIVES, with conditions.** Build it as a hand-written guard (no dep);
  the two non-negotiable build constraints are (a) match the real, inconsistent wire
  shapes with a log-and-drop default so no live frame regresses, and (b) log drop
  metadata only, never raw payloads.

## Recommendation
**Build.** This closes a second binding MUST rule (FE-3) that is a real, live gap —
there is a literal `any` at the WebSocket boundary and unchecked writes straight into
the app's state store — and it does so with a small, frontend-only change that reuses
a discriminated-union pattern the codebase already ships. It is disjoint from the
backend A2 work and every in-flight item, so it runs safely in parallel. Do it with
**no new dependency** (a hand-written union guard); zod is named only as a
pre-cleared fallback and should not actually be added for six fixed message types.
The build must honour two constraints or it does more harm than good: mirror the
existing (inconsistent) envelope shapes so no working frame gets dropped, and log
only frame metadata on a drop, never the raw transcript payload (that text is the
user's speech). With those two guardrails this is a low-risk, high-fit hardening win.
