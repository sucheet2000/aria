# A.2 — Browser-Side Perception (SCALE-1) · Design for approval

**Status:** proposed — needs your sign-off before any code (it's a rewrite).
**Goal:** retire server-side camera/mic capture so ARIA works in the cloud and is genuinely multi-user, by moving capture + light inference into each user's browser. STT, cognition, and TTS stay on the server.

---

## Why this is the last showstopper
A Railway container has no camera/mic. Today the Python vision/audio workers open the **server's** physical devices (`cv2.VideoCapture(0)`, `sounddevice`) — so the headline multimodal feature can't run in prod and can never be per-user (one physical device, claimed by one `activeOwner`). Moving capture browser-side fixes cloud-viability, multi-tenancy, **and** privacy (video never leaves the user's machine) in one stroke.

## Current state (verified by the pipeline map)
- **The live perception path is a stdout JSON pipe**, not gRPC/NATS: Python vision worker → stdout → Go scans it → WS `vision_state` → frontend store → re-attached onto the `POST /api/cognition` body.
- **Two whole transports are dead code:** the gRPC `PerceptionService` (:50051) and the NATS `aria.perception.frames` path are fully built but **wired to nothing** (server runs, no consumer). They can be deleted.
- **The frontend is a pure sink today** — `useCamera.ts` exists but is never mounted; no `getUserMedia`, no in-browser inference.
- **STT is the one thing that can't move:** faster-whisper is CPU-heavy with no browser-quality equivalent. So mic **audio** must still reach the server, even though **capture** moves to the browser.
- Emotion, gesture, and head-pose are dependency-light **rule/math** (pure Python) — trivial to port to TypeScript.

## Target architecture
```
Browser:  getUserMedia(camera) → MediaPipe FaceLandmarker + HandLandmarker (WASM/WebGPU)
                               → emotion + gesture + head-pose (ported to TS)
                               → fills vision_state on POST /api/cognition   (cognition ~unchanged)
          getUserMedia(mic)    → VAD (WASM) → stream utterance audio over a WS   ┐
Server:   NEW /ws/audio endpoint → existing VAD/whisper/wake-word pipeline ──────┘ (STT stays)
          cognition (Claude) · TTS · memory — unchanged
Retired:  vision_worker camera loop · Go vision subprocess · gRPC PerceptionService(:50051) · NATS frames
```
Key seam: **the browser produces the exact `vision_state` + gesture fields the cognition route already consumes** — so `cognition_route.py` / the schema need ~zero change. The `PerceptionFrame` proto (hands-only) is a red herring and gets retired with the dead transports.

## Move / keep / retire
| Moves to browser | Stays server-side | Retired / deleted |
|---|---|---|
| Camera capture (getUserMedia) | STT (faster-whisper) | `vision_worker.py` camera loop + `cv2.VideoCapture` |
| MediaPipe Face + Hand (WASM) | Denoise (DeepFilterNet) | Go vision subprocess (`internal/vision/worker.go`) |
| emotion / gesture / head-pose (→ TS) | Claude cognition · TTS · memory | gRPC `PerceptionService` :50051 (dead) + NATS frames (dead) |
| face-exit interrupt detector | wake-word / sleep-phrase state machine | `sounddevice` capture (source swaps to WS audio) |
| mic capture (audio streamed to server) | | |

## Recommended phasing (two independently-shippable phases)
**A.2a — Vision (the clean half).** Browser camera + MediaPipe + ported emotion/gesture/head-pose fills the cognition request; retire the vision worker + both dead transports. Cognition unchanged. Lower risk — vision already round-trips through the browser, we're just inverting who produces it.

**A.2b — Audio (the hard half).** Browser mic → VAD → stream utterances to a new server `/ws/audio` endpoint that feeds the existing whisper/wake-word pipeline; retire `sounddevice`. Re-home the wake-word + the TTS-mute-during-speech loop across the network. Higher risk (latency + that feedback loop).

Shipping A.2a first proves the model and de-risks A.2b.

## Risks / tradeoffs
- **Browser MediaPipe perf** — WASM/WebGPU face+hands at ~15fps is well within budget on modern laptops; degrade gracefully on weak devices.
- **Audio latency + the TTS-mute loop** — today VAD-mute-during-TTS is a local stdin poke; across the network it needs a WS control channel. The trickiest coupling.
- **Owner-scoping becomes per-connection** — each browser is its own source (this is the *fix* for multi-user, not a regression).
- **Camera-permission UX** — browser prompts; need a clean "enable camera/mic" gate.
- **`two_hand_gesture` is already vestigial** (never emitted) — drop it, don't port it.

## Decisions I need from you
1. **Approve the approach** (browser MediaPipe + server-side STT via streamed audio)?
2. **Phasing:** A.2a (vision) first, then A.2b (audio) — OK? Or both together?
3. **Scope of retirement:** delete the dead gRPC PerceptionService + NATS frame path now (they carry no traffic), or leave them dormant?
4. This is multi-PR and touches the live app — do you want a full written implementation plan (file-by-file, per the writing-plans flow) before code, or a lighter go-per-phase?
