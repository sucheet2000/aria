// Provisions the MediaPipe Tasks-Vision WASM runtime for the browser perception
// pipeline (A.2). We load MediaPipe from our OWN origin (/mediapipe/wasm) to stay
// CSP-safe — never a runtime CDN fetch — so the WASM must be present in public/.
//
// The `.task` MODELS are committed (public/mediapipe/*.task); the WASM is copied
// here from the pinned `@mediapipe/tasks-vision` npm package at build time (no
// network, reproducible from the lockfile). Runs as `prebuild`, so it executes on
// Vercel and in CI before `next build`.
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../node_modules/@mediapipe/tasks-vision/wasm");
const dest = resolve(here, "../public/mediapipe/wasm");

if (!existsSync(src)) {
  console.error(
    `[mediapipe] WASM source not found at ${src}. Run \`npm ci\` first ` +
      `(is @mediapipe/tasks-vision installed?).`,
  );
  process.exit(1);
}

mkdirSync(dest, { recursive: true });
cpSync(src, dest, { recursive: true });
console.log(`[mediapipe] copied WASM runtime → public/mediapipe/wasm`);
