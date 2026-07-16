# MediaPipe assets (browser-side perception)

The browser runs MediaPipe Tasks Vision locally (Phase A.2a) so the camera never
leaves the user's machine. To stay CSP-safe we load the WASM runtime and the
`.task` models **from this app's own origin** (`/mediapipe/...`) instead of a
runtime CDN fetch.

## What lives here

| File | Source | In git? |
|------|--------|---------|
| `face_landmarker.task` (3.6 MB) | `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task` (float16 / 1) | **committed** |
| `hand_landmarker.task` (7.5 MB) | `https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task` (float16 / 1) | **committed** |
| `wasm/` (6 files) | Copied from `node_modules/@mediapipe/tasks-vision/wasm/` (pinned `0.10.35`) | git-ignored, build-copied |

These are the same model URLs the retired Python `vision_worker.py` used, so
detection behaviour matches the server pipeline being replaced.

## How provisioning works

- **The two `.task` models are committed to the repo.** At ~11 MB total they ship
  as normal static assets, so Vercel/production serves them from `/mediapipe/...`
  with no build-time download and no external host — the simplest path that stays
  free and within the Vercel Hobby tier.
- **The WASM runtime is copied at build time,** not committed. `npm run predev`
  and `npm run prebuild` run `frontend/scripts/copy-mediapipe-wasm.mjs`, which
  copies `wasm/` out of the pinned `@mediapipe/tasks-vision` package into this
  folder. It is reproducible from the lockfile, needs no network, and runs on
  Vercel and in CI before `next build`. The `wasm/` folder is git-ignored (root
  `.gitignore`).

To refresh the models to a newer MediaPipe version, re-download from the URLs
above and bump the `@mediapipe/tasks-vision` pin so the WASM matches.
