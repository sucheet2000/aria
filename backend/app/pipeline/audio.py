# Production audio runs via audio_worker.py subprocess. This file kept for unit test compatibility.
from __future__ import annotations

import structlog

from app.pipeline.transcriber import Transcriber
from app.pipeline.vad import VADProcessor

logger = structlog.get_logger()


class AudioPipeline:
    def __init__(self) -> None:
        self._vad = VADProcessor()
        self._transcriber = Transcriber()

    def load(self, whisper_model_size: str = "base") -> None:
        logger.info("AudioPipeline.load — delegates to audio_worker.py in production")

    async def process_audio_chunk(self, audio_bytes: bytes) -> dict:
        return {"transcript": "", "is_final": False}

    def transcribe(self, audio_path: str) -> str:
        return ""
