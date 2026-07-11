from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version="0.1.0")


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Internal readiness probe pinged by the Go edge's public ``/ready``.

    Returns 503 until every critical dependency is up: the ChromaDB memory
    store is loaded and ``DATA_DIR`` exists and is writable.
    """
    memory = getattr(request.app.state, "memory", None)
    if memory is None or not getattr(memory, "loaded", False):
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "reason": "memory not loaded"},
        )
    data_dir = Path(settings.DATA_DIR)
    if not data_dir.is_dir() or not os.access(data_dir, os.W_OK):
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "reason": "data_dir not writable"},
        )
    return JSONResponse(status_code=200, content={"status": "ready"})
