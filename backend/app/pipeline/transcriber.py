from __future__ import annotations

import numpy as np
import structlog

logger = structlog.get_logger()

SAMPLE_RATE = 16000


class Transcriber:
    """faster-whisper based speech-to-text transcriber."""

    def __init__(self, model_size: str = "base", device: str = "auto") -> None:
        self._model_size = model_size
        self._device = device
        self._model = None

    def load(self) -> None:
        from faster_whisper import WhisperModel
        compute_type = "int8"
        device = "cpu"
        self._model = WhisperModel(
            self._model_size,
            device=device,
            compute_type=compute_type,
        )
        logger.info("whisper model loaded", model=self._model_size)

    def transcribe(self, audio_chunks: list[np.ndarray]) -> tuple[str, float]:
        """
        Transcribe a list of audio chunks (numpy float32 arrays at 16kHz).
        Returns (transcript_text, confidence).
        """
        if self._model is None:
            raise RuntimeError("Transcriber not loaded — call load() first")

        audio = np.concatenate(audio_chunks).astype(np.float32)
        if audio.max() > 1.0:
            audio = audio / 32768.0

        segments, info = self._model.transcribe(
            audio,
            language="en",
            beam_size=5,
            vad_filter=False,
            word_timestamps=False,
        )

        text_parts = []
        confidences = []
        for segment in segments:
            text_parts.append(segment.text.strip())
            confidence = min(1.0, max(0.0, (segment.avg_logprob + 1.0)))
            confidences.append(confidence)

        transcript = " ".join(text_parts).strip()
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return transcript, round(avg_confidence, 3)
