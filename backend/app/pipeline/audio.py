from __future__ import annotations

import structlog

from app.models.schemas import AudioState

logger = structlog.get_logger()


class AudioPipeline:
    def __init__(self) -> None:
        self._whisper_model = None
        self._vad_model = None

    def load(self, whisper_model_size: str = "base") -> None:
        logger.info(
            "AudioPipeline stub: Whisper + VAD loading not yet implemented",
            model_size=whisper_model_size,
        )

    async def process_audio_chunk(self, audio_bytes: bytes) -> AudioState:
        return AudioState(transcript="", is_speaking=False)

    def transcribe(self, audio_path: str) -> str:
        return ""
