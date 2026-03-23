from __future__ import annotations
import time
import numpy as np
import structlog

logger = structlog.get_logger()

SAMPLE_RATE = 16000

BASE_DOMAIN_PROMPT = (
    "Software engineering, Go, Python, TypeScript, React, Next.js, "
    "ARIA, machine learning, neural networks, MediaPipe, WebSocket, "
    "FastAPI, ChromaDB, memory, vision, gesture, avatar"
)


class Transcriber:
    """
    faster-whisper based speech-to-text transcriber.
    Supports dynamic keyword injection from the cognition layer.
    """

    def __init__(self, model_size: str = "base", device: str = "auto") -> None:
        self._model_size = model_size
        self._device = device
        self._model = None
        self._dynamic_keywords: list[str] = []
        self._condition_on_previous = True

    def load(self) -> None:
        from faster_whisper import WhisperModel
        self._model = WhisperModel(
            self._model_size,
            device="cpu",
            compute_type="int8",
        )
        logger.info("whisper model loaded", model=self._model_size)

    # --- Dynamic keyword injection hook ---
    # Sprint 7: ChromaDB will call this method to inject context-relevant
    # keywords retrieved from episodic memory before each transcription.
    # For example, if the user has been discussing Arsenal, this will be
    # called with ["Arsenal", "football", "match", "Premier League"] to
    # prevent domain bleed from previous technical conversations.
    def set_dynamic_keywords(self, keywords: list[str]) -> None:
        """
        Inject domain keywords from the cognition layer.
        Called by ChromaDB retrieval layer in Sprint 7.
        keywords: list of terms relevant to current conversation context
        """
        self._dynamic_keywords = keywords
        logger.debug("dynamic keywords updated", count=len(keywords))

    def reset_context(self) -> None:
        """
        Reset transcription context when topic shifts significantly.
        Called by the cognition layer when symbolic inference detects
        a topic change (cosine similarity below threshold).
        Clears dynamic keywords and disables previous-text conditioning
        for one transcription cycle to prevent domain bleed.
        """
        self._dynamic_keywords = []
        self._condition_on_previous = False
        logger.debug("transcription context reset")

    def _build_initial_prompt(self) -> str:
        """
        Combine base domain vocabulary with dynamic keywords.
        Dynamic keywords take priority and appear first.
        """
        if self._dynamic_keywords:
            dynamic_part = ", ".join(self._dynamic_keywords)
            return f"{dynamic_part}. {BASE_DOMAIN_PROMPT}"
        return BASE_DOMAIN_PROMPT

    def transcribe(self, audio_chunks: list[np.ndarray]) -> tuple[str, float]:
        """
        Transcribe a list of audio chunks (float32 at 16kHz).
        Returns (transcript_text, confidence).
        """
        if self._model is None:
            raise RuntimeError("Transcriber not loaded, call load() first")

        audio = np.concatenate(audio_chunks).astype(np.float32)
        if audio.max() > 1.0:
            audio = audio / 32768.0

        initial_prompt = self._build_initial_prompt()
        condition = self._condition_on_previous

        # Re-enable previous-text conditioning after a reset cycle
        self._condition_on_previous = True

        segments, info = self._model.transcribe(
            audio,
            language="en",
            beam_size=5,
            vad_filter=False,
            word_timestamps=False,
            initial_prompt=initial_prompt,
            condition_on_previous_text=condition,
        )

        text_parts = []
        confidences = []
        for segment in segments:
            text_parts.append(segment.text.strip())
            confidence = min(1.0, max(0.0, segment.avg_logprob + 1.0))
            confidences.append(confidence)

        transcript = " ".join(text_parts).strip()
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return transcript, round(avg_confidence, 3)
