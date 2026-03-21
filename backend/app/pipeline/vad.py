from __future__ import annotations
import numpy as np
import structlog

logger = structlog.get_logger()

class VADProcessor:
    SAMPLE_RATE = 16000
    CHUNK_MS = 30
    CHUNK_SAMPLES = int(16000 * 30 / 1000)  # 480

    def __init__(self, aggressiveness: int = 1) -> None:
        self._vad = None
        self._aggressiveness = aggressiveness
        self._speech_chunks: list = []
        self._silence_ms: int = 0
        self._in_speech: bool = False
        self.MIN_SPEECH_MS = 250
        self.MAX_SILENCE_MS = 700

    def load(self) -> None:
        import webrtcvad
        self._vad = webrtcvad.Vad(self._aggressiveness)
        logger.info("webrtcvad loaded", aggressiveness=self._aggressiveness)

    def process_chunk(self, chunk: np.ndarray) -> tuple:
        pcm = np.clip(chunk * 32768, -32768, 32767).astype(np.int16).tobytes()
        try:
            is_speech = self._vad.is_speech(pcm, self.SAMPLE_RATE)
        except Exception:
            is_speech = False

        # Amplitude fallback: if signal is strong enough, treat as speech
        # even if webrtcvad rejects it (handles compressed mic formats)
        if not is_speech:
            amplitude = float(np.abs(chunk).mean())
            if amplitude > 0.01:
                is_speech = True

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
