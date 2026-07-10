#!/usr/bin/env bash
set -euo pipefail

# The Python FastAPI service binds loopback only. It is internal — the Go server
# is the sole public listener and the only auth boundary. Never expose :8000.
uvicorn app.main:app --host 127.0.0.1 --port 8000 &

# Go server binds 0.0.0.0:$PORT (public, Railway-routed), spawns the Python
# vision/audio workers, and proxies cognition/TTS to 127.0.0.1:8000.
exec ./server
