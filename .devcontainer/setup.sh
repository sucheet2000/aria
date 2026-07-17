#!/usr/bin/env bash
# One-time environment setup for the ARIA Codespace / devcontainer.
# Runs as postCreateCommand. First run takes a few minutes (Python ML deps).
set -uo pipefail

echo "▶ Frontend dependencies (npm ci)…"
( cd frontend && npm ci )

echo "▶ Go modules (go mod download)…"
( cd backend && go mod download )

echo "▶ Python venv + deps…"
cd backend
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip wheel >/dev/null
# Install the CPU-only torch build first to skip ~3GB of unused CUDA wheels
# (same trick CI uses; requirements.txt's torch==2.10.0 is then already satisfied).
if ! pip install torch==2.10.0+cpu --index-url https://download.pytorch.org/whl/cpu; then
  echo "⚠ CPU torch pre-install failed — requirements.txt will pull the default build (slower)."
fi
pip install -r requirements.txt
cd ..

cat <<'DONE'

✅ ARIA devcontainer ready.

Before running the backend, add your keys as Codespaces secrets
(see .devcontainer/README.md). Then, in three terminals:

  • Python API : cd backend && PYTHONPATH=$PWD .venv/bin/python -m uvicorn app.main:app --port 8000
  • Go server  : cd backend && go run cmd/server/main.go
  • Frontend   : cd frontend && npm run dev

Port 3000 auto-forwards and opens in your browser.
DONE
