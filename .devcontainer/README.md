# Develop ARIA in the cloud (GitHub Codespaces)

Run the whole stack — Go + Python + Next.js — in a cloud dev environment, so nothing
heavy lives on your laptop. The environment (Go 1.26, Python 3.13, Node 20 and all
dependencies) is built automatically from `.devcontainer/`.

## Is it free?

Personal GitHub accounts get **120 core-hours + 15 GB storage free every month**
(~60 hours on a 2-core machine, ~30 on a 4-core). Set your **Codespaces spending
limit to $0** (GitHub → Settings → Billing → Codespaces) and it simply stops at the
free quota instead of ever charging you. Codespaces also auto-suspend after 30 minutes
idle, so you don't burn hours leaving one open.

## Open one

1. On GitHub: **Code ▸ Codespaces ▸ Create codespace on `integration`**.
2. First build takes a few minutes (it installs the Python ML deps). After that it's cached.
3. The default **2-core** machine is fine for editing and the frontend. Pick **4-core**
   when you want to run the full Python + Go + browser pipeline at once (it uses free
   hours twice as fast).

## Add your secrets (once)

The environment builds without any keys, but the backend needs them to run. Add them as
**Codespaces secrets** so they're never in the code:
GitHub → repo **Settings ▸ Secrets and variables ▸ Codespaces ▸ New secret**.

| Secret | Used by | Notes |
|--------|---------|-------|
| `ANTHROPIC_API_KEY` | Python (Claude cognition) | required |
| `ELEVENLABS_API_KEY` | Python (TTS voice) | required for speech out |
| `ELEVENLABS_VOICE_ID` | Python (TTS voice) | the voice to use |
| `INTERNAL_AUTH_SECRET` | Go ⇄ Python trust boundary | required when `ENV != local` |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Frontend (auth) | public key, safe to expose |
| `CLERK_SECRET_KEY` | Frontend (auth) | keep secret |

The full list of backend settings (with blanks) is in [`backend/.env.example`](../backend/.env.example).
For local `ENV=local` runs the internal-auth guard is relaxed, so you can start the
backend with just the Anthropic/ElevenLabs keys and fill the rest in later.

## Run it

The setup script prints these on completion; three terminals:

```bash
# Python API (FastAPI)
cd backend && PYTHONPATH=$PWD .venv/bin/python -m uvicorn app.main:app --port 8000

# Go server (WebSocket hub / authenticated edge)
cd backend && go run cmd/server/main.go

# Frontend (Next.js)
cd frontend && npm run dev
```

Ports **3000** (frontend), **8000** (Python API) and **8080** (Go server) forward
automatically; 3000 opens in your browser.

## What's where

- **`devcontainer.json`** — the environment definition (base image, language features,
  forwarded ports, VS Code extensions).
- **`setup.sh`** — one-time dependency install (`npm ci`, `go mod download`, a Python
  venv with CPU-only torch to skip ~3 GB of unused CUDA wheels).
