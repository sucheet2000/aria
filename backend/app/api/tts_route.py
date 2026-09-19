from __future__ import annotations

import asyncio
import os
import random
import time

import httpx
import structlog
from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import settings
from app.pipeline.voice_engine import voice_engine

logger = structlog.get_logger()
router = APIRouter()

VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
TTS_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream"

_BACKOFF_BASE = 0.4
_BACKOFF_CAP = 0.75
_RETRY_BUDGET_SECONDS = 14.0  # hard ceiling; must stay under the frontend 15s AbortSignal


class TTSRequest(BaseModel):
    text: str
    emotion: str | None = None


def _worst_case_budget_seconds() -> float:
    return (
        settings.ELEVENLABS_TIMEOUT_SECONDS * (settings.ELEVENLABS_MAX_RETRIES + 1)
        + _BACKOFF_CAP * settings.ELEVENLABS_MAX_RETRIES
    )


def _provider_status(resp: httpx.Response) -> str | None:
    """ElevenLabs' machine-readable error code, if any.

    Two body shapes occur: ``{"detail": {"status": "<code>", ...}}`` for API
    errors and the FastAPI-style ``{"detail": [{"type", "loc", "msg", "input"}]}``
    for 422 validation errors. S2: a validation body echoes the request text in
    ``input``/``msg``, so only the enum ``type`` and the field path are kept.
    """
    try:
        detail = resp.json().get("detail")
    except Exception:
        return None
    if isinstance(detail, dict):
        status = detail.get("status")
        return str(status)[:64] if isinstance(status, str) else None
    if isinstance(detail, list) and detail and isinstance(detail[0], dict):
        first = detail[0]
        kind = first.get("type")
        loc = first.get("loc")
        if not isinstance(kind, str):
            return None
        path = ".".join(str(part) for part in loc) if isinstance(loc, list) else ""
        return f"{kind}:{path}"[:64] if path else kind[:64]
    return None


def _retryable(status: int) -> bool:
    return status == 429 or 500 <= status < 600


def _compute_delay(attempt: int, resp: httpx.Response) -> float:
    retry_after = resp.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return float(retry_after)
        except ValueError:
            pass
    delay = min(_BACKOFF_CAP, _BACKOFF_BASE * 2**attempt)
    return delay / 2 + random.uniform(0, delay / 2)


@router.post("/api/tts")
async def tts(req: TTSRequest) -> Response:
    if not settings.ELEVENLABS_API_KEY:
        return Response(status_code=503, content=b"")

    payload = voice_engine.build_request_payload(
        text=req.text,
        voice_id=VOICE_ID,
        emotion=req.emotion,
        use_turbo=True,
    )

    headers = {
        "xi-api-key": settings.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    deadline = time.monotonic() + _RETRY_BUDGET_SECONDS
    timeout = settings.ELEVENLABS_TIMEOUT_SECONDS
    max_retries = settings.ELEVENLABS_MAX_RETRIES

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            attempt = 0
            while True:
                resp = await client.post(TTS_URL, json=payload, headers=headers)
                if resp.status_code == 200:
                    return Response(content=resp.content, media_type="audio/mpeg")
                if not _retryable(resp.status_code) or attempt >= max_retries:
                    break
                delay = _compute_delay(attempt, resp)
                if time.monotonic() + delay + timeout > deadline:
                    break
                logger.warning(
                    "elevenlabs retry",
                    status=resp.status_code,
                    attempt=attempt + 1,
                    delay=round(delay, 3),
                )
                await asyncio.sleep(delay)
                attempt += 1

            logger.error(
                "elevenlabs error",
                status=resp.status_code,
                provider_status=_provider_status(resp),
                body_chars=len(resp.text),
                attempts=attempt + 1,
            )
            if resp.status_code == 402:
                logger.warning(
                    "ElevenLabs 402: voice ID may be a paid library voice. "
                    "Go to elevenlabs.io -> Voice Lab -> Create Voice, "
                    "copy the voice ID, and set ELEVENLABS_VOICE_ID env var. "
                    "Falling back to browser TTS."
                )
                return Response(status_code=503, content=b"")
            return Response(status_code=resp.status_code)
    except Exception as e:
        logger.error("tts request failed", error_type=type(e).__name__, error=str(e)[:200])
        return Response(status_code=500)
