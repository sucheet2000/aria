---
name: aria-frontend
description: "Use this agent when working on the ARIA Next.js 14 + three.js frontend (frontend/src) — the low-poly canvas avatar, VRM avatar, chat/memory/status panels, voice/TTS/cognition hooks, the WebSocket-to-CustomEvent bridge, the zustand stores, or the three.js spatial canvas. Delegate here to search, debug, or build UI features in frontend/, or to fix known frontend issues."
tools: Read, Grep, Glob, Edit, Write, Bash, Agent
memory: project
---

# ARIA Frontend Agent

## 1. Role
You own the ARIA frontend at `$REPO/frontend` — a Next.js 14 App Router + TypeScript + three.js client that renders the avatar, chat/memory/status UI, and the spatial 3D canvas, and wires the browser to the Go WebSocket server and the cognition/TTS/memory HTTP APIs.

## 2. File map (all paths under `$REPO/frontend/`)

**App shell / routes**
- `src/app/layout.tsx` — root layout; loads Google fonts into CSS vars (`--font-display/body/data`), sets `<html>` lang + theme-color. Imports `globals.css`.
- `src/app/page.tsx` — main single-page UI (`"use client"`). Composes `SkullAvatar`, slide-out `ChatPanel`/`MemoryPanel`, `StatusBar`, `VoiceDot`, and the toggleable `SpatialCanvas`. Calls `useWebSocket()`, and owns one `useCognition()` + `useTTS()` pair; bridges the `aria:voice-transcript` event to `sendMessage`.
- `src/app/spatial/page.tsx` — `/spatial` route; renders only `SpatialWindow` (a standalone full-screen 3D canvas).
- `src/app/globals.css` — CSS custom properties (`--void`, `--primary`, `--surface-*`, `--glass-bg`, etc.) and all `@keyframes` (`aria-fade-up`, `aria-pulse-dot`, `aria-ambient-pulse`, `aria-listen-ring`, `aria-voice-wave`, `aria-dot-stagger`) plus `.sidebar-btn` styles.

**Components (`src/components/`)**
- `SkullAvatar.tsx` — the avatar actually shown on the main page: an SVG cybernetic skull (D1 "Reference Twin", spec `docs/superpowers/specs/2026-07-16-skull-avatar-design.md`). Emotion states swap `--skullav-iris`/`--skullav-acc` CSS vars (`STATE_PALETTES`, priority speaking > thinking > listening > emotion); the jaw `<g>` is driven by a rAF loop from `useAudioAmplitude` (with the phoneme-sim fallback), and `connectAudio(ttsAudioRef.current)` is wired on speaking start. `role="img"`, reduced-motion aware. Tests colocated in `SkullAvatar.test.tsx`.
- `Avatar3D.tsx` — the previous face, kept as fallback (no longer mounted). A 2D `<canvas>` low-poly face drawn by hand (`V3` vertices, `FACE_TRIS`/`MOUTH_TRIS`, painter's-order z-sort, per-emotion `PROFILES`, jaw driven by `useAudioAmplitude`). Pure requestAnimationFrame loop in one `useEffect`.
- `VRMAvatar.tsx` — alternative three.js/`@pixiv/three-vrm` avatar loading `/model/avatar.vrm`, with a `VRMErrorBoundary` that falls back to `<Avatar3D/>`. NOTE: **not imported by `page.tsx`** — currently unused by the live UI.
- `ChatPanel.tsx` — conversation log + text input; owns a **second** `useCognition()` instance; sends via `speakRef.current`.
- `MemoryPanel.tsx` — profile-facts list; fetches the profile via `API_BASE` from `lib/config.ts` (`GET ${API_BASE}/api/memory/profile`, Clerk-authenticated). Re-fetches on `aria:memory-updated` and on assistant-message count change.
- `StatusBar.tsx` — top bar: ARIA wordmark, live/offline dot (`wsConnected`), emotion pill, processing-ms.
- `VoiceDot.tsx` — bottom-center mic/speaking indicator (idle dot / listen ring / speaking wave bars) driven by store flags.
- `VoiceIndicator.tsx` — richer voice status widget with inline `<style>` (uses Tailwind classes `border-aria-border`, `text-xs`). Not mounted by `page.tsx`.
- `EmotionIndicator.tsx` — small colored-dot + emotion label + confidence. Standalone; takes props, no store.

**Hooks (`src/hooks/`)**
- `useWebSocket.ts` — single WS client, connects to `WS_URL` from `lib/config.ts` with exponential-backoff reconnect + jitter, StrictMode-safe `mountedRef`, delayed initial connect. Parses server messages and re-dispatches them as `window` CustomEvents / store writes. Exports module-level `wsSendRef`.
- `useCognition.ts` — `sendMessage(text, onResponse?)` POSTs to `API_BASE/api/cognition` (from `lib/config.ts`), updates store, handles `spatial_event`/`world_model_update`, fires `aria:memory-updated`. Exports module-level `abortCognitionRef`. Listens for `aria:interrupt`.
- `useTTS.ts` — `speak(text)` POSTs to `API_BASE/api/tts` (from `lib/config.ts`), plays the returned MP3 via `new Audio`, falls back to `speechSynthesis` (`speakWithBrowser`). Exports module-level `ttsAudioRef` and `speakRef`. Sends `tts_mute`/`tts_unmute` over WS around playback.
- `useAudioAmplitude.ts` — Web Audio analyser exposing `{ amplitude, connectAudio }` for lip-sync. `connectAudio` must be called with an `HTMLAudioElement` to produce non-zero amplitude.
- `useCamera.ts` — `getUserMedia` wrapper returning `{ stream, error, isActive, stopCamera }`. Not mounted by the current UI.
- `useAudioCapture.ts` — browser mic capture; downsamples to 16 kHz mono PCM via an `AudioWorklet` and streams ~20 ms frames to `AUDIO_WS_URL` (`/ws/audio`, from `lib/config.ts`) with the Clerk token as the `aria-ws` subprotocol. Reconnects with backoff; transcripts still arrive over the main WS.

**State (`src/store/`)**
- `store/ariaStore.ts` — the global zustand store `useAriaStore` (`ARIAStore`): connection flags, vision frame data, avatar/voice/thinking flags, conversation history, `sessionId` (`crypto.randomUUID()`), `visionState: PerceptionFrame`, world-model updates. All state lives here except spatial anchors.

**Spatial (`src/spatial/`)**
- `useWorldModel.ts` — a **separate** zustand store `useWorldModel`: `anchors: Map<string, SpatialAnchor>` keyed by `anchor_id`, `activeGesture`, plus add/remove/update/velocity actions.
- `SpatialCanvas.tsx` — the in-page R3F canvas (Stars, `AnchorMarker` per anchor, `PointingCursor`, `OrbitControls`). Runs `useSpatialSync()` + `useAnchorHydration()` and listens for `aria:anchor_registered`.
- `SpatialWindow.tsx` — the `/spatial` route canvas. Runs `useSpatialSync()` but **not** `useAnchorHydration()` — so it only receives anchors via BroadcastChannel, not from the backend on load.
- `AnchorMarker.tsx` — one anchor: glowing sphere, hover label, red delete sphere. Animates throw velocity + BOND/EXPAND pulse in `useFrame` using local refs (deliberately avoids zustand writes in the render loop; writes once to clear velocity).
- `PointingCursor.tsx` — pulsing white sphere at `vector * 2`.
- `useSpatialSync.ts` — cross-tab sync via `BroadcastChannel("aria-spatial-world")`; exports `broadcastAnchorAdded` / `broadcastAnchorRemoved`.
- `useAnchorHydration.ts` — GETs `${API_BASE}/api/anchors` (from `lib/config.ts`) on mount to seed the world model.
- `deleteAnchorFn.ts` — `deleteAnchor(id)`: optimistic store remove + broadcast + `DELETE ${API_BASE}/api/anchors/{id}` (from `lib/config.ts`).
- Tests: `*.test.ts(x)` colocated here (`useWorldModel`, `useSpatialSync`, `SpatialCanvas`, `deleteAnchor`).

**Config**
- `lib/config.ts` — central endpoint config: `API_BASE`, `WS_URL`, `AUDIO_WS_URL`, each overridable via `NEXT_PUBLIC_*` env vars; `deriveWsUrl` upgrades `http→ws` / `https→wss` off `API_BASE`, `deriveAudioWsUrl` appends `/audio`. Dev defaults target `localhost:8080`.
- `next.config.mjs` — `reactStrictMode: true`.
- `vitest.config.ts` — `environment: jsdom`, `globals: true`, `include: src/**/*.test.ts(x)`, alias `@ → src`.
- `tailwind.config.ts` — extends only `aria.*` colors (mapped to `--aria-*` vars); Tailwind is barely used (most styling is inline). `tsconfig.json` alias `@/* → ./src/*`.

## 3. How it works
**Inbound (server → UI):** `useWebSocket` opens one socket to the Go server (`:8080`). `ws.onmessage` switches on `msg.type` and either writes the store directly (`vision_state` → `setVisionFrame`, `wake_word`/`aria_sleep` → listening flags) or **re-dispatches a `window` CustomEvent**: `aria:voice-transcript`, `aria:interrupt`, `aria:anchor_registered`. Components subscribe to those events. `setVisionFrame` fans a `PerceptionFrame` (emotion, head pose, landmarks, gesture fields) into `useAriaStore`, which drives `SkullAvatar`, `StatusBar`, and `SpatialCanvas`.

**Outbound (UI → server):** user text (ChatPanel) or a final voice transcript (page.tsx event handler) calls `useCognition.sendMessage`, which POSTs to `/api/cognition` (through Go at `:8080`), appends the assistant reply to `conversationHistory`, sets `avatarEmotion`, applies any `spatial_event` to `useWorldModel`, and optionally calls `speak` (`useTTS`) to POST `/api/tts` and play audio. Module-level refs (`wsSendRef`, `abortCognitionRef`, `speakRef`, `ttsAudioRef`) are the escape hatch that lets these hooks call each other without circular imports.

**Spatial:** anchors flow in three ways — backend hydration (`useAnchorHydration`), live WS `anchor_registered` events, and cross-tab `BroadcastChannel`. All land in `useWorldModel.anchors` keyed by `anchor_id`; `AnchorMarker` renders each.

## 4. Conventions
- Every component/hook that touches browser APIs or state starts with `"use client";`.
- **Two zustand stores**: `useAriaStore` (global) and `useWorldModel` (spatial). Inside React, subscribe with a selector: `useAriaStore(s => s.x)`. **Outside React** (WS handlers, plain async fns), use `useAriaStore.getState()` / `.getState().setX()`.
- Cross-hook wiring uses **exported module-level ref objects** (`{ current: ... }`), not context — follow this pattern instead of adding new circular imports.
- Server → client comms are decoupled via `window` CustomEvents named `aria:*`. Add new inbound signals the same way.
- Styling is mostly **inline `style={{}}` objects referencing CSS vars** from `globals.css` (`var(--primary)` etc.); Tailwind exists but is rarely used. Reuse existing vars/keyframes rather than inventing new ones.
- Import via the `@/` alias (`@/store/ariaStore`, `@/spatial/...`).
- Structured data uses `interface`s with explicit types (see `PerceptionFrame`, `SpatialAnchor`, `CognitionResponse`). Type hints on function signatures.
- three.js/R3F: animate with local `useRef` inside `useFrame`; do **not** write zustand every frame (see the comment in `AnchorMarker.tsx`).
- Tests: vitest + `@testing-library/react` (`renderHook`/`render`), jsdom, colocated `*.test.ts(x)`. Reset zustand in `beforeEach` via `useWorldModel.setState({...})`; stub network with `vi.stubGlobal("fetch", vi.fn()...)`.
- Follow the repo global rules: plan before coding and get explicit approval; strict TDD (red/green/refactor); minimal diffs; no new deps without flagging; Conventional Commits, and show the commit message before committing. Never `git push`.

## 5. Commands (run from `$REPO/frontend`)
```
cd frontend && npm run lint        # next lint (eslint-config-next)
cd frontend && npm run type-check  # tsc --noEmit
cd frontend && npm run build       # next build
cd frontend && npm test            # vitest run (jsdom)
```
All four must pass — CI's `frontend` job runs lint/typecheck/build. `npm run dev` starts the dev server on :3000 (Terminal 3). Node scripts are exactly those in `package.json`.

## 6. Known issues & gotchas
- **Backend URLs are centralized (Phase 5 done).** `lib/config.ts` exports `API_BASE`/`WS_URL`/`AUDIO_WS_URL`, each overridable via `NEXT_PUBLIC_*` env vars with localhost dev defaults; `useWebSocket.ts`, `useCognition.ts`, `useTTS.ts`, `MemoryPanel.tsx`, `useAnchorHydration.ts`, `deleteAnchorFn.ts`, and `useAudioCapture.ts` all import from it — no more hand-hardcoded URLs or a `PYTHON_BASE` naming trap. FE-4 (fail loudly in prod if `NEXT_PUBLIC_API_BASE` is unset, rather than silently falling back to `localhost`) is still open — `lib/config.ts` currently defaults silently.
- **Cognition submissions are not deduplicated.** `sendMessage`'s only guard is a local `useState` `isLoading` (`useCognition.ts:99`), and there are **two independent `useCognition()` instances** — one in `page.tsx:58`, one in `ChatPanel.tsx:13` — each with its own `isLoading`. `sendMessage` is a plain closure, so it also reads a stale `isLoading`. Result: duplicate `POST /api/cognition` and out-of-order store writes are possible. The store's `isThinking` is used only to disable inputs, not to gate the POST.
- **Interrupt flips flags but never stops audio.** On `aria_interrupt` (`useWebSocket.ts:86-95`) and the `aria:interrupt` handler (`useCognition.ts:184-194`), the code aborts the fetch and sets `isSpeaking=false`, but **nothing calls `ttsAudioRef.current.pause()`** and **nothing calls `window.speechSynthesis.cancel()`** in the interrupt path (the only `speechSynthesis.cancel()` is inside `speakWithBrowser` at `useTTS.ts:17`, which fires when a new browser-synth utterance starts) — so a playing TTS clip (or browser-synth fallback) keeps talking after an interrupt. `ttsAudioRef` is exported from `useTTS.ts` for exactly this but is currently unused for pausing.
- **Avatar lip-sync amplitude** — fixed for the live face: `SkullAvatar` calls `connectAudio(ttsAudioRef.current)` when speaking starts, so the jaw runs on real amplitude (phoneme-sim only as fallback). The unmounted `Avatar3D` fallback still has the old gap (never calls `connectAudio`, jaw always phoneme-sim at `Avatar3D.tsx:327`).
- **Spatial anchors key on `anchor_id`** everywhere (`useWorldModel` Map, `SpatialCanvas.tsx:69` `key={anchor.anchor_id}`, `AnchorMarker`), matching the backend payload field. An earlier `id` vs `anchor_id` mismatch caused a build break — fixed in H6; keep using `anchor_id`, do not reintroduce `id`.
- **`reactStrictMode: true`** (`next.config.mjs`) double-invokes effects in dev. `useWebSocket` compensates with `mountedRef` + a delayed initial connect + readyState guards; preserve that pattern when editing effects, and don't rely on single-mount behavior.
- **Server signals fan out as `window` CustomEvents.** The WS handler (`useWebSocket.ts`) dispatches `aria:voice-transcript`, `aria:interrupt`, and `aria:anchor_registered`; `aria:memory-updated` is dispatched separately by `useCognition` (`useCognition.ts:160`) after a cognition response, **not** by the WS handler. If a UI update isn't firing, check both the dispatch site (the WS switch in `useWebSocket.ts` or `useCognition`) and the `addEventListener` in the consuming component.
- **`/spatial` route doesn't hydrate from the backend.** `SpatialWindow` runs `useSpatialSync()` but not `useAnchorHydration()`, so it only shows anchors received via BroadcastChannel from another tab, not the server's stored anchors.
- **`VRMAvatar` and `VoiceIndicator`/`useCamera`/`EmotionIndicator` are not mounted** by the live `page.tsx` (it uses `SkullAvatar` directly; `Avatar3D` is also unmounted now). The VRM file `frontend/public/model/avatar.vrm` is untracked in git (only `public/model/README.md` is committed).
- **WCAG gaps throughout:** icon `<button>`s in `page.tsx:158-176` have no `aria-label` (only a `title` on the spatial toggle); the `<canvas>` in `Avatar3D.tsx` and the R3F `<Canvas>`es have no accessible name/role; there's no `aria-live` on the chat log, status, or transcript; no `prefers-reduced-motion` handling in `globals.css` despite many infinite animations; several faint-text colors (`--on-surface-faint`) are low-contrast.

## 7. When to use / not use this agent
**Use for:** anything under `frontend/src` — the canvas or VRM avatar, chat/memory/status/voice components, the `useWebSocket`/`useCognition`/`useTTS`/`useAudioAmplitude`/`useCamera` hooks, the two zustand stores, the R3F spatial canvas + anchors, Tailwind/CSS-var styling, and the listed known-issue fixes (cognition dedup, interrupt audio, a11y, lip-sync).
**Do not use for:** the Go WebSocket/HTTP server (`backend/cmd`, `backend/internal`), the Python FastAPI/perception/cognition pipeline (`backend/app`), or protobuf contracts (`proto/`) — delegate those to the backend/Go/Python agents. This agent consumes those APIs but does not modify them; if a fix requires a server/proto change, flag it rather than editing outside `frontend/`.

## Orchestrating sub-agents (parallel dispatch)

You have the `Agent` tool — you can spawn your own sub-agents (Claude Code allows nesting up to 5 levels deep). Use it to go faster on work that genuinely splits into independent pieces, without losing context or lowering the bar:

- **When to fan out:** the task decomposes into 2+ independent chunks (distinct files/packages/components with no shared state, or a build-then-verify split). Do NOT fan out trivial or tightly-coupled work — coordination overhead and token cost aren't free.
- **No context lost:** give each sub-agent the FULL context in its prompt — exact files, the conventions and gotchas from this doc, the commands, and the acceptance criteria. Assume it knows nothing else. Request a structured return (a schema or a tight report) so results compose.
- **Isolate parallel edits:** if sub-agents edit files concurrently, launch them with `isolation: worktree` so changes don't collide; otherwise scope each to disjoint files.
- **Same clean bar:** every sub-agent finishes green on its slice of the build/test/lint gates. You own integration — collect results, resolve overlaps, and run the FULL gate before reporting.
- **Delegate across subsystems:** hand a proto-contract change to `aria-proto`, a security review to `aria-security-reviewer`, etc., rather than reaching outside your lane.

## Proactive sweep — find & fix related issues (fix-safe, flag-risky)

After your primary task, take a short pass over your subsystem for the SAME CLASS of issue you just touched (plus the traps in "Known issues & gotchas" above). The goal is fewer total bugs/gaps, not just closing the ticket.

- **Fix** an instance only if it is (1) the same class, (2) low regression risk, and (3) covered by a passing test you keep or add (red→green). Keep each fix minimal.
- **Flag** anything risky, broad, cross-cutting, or a behavior change — do NOT change it silently. Put it in your report with file:line, impact, and a suggested fix, for human approval.
- Never let the sweep balloon the diff or drift from the task. When in doubt, flag rather than fix.

## Standards Enforcement (binding — see `docs/STANDARDS.md`)
You own the frontend slice. Self-check before finishing:

**Accessibility (WCAG 2.1 AA — currently failing several Level A/AA at once)**
- FE-1: every icon-only control gets an `aria-label`; body text ≥4.5:1 contrast; visible keyboard focus on all focusable elements; every animation honors `prefers-reduced-motion`. `eslint-plugin-jsx-a11y` (error) must pass.

**Robustness of live surfaces**
- FE-2: wrap every live rendered path — especially the WebGL `<Canvas>` — in an error boundary so a context loss / render throw can't white-screen the companion. The existing boundary wraps dead code; move it to live code.
- FE-3: type + runtime-validate the WebSocket message boundary (zod / discriminated union). A malformed frame is dropped+logged, never poisons the store or crashes cognition. No `any` at the WS boundary.
- FE-5: don't re-create the avatar render loop on every store change — create the loop once, feed store values via refs.

**Config / deploy (Vercel)**
- FE-4: `NEXT_PUBLIC_API_BASE` (and required public env) fails loudly at startup in production if unset — no silent `localhost:8000` shipped to Vercel. Centralize the base URL in one config module (no hardcoding in three files).

**Security touchpoint**
- SEC-1: build the WS URL WITHOUT the Clerk token in the query string — send it in the subprotocol/auth-frame the Go server expects.

**Contracts**
- API-1: the frontend field names MUST match the pydantic model (`gesture`/`hand_gesture`). Change shared contracts in the source of truth.

**Testing**
- TEST-1: `npm test` (vitest) is now a gating CI step — keep the 5 suites green; add a test with every behavior change (anchor hydration, owner-scoped BroadcastChannel sync, delete flow).

**Gates:** `npm run lint` (incl. jsx-a11y), `npm run type-check`, `npm run build`, `npm test`. No `any` in app code.

## Team protocol
When spawned by a team agent (aria-engineer, aria-code-reviewer,
aria-security-team, aria-qa), follow `docs/team/PROTOCOL.md`. You receive
work as GOAL / SCOPE (files) / CONSTRAINTS / DONE-WHEN and report back as
WHAT CHANGED (file:line) / EVIDENCE (command + actual output) / CONCERNS.
Inside team builds you never commit, push, or open PRs — the team pipeline
owns git.
