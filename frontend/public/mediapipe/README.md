# MediaPipe assets (browser-side perception)

The browser runs MediaPipe Tasks Vision locally (Phase A.2a) so the camera never
leaves the user's machine. To stay CSP-safe we load the WASM runtime and the
`.task` models **from this app's own origin** (`/mediapipe/...`) instead of a
runtime CDN fetch.

## Files expected here

| File | Source | Version |
|------|--------|---------|
| `wasm/` (6 files) | Copied from `node_modules/@mediapipe/tasks-vision/wasm/` | matches the `@mediapipe/tasks-vision` version pinned in `package.json` (0.10.35) |
| `face_landmarker.task` | `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task` | float16 / 1 |
| `hand_landmarker.task` | `https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task` | float16 / 1 |

These are the same model URLs the retired Python `vision_worker.py` used, so
detection behaviour matches the server pipeline being replaced.

## Provisioning (they are NOT committed to git)

The binaries total ~43MB and are excluded by `.gitignore` (`*.task` repo-wide,
and `wasm/` via this folder's `.gitignore`). Provision them per environment:

```bash
# from frontend/
mkdir -p public/mediapipe/wasm
cp node_modules/@mediapipe/tasks-vision/wasm/* public/mediapipe/wasm/
curl -sSL -o public/mediapipe/face_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
curl -sSL -o public/mediapipe/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
```

For the Vercel/production build, run the equivalent as a build step (or move to
git-lfs / an approved asset host with a matching CSP `wasm-src`/`connect-src`).
