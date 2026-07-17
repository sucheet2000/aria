# Skull Avatar ("Reference Twin") — Design Spec

**Date:** 2026-07-16
**Status:** Approved by Sucheet (direction D1 chosen from four rendered mockups)
**Mockups:** claude.ai artifact "ARIA Face Directions" — D1 "Reference Twin"
(the artifact's D1 SVG is the approved geometry reference)

## 1. Summary

Replace ARIA's talking face with a cyberpunk robo-skull matching Sucheet's
reference image (`83731527.png`): indigo mechanical skull, glowing magenta
cross-shaped eyes in dark sockets, gold bared teeth, cyan hardware accents,
head cables, side machinery, forehead plate with three pink dots, flat
cel-shaded style with dark outlines. The new face keeps everything that
already works: amplitude-driven jaw lip-sync and the nine emotion states.

The reference appears to be a collectible artwork; the avatar is a hand-built
vector interpretation of its style (personal use), not a copy of the file.

## 2. Component

- **New:** `frontend/src/components/SkullAvatar.tsx` — an SVG React component
  (`"use client"`). The approved D1 mockup's geometry moves into it: cranium +
  face path, cel-shade overlays, eye sockets, cross-glyph eyes with SVG glow
  filter, nose, forehead plate + three dots, cheek vents, upper teeth row,
  lower-jaw `<g>` (mandible + lower teeth), head cables, side machinery, neck
  tubes.
- **Why SVG over canvas:** emotion theming is CSS custom properties
  (`--iris`, `--acc`, …) swapped per state; glow is a declarative filter; the
  jaw animates by transforming one `<g>`. No per-frame redraw of ~60 shapes.
- **Integration:** `frontend/src/app/page.tsx` swaps its import from
  `Avatar3D` to `SkullAvatar`. `Avatar3D.tsx` stays untouched in the tree as
  the one-line-revert fallback. No other consumer changes.

## 3. Lip-sync

Same wiring as the current face: `useAudioAmplitude` + `connectAudio` on
`ttsAudioRef`'s audio element. A `requestAnimationFrame` loop writes
`transform: translateY(<amplitude-scaled px>)` directly on the jaw group's
DOM node (ref) — no React re-render per frame. Max jaw drop ≈ 13px at the
mockup's 320×340 viewBox scale; smoothing identical in feel to today's jaw.

## 4. Emotion states

The nine existing profiles survive as palette maps. The indigo shell stays
constant; **eyes (`--iris`) and cyan hardware (`--acc`) take the state
color**, and glow/pulse intensity is the second signal (reusing the current
`pulse` values as pulse-rate multipliers):

| State | Eyes / accents | Notes |
|---|---|---|
| idle | blue `#50b4ff` | slow pulse |
| listening | cyan `#00d2ff` | faster pulse |
| thinking | purple `#a064ff` | strong pulse |
| speaking | teal `#00ffb4` | jaw active |
| happy | gold `#ffd200` | |
| distressed | red `#ff3c3c` | fastest pulse |
| fearful | violet `#c864ff` | |
| surprised | amber `#ffb400` | |
| neutral | = idle | |

Default (no state) styling matches the reference: magenta `#ff4ff0` eyes,
cyan `#2ef2cf` hardware. State priority preserved: speaking > thinking >
listening > emotion — same `getProfile` logic as `Avatar3D`.

Reads the same zustand store flags `Avatar3D` reads today (avatar emotion,
speaking/thinking/listening); exact selector names verified at plan time from
`ariaStore.ts`.

## 5. Idle motion & a11y

- Gentle whole-head bob (slow translateY sine) + eye-glow pulse so the face
  never looks frozen.
- Both disabled under `prefers-reduced-motion` (FE-1). Jaw lip-sync remains
  (it conveys real information) but with transition smoothing removed.
- SVG carries `role="img"` and a descriptive `aria-label`.
- Palette check: state colors sit on the dark socket/void grounds at
  comfortable contrast; the component introduces no text.

## 6. Testing (vitest, colocated)

`frontend/src/components/SkullAvatar.test.tsx`:
1. Renders with the correct role and aria-label.
2. Emotion state → expected `--iris` CSS var on the root group (table-driven
   across all nine states + priority: speaking beats emotion).
3. Amplitude change (mocked `useAudioAmplitude`) → jaw group transform
   changes.
4. `prefers-reduced-motion` (mocked matchMedia) → ambient animation class
   absent.

Full local gate (`make check`) green before commit; in-browser QA pass
(voice → jaw movement; emotion → eye recolor) at the end.

## 7. Out of scope (parked, not lost)

- D2 "Ghost Shell" hologram mode (shares this geometry; future toggle).
- D3 "Sigil" status-bar mini-face / favicon.
- Any VRM/three.js work, WS/cognition changes, or `VoiceDot`/`StatusBar`
  changes.

## 8. Files

| File | Change |
|---|---|
| `frontend/src/components/SkullAvatar.tsx` | New — the D1 skull component |
| `frontend/src/components/SkullAvatar.test.tsx` | New — tests above |
| `frontend/src/app/page.tsx` | Swap `Avatar3D` → `SkullAvatar` (import + JSX) |

No new dependencies. No other files.
