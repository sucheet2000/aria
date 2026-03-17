# ARIA — Adaptive Real-time Intelligence Avatar

A multimodal AGI avatar system combining real-time vision, gesture recognition, speech processing, and Claude-powered cognition in a live interactive interface.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full system design.

## Setup

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # fill in API keys
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at http://localhost:3000 and connects to the backend at http://localhost:8000.

## Development

| Command | Description |
|---|---|
| `pytest tests/ -v` | Run backend tests |
| `ruff check .` | Lint backend |
| `mypy app tests` | Type-check backend |
| `npm run lint` | Lint frontend |
| `npm run type-check` | Type-check frontend |

## Local dev with Docker

```bash
docker-compose up
```
