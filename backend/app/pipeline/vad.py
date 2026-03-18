from __future__ import annotations

import numpy as np
import structlog

logger = structlog.get_logger()


class VADProcessor:
    """Silero VAD wrapper for real-time voice activity detection."""

    SAMPLE_RATE = 16000
    CHUNK_MS = 30
    CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_MS / 1000)  # 480 samples
    SPEECH_THRESHOLD = 0.5
    MIN_SPEECH_MS = 250
    MAX_SILENCE_MS = 700

    def __init__(self) -> None:
        self._model = None
        self._speech_chunks: list[np.ndarray] = []
        self._silence_ms: int = 0
        self._in_speech: bool = False

    def load(self) -> None:
        import torch
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            trust_repo=True,
        )
        self._model = model
        self._get_speech_timestamps = utils[0]
        logger.info("silero VAD loaded")

    def process_chunk(self, chunk: np.ndarray) -> tuple[bool, list[np.ndarray] | None]:
        """
        Process a 30ms audio chunk.
        Returns (is_speech, completed_utterance_chunks or None).
        completed_utterance_chunks is non-None when an utterance just ended.
        """
        import torch
        if self._model is None:
            raise RuntimeError("VAD not loaded — call load() first")

        tensor = torch.from_numpy(chunk).float()
        confidence = self._model(tensor, self.SAMPLE_RATE).item()
        is_speech = confidence >= self.SPEECH_THRESHOLD

        if is_speech:
            self._in_speech = True
            self._silence_ms = 0
            self._speech_chunks.append(chunk.copy())
            return True, None

        if self._in_speech:
            self._silence_ms += self.CHUNK_MS
            self._speech_chunks.append(chunk.copy())

            if self._silence_ms >= self.MAX_SILENCE_MS:
                total_ms = len(self._speech_chunks) * self.CHUNK_MS
                if total_ms >= self.MIN_SPEECH_MS:
                    completed = list(self._speech_chunks)
                    self._reset()
                    return False, completed
                self._reset()

        return False, None

    def _reset(self) -> None:
        self._speech_chunks = []
        self._silence_ms = 0
        self._in_speech = False
