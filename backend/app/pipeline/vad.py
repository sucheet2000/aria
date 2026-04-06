from __future__ import annotations

import numpy as np
import structlog

logger = structlog.get_logger()

class VADProcessor:
    SAMPLE_RATE = 16000
    CHUNK_MS = 30
    CHUNK_SAMPLES = int(16000 * 30 / 1000)  # 480

    def __init__(self, aggressiveness: int = 0) -> None:
        self._vad = None
        self._aggressiveness = aggressiveness
        self._speech_chunks: list = []
        self._silence_ms: int = 0
        self._in_speech: bool = False
        self._muted: bool = False
        self.MIN_SPEECH_MS = 250
        self.MAX_SILENCE_MS = 400

    def mute(self) -> None:
        """Suppress speech detection while ARIA is speaking TTS."""
        self._muted = True

    def unmute(self) -> None:
        self._muted = False

    def load(self) -> None:
        import webrtcvad
        self._vad = webrtcvad.Vad(self._aggressiveness)
        logger.info("webrtcvad loaded", aggressiveness=self._aggressiveness)

    def process_chunk(self, chunk: np.ndarray) -> tuple:
        if self._muted:
            return False, None

        rms = float(np.sqrt(np.mean(chunk ** 2)))

        # Energy gate only applies when not already tracking speech.
        # During speech, we let low-energy chunks through so silence
        # can be measured and the utterance can be finalized.
        if not self._in_speech and rms < 0.002:
            return False, None

        pcm = np.clip(chunk * 32768, -32768, 32767).astype(np.int16).tobytes()
        try:
            is_speech = self._vad.is_speech(pcm, self.SAMPLE_RATE)
        except Exception:
            is_speech = False

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

    def clear(self) -> None:
        """Discard any accumulated speech chunks."""
        self._speech_chunks = []
        self._silence_ms = 0
        self._in_speech = False

    def _reset(self) -> None:
        self._speech_chunks = []
        self._silence_ms = 0
        self._in_speech = False
