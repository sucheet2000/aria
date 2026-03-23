from __future__ import annotations

import os

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


class TTSRequest(BaseModel):
    text: str
    emotion: str | None = None


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

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(TTS_URL, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.error(
                    "elevenlabs error",
                    status=resp.status_code,
                    body=resp.text[:200],
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
            return Response(
                content=resp.content,
                media_type="audio/mpeg",
            )
    except Exception as e:
        logger.error("tts request failed", error=str(e))
        return Response(status_code=500)
