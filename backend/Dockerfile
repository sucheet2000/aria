# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1 — build the Go server binary.
# Cross-compiled to linux/amd64 (Railway's runtime) natively on the build host.
# ---------------------------------------------------------------------------
FROM --platform=$BUILDPLATFORM golang:1.26.1-bookworm AS go-builder

WORKDIR /src

COPY backend/go.mod backend/go.sum ./
RUN go mod download

COPY backend/ .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -trimpath -ldflags="-s -w" -o /out/server ./cmd/server

# ---------------------------------------------------------------------------
# Stage 2 — build the Python dependencies into a self-contained venv.
# Needs a build toolchain + Rust because deepfilterlib (a deepfilternet dep)
# ships no cp313 wheel and compiles from source. Kept out of the final image.
# Pinned to linux/amd64 so the wheels/venv match Railway's runtime.
# ---------------------------------------------------------------------------
FROM --platform=linux/amd64 python:3.13-slim AS py-builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        patchelf \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Rust toolchain for building deepfilterlib from source.
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Install the CPU-only torch wheel first so requirements.txt finds torch already
# satisfied and skips the ~3 GB CUDA build (mirrors ci.yml).
COPY backend/requirements.txt ./
RUN pip install --upgrade pip setuptools wheel \
    && pip install torch==2.10.0+cpu --extra-index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 3 — runtime image: slim Python + system libs + the venv + Go binary.
# One image runs both processes (see start.sh): Go public, Python internal.
# ---------------------------------------------------------------------------
FROM --platform=linux/amd64 python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    PYTHON_BIN=python3 \
    PYTHONPATH=/app:/app/gen/python \
    SOUL_PATH=/app/SOUL.md \
    PATH="/opt/venv/bin:${PATH}"

# System libraries the ML stack needs at runtime:
#   libgl1 + libglib2.0-0  -> opencv / mediapipe
#   libportaudio2          -> sounddevice
#   ffmpeg                 -> audio decode
#   ca-certificates        -> HTTPS to Anthropic / ElevenLabs
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libportaudio2 \
        ffmpeg \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=py-builder /opt/venv /opt/venv

COPY backend/ .
COPY SOUL.md /app/SOUL.md
COPY --from=go-builder /out/server ./server
RUN chmod +x ./server ./start.sh

EXPOSE 8080

CMD ["./start.sh"]
