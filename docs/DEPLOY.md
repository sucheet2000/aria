# ARIA — Go-Live Runbook (Phase 5)

Step-by-step guide to deploy ARIA: the backend to **Railway** and the frontend to
**Vercel**. This is deploy documentation — running it is a manual, human-driven
task. Nothing here calls a cloud API for you.

---

## 1. How the pieces fit together

ARIA ships as **two deployments**:

- **Backend → Railway.** One Docker image (`backend/Dockerfile`) runs *three*
  things in a single container:
  - the **Go server** — the only public process. Binds `0.0.0.0:$PORT`, terminates
    the WebSocket, verifies Clerk tokens, rate-limits, and proxies to Python.
  - the **Python FastAPI service** — internal only. Binds `127.0.0.1:8000`. Does
    cognition (Claude) and TTS (ElevenLabs).
  - the **Python vision/audio workers** — subprocesses the Go server spawns.

  `start.sh` launches uvicorn on `127.0.0.1:8000` in the background, then hands the
  container's main process to the Go server on `$PORT`.

- **Frontend → Vercel.** The Next.js app. Talks to the backend over HTTPS
  (`/api/*`) and secure WebSocket (`wss://…/ws`).

```
Browser ──HTTPS/WSS──> Railway (Go :$PORT, public)
                              │  spawns + proxies (localhost only)
                              ├─> Python FastAPI 127.0.0.1:8000  (internal)
                              └─> Python vision/audio workers    (subprocesses)

Vercel (Next.js) ──> Railway Go URL
```

## 2. Two invariants — do not break these

1. **Python is never public.** Only the Go port is exposed on Railway. FastAPI
   stays on `127.0.0.1:8000` inside the container. Railway must map exactly one
   port (the Go `$PORT`); never add a second public port for `:8000`. Go is the
   single auth boundary — FastAPI trusts the `X-Aria-Owner` header Go sets after
   verifying the Clerk token, so exposing `:8000` would let anyone forge identity.

2. **Set `INTERNAL_AUTH_SECRET`.** Defense-in-depth: a shared secret Go sends and
   Python requires on internal calls, so an accidental exposure of `:8000` still
   can't forge requests. Generate a long random value and set it on Railway.

---

## 3. Every secret and setting

### Backend (Railway service environment)

| Variable | Required | Secret | What it is |
| --- | --- | --- | --- |
| `PORT` | Auto | no | Injected by Railway. The Go server binds it. Do not hardcode. |
| `HOST` | Baked | no | `0.0.0.0` (set in the Dockerfile). Needed so Railway can reach the Go server. |
| `ANTHROPIC_API_KEY` | Yes | **yes** | Claude API key. Spends money. |
| `ELEVENLABS_API_KEY` | Yes | **yes** | ElevenLabs TTS key. Spends money. |
| `ELEVENLABS_VOICE_ID` | Yes | no | Which ElevenLabs voice to use. |
| `CLERK_SECRET_KEY` | **Yes** | **yes** | Clerk secret key. **Mandatory in production** — with the `0.0.0.0` bind the Go server refuses to start without it (fail-closed). |
| `CLERK_JWT_ISSUER` | Yes | no | Clerk issuer/JWKS URL. Enforced when verifying tokens. |
| `INTERNAL_AUTH_SECRET` | Yes | **yes** | Shared Go↔Python secret (invariant #2). Random long string. |
| `ALLOWED_ORIGINS` | Yes | no | Comma-separated CORS allow-list. Set to your Vercel URL, e.g. `https://aria.vercel.app`. |
| `RATE_LIMIT_RPS` | No | no | Per-user requests/sec on paid endpoints. Default `5`. |
| `RATE_LIMIT_BURST` | No | no | Per-user burst. Default `10`. |
| `RATE_LIMIT_GLOBAL_RPS` | No | no | Global ceiling requests/sec. Default `50`. |
| `RATE_LIMIT_GLOBAL_BURST` | No | no | Global burst. Default `100`. |
| `AUDIO_ENABLED` | Recommended | no | Set `false` in the cloud — there is no microphone on the server. |
| `DEBUG` | No | no | `false` in production. |

Never set `ALLOW_INSECURE_NO_AUTH` in production. It is a local-dev-only escape
hatch. In production you set a real `CLERK_SECRET_KEY` instead.

### Frontend (Vercel project environment)

| Variable | Required | Secret | What it is |
| --- | --- | --- | --- |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Yes | no (public) | Clerk publishable key. Ships in the browser bundle; needed at build time. |
| `NEXT_PUBLIC_API_BASE` | Yes | no | Backend HTTPS base, e.g. `https://aria-backend.up.railway.app`. |
| `NEXT_PUBLIC_WS_URL` | Yes | no | Backend WebSocket URL, e.g. `wss://aria-backend.up.railway.app/ws`. |
| `CLERK_SECRET_KEY` | Yes | **yes** | Clerk server-side key. `clerkMiddleware` runs server-side on Vercel and needs it. |

> Vercel injects `NEXT_PUBLIC_*` env vars into the build automatically once they
> are set in Project → Settings → Environment Variables. That is why `vercel.json`
> does not list them — referencing them there via the legacy `@secret` syntax
> breaks fresh builds. Set them in the dashboard.

---

## 4. Deploy the backend to Railway

1. **Create the project.** Railway dashboard → **New Project** → **Deploy from
   GitHub repo** → pick the ARIA repo and the branch you want to ship.
2. **Point the service at the backend.** Service → **Settings → Source**:
   - **Root Directory:** repo root (leave blank / `/`). The image is built from
     the repo root so `SOUL.md` — which lives at the root, outside `backend/` — is
     copied into the image. `SOUL_PATH=/app/SOUL.md` is baked into the Dockerfile,
     so `prompt.py` loads ARIA's identity with no manual env var.
   - **Builder:** Dockerfile. Set the **Dockerfile path** to `backend/Dockerfile`.
   - The settings in `deploy/railway.json` mirror this (builder = Dockerfile,
     `dockerfilePath: backend/Dockerfile`, health check `/health`, restart on
     failure). To apply them as code, set the service's config-as-code path to
     `deploy/railway.json`.
3. **Set the environment variables** from the backend table in section 3
   (Service → **Variables**). At minimum: `ANTHROPIC_API_KEY`,
   `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `CLERK_SECRET_KEY`,
   `CLERK_JWT_ISSUER`, `INTERNAL_AUTH_SECRET`, `ALLOWED_ORIGINS`,
   `AUDIO_ENABLED=false`. Do **not** set `PORT` — Railway provides it.
4. **Deploy.** Railway builds the Dockerfile (heavy — several minutes for the ML
   deps) and starts the container. Health check hits `GET /health` on `$PORT`.
5. **Get the URL.** Service → **Settings → Networking → Generate Domain**. Copy the
   `https://…up.railway.app` URL — the frontend needs it. Confirm only one port
   is exposed (the Go `$PORT`), never `:8000`.
6. **Smoke-test:** `curl https://<railway-url>/health` should return
   `{"status":"ok",...}`. `/api/*` without a token should return `401`.

## 5. Deploy the frontend to Vercel

1. **Import the project.** Vercel dashboard → **Add New → Project** → import the
   ARIA repo.
2. **Set the root directory** to `frontend`. Vercel auto-detects Next.js and uses
   `frontend/vercel.json` (framework, `npm ci`, `npm run build`).
3. **Set the environment variables** from the frontend table in section 3:
   - `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`
   - `NEXT_PUBLIC_API_BASE` → the Railway HTTPS URL from step 4.5, e.g.
     `https://aria-backend.up.railway.app`
   - `NEXT_PUBLIC_WS_URL` → the same host with `wss://` and the `/ws` path, e.g.
     `wss://aria-backend.up.railway.app/ws`
   - `CLERK_SECRET_KEY`
4. **Deploy.** Vercel builds and gives you a `https://<app>.vercel.app` URL.
5. **Close the CORS loop.** Set the backend `ALLOWED_ORIGINS` on Railway to this
   Vercel URL and redeploy the backend if it changed.

## 6. Verify end to end

1. Open the Vercel URL → you should be sent to Clerk sign-in.
2. Sign in → the app loads and the WebSocket connects (`wss://…/ws?token=…`).
3. Send a message → cognition returns and TTS audio plays.
4. Signed-out `/api/*` returns `401`; a request flood returns `429`.

---

## 7. Known gaps — must fix before this actually serves traffic

These are outside "deploy config" scope (they are Go/Python/frontend code) but
**block a working cloud deploy**. Flagged here so they are not a surprise:

1. **✅ Resolved (Phase 5a).** The frontend previously hardcoded
   `http://localhost:8080` / `ws://localhost:8080`. It now reads
   `NEXT_PUBLIC_API_BASE` / `NEXT_PUBLIC_WS_URL` via `frontend/src/lib/config.ts`
   (falls back to localhost for local dev). Just set those two env vars on Vercel
   (section 3) and the deployed frontend targets the Railway backend.
2. **Vision worker has a hardcoded macOS path.**
   `backend/internal/vision/worker.go` sets `cmd.Dir = "/Users/sucheetboppana/aria/backend"`.
   That path does not exist in the container, so the vision subprocess won't start.
   Change it to the container working directory (`/app`) or an env var. Graceful:
   the Go server keeps running; only vision is dead. **Go backend agent's task.**
3. **Server-local vision/audio capture.** The workers capture the *server's*
   camera/mic. A Railway container has neither, so live perception is effectively
   off in the cloud until capture moves client-side. Set `AUDIO_ENABLED=false`.
4. **✅ Resolved.** `SOUL.md` now ships in the image. The backend is built from a
   **repo-root context** (`docker build -f backend/Dockerfile .`), the Dockerfile
   does `COPY SOUL.md /app/SOUL.md`, and it bakes `SOUL_PATH=/app/SOUL.md` so
   `prompt.py` loads ARIA's identity explicitly (env override, repo-root fallback
   for local dev). On Railway set **Root Directory** to the repo root and the
   **Dockerfile path** to `backend/Dockerfile` (section 4).
5. **✅ Resolved (Phase 5b).** `INTERNAL_AUTH_SECRET` is now enforced end-to-end:
   Go sends `X-Internal-Auth` on every internal call and Python's
   `require_internal_auth` returns 403 on a missing/wrong secret (constant-time
   compare; pass-through only when the secret is unset for local dev). Set the same
   secret on both the Railway backend and the Python service so the boundary is live.
   This is defence-in-depth behind invariant #1 (Python stays private).

---

## 8. Test the backend image locally (optional)

```bash
# Build the same image Railway builds (repo-root context so SOUL.md is copied):
docker build -f backend/Dockerfile -t aria-backend .

# Run with docker-compose (Go public on :8080, Python internal, audio off):
ANTHROPIC_API_KEY=... ELEVENLABS_API_KEY=... docker compose up
```

`docker-compose.yml` sets `ALLOW_INSECURE_NO_AUTH=1` for local runs (no Clerk).
Production does the opposite: a real `CLERK_SECRET_KEY`, no insecure flag.
