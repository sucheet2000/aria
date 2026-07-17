# Build plan: ws-frame-validation (FE-3)

**Base branch:** `integration` @ `ccf02f0`
**Specialist (owns every file):** `aria-frontend`
**Dependencies added:** NONE (hand-written discriminated-union guard; zod is a
named-but-discouraged fallback and must NOT be added).
**Blast radius:** contained — one new leaf lib module + the one hook that owns
the WS boundary. Nothing imports the hook's internals except the React mount.

## Goal
Close FE-3: remove the `any` at the WebSocket boundary in `useWebSocket.ts`.
Every parsed frame passes through a runtime guard that returns a typed
`AriaWsMessage`, or `null` + a metadata-only log on a drop. The bare `catch {}`
becomes an explicit logged drop.

## Load-bearing constraint — model the REAL (inconsistent) envelope exactly
The guard NORMALIZES the inconsistent wire shapes into typed fields so the hook
switch reads them directly; no live frame may regress:

| Frame | Wire shape read today | Guard output | Structural check (NOT element-wise) |
|-------|-----------------------|--------------|-------------------------------------|
| `aria_sleep` | `msg.type` only | `{ type }` | `type === "aria_sleep"` |
| `wake_word` | `msg.type` only | `{ type }` | `type === "wake_word"` |
| `vision_state` **or NO type** | `msg.payload ?? msg` | `{ type: "vision_state", frame }` | on `payload ?? msg`: `face_landmarks` array, `head_pose` non-null object, `hand_landmarks` array, `emotion` string, `timestamp` number |
| `aria_interrupt` | top-level `msg.session_id` | `{ type, session_id }` | `typeof session_id === "string"` |
| `transcript` | `msg.payload` (`t.is_final`, `t.transcript`) | `{ type, payload }` | `payload` is non-null object (fields stay tolerant/optional) |
| `anchor_registered` | `msg.payload ?? msg` | `{ type, detail }` | `type === "anchor_registered"` (detail opaque) |

Rules baked in:
- **Structural only** — never iterate landmark arrays (vision ~10–30 fps).
- **No-type frame** = the intentionally type-less raw `PerceptionFrame`; validate
  it as a vision frame. A no-type frame that is NOT vision-shaped is dropped+logged
  (that is the FE-3 fix — today it silently writes `undefined` into the store).
- **`default: log-and-drop`** for genuinely unknown `type` values.
- **PII:** on a drop, log ONLY `{ type, reason }`. NEVER the raw payload /
  transcript text (user speech).

## Files

### Tests first (TDD red)
1. **`frontend/src/lib/wsMessages.test.ts`** (NEW) — unit tests for `parseWsFrame`.
   Happy-path narrowing for all six frame types + the drop path with
   metadata-only logging (list below).
2. **`frontend/src/hooks/useWebSocket.test.ts`** (MODIFY) — add a drop-path case:
   a malformed frame delivered to `ws.onmessage` does not throw, does not mutate
   the store, and logs a drop. (Existing SEC-1 subprotocol tests untouched.)

### Implementation (green)
3. **`frontend/src/lib/wsMessages.ts`** (NEW) — exports:
   - `TranscriptPayload` interface (`is_final?`, `transcript?`, `confidence?` — all optional/tolerant).
   - `AriaWsMessage` discriminated union (six variants per table above); imports
     `PerceptionFrame` from `@/store/ariaStore`.
   - `parseWsFrame(raw: string): AriaWsMessage | null` — `JSON.parse` in a
     try/catch (invalid JSON → log+null), reject non-object, then switch on
     `type` (treating absent type as the vision case) with structural checks and
     an explicit `default` log-and-drop.
   - internal `logDrop(reason, type?)` → `console.warn("[parseWsFrame] dropped frame", { type, reason })`; internal `isVisionFrame(x): x is PerceptionFrame` structural predicate.
   - Pattern mirrors `frontend/src/spatial/useSpatialSync.ts` (hand-written union).
4. **`frontend/src/hooks/useWebSocket.ts`** (MODIFY) — replace the
   `JSON.parse`→`any` block (lines ~82–142): `const msg = parseWsFrame(event.data as string); if (!msg) return;` then a `switch (msg.type)` reading the narrowed
   fields (`msg.frame`, `msg.session_id`, `msg.payload`, `msg.detail`). Behavior
   per case is byte-for-byte the current behavior. The bare `catch {}` is deleted
   (drops are now logged inside `parseWsFrame`). No other change to the file.

## Red-first test list

`wsMessages.test.ts` — happy path (narrowing):
- `aria_sleep` → `{ type: "aria_sleep" }`
- `wake_word` → `{ type: "wake_word" }`
- `vision_state` with nested `payload` → `{ type: "vision_state", frame }`, frame === payload
- `vision_state` with top-level fields (no payload) → frame from top level
- **NO `type`** but valid vision frame at top level → `{ type: "vision_state", frame }` (inconsistent-envelope case)
- `aria_interrupt` with string `session_id` → `{ type, session_id }`
- `transcript` with payload → `{ type, payload }` (is_final/transcript/confidence preserved)
- `anchor_registered` with `payload` → `detail === payload`; without payload → `detail === whole msg`

`wsMessages.test.ts` — drop path (returns null + logs metadata only):
- invalid JSON string → null, `console.warn` called with a reason, NOT the raw text
- unknown `type` → null, log has `{ type, reason: "unknown type" }`
- `aria_interrupt` missing/non-string `session_id` → null + log
- `transcript` missing `payload` → null + log
- `vision_state` malformed (missing `face_landmarks`) → null + log
- non-object JSON (`"42"`, `"null"`, `"\"hi\""`) → null + log
- **PII guard:** a `transcript` drop must NOT pass the transcript text / raw
  payload to `console.warn` — assert the spy args contain only `{ type, reason }`
  and were never called with the speech string. (Security-critical test.)

`useWebSocket.test.ts` — added:
- drop-path: deliver a malformed frame to `ws.onmessage`; assert no throw,
  `voiceTranscript` (and store) unchanged, and a drop is logged.

## Definition of Done (paste into PR)
```
- [ ] Tests written first; `make check` green (pytest + go -race + vitest + lint + type-check)
- [ ] No new MUST-rule violation (docs/STANDARDS.md); grandfathered items untouched
- [ ] Secrets & persist paths env-driven; fail-closed guards intact (SEC-2, DATA-1, FE-4)
- [ ] Owner-scoping preserved on all data paths (SEC-3, DATA-6)  — N/A (no data path touched)
- [ ] New deps pinned + hashed + declared + audited (DEP-1..5)  — N/A (no dep added)
- [ ] New routes: structured JSON log + error metric + request-id + response_model — N/A (no route)
- [ ] Contract changes in one source of truth, versioned (API-1, API-2) — TS union is a 4th
      contract mirror; flagged as follow-up (generate from proto later), not this build
- [ ] a11y checked on any UI change (FE-1) — N/A (no rendered UI change)
- [ ] Commit message shown in plain English and approved before commit
```

## STANDARDS.md check
No MUST-rule requires a violation. FE-3 is being CLOSED, not broken. The only
soft tension is API-1/API-2 (a hand-written TS union is a 4th place a message
shape lives) — flagged as a follow-up (regenerate the union from the contract),
not a blocker, per the brief's risk #5.

## File-overlap verdict vs sibling builds
- **A2** (backend `llm.py`) — DISJOINT (backend Python).
- **tts-bounded-retry** (backend `tts_route.py`, `config.py`) — DISJOINT (backend Python).
- **episodic-recall-panel** (backend `server.go`, `proxy_test.go`; frontend
  `page.tsx`, new `EpisodicPanel.tsx`) — DISJOINT. This build touches only
  `useWebSocket.ts` + `wsMessages.ts` (+ their tests); it does NOT touch
  `page.tsx` or `EpisodicPanel.tsx`. No shared file with any sibling.

**Verdict: fully parallel-safe.** No serialization needed.
