from __future__ import annotations

import numpy as np
import structlog

logger = structlog.get_logger()

class VADProcessor:
    SAMPLE_RATE = 16000
    CHUNK_MS = 30
    CHUNK_SAMPLES = int(16000 * 30 / 1000)  # 480

    def __init__(self, aggressiveness: int = 0, max_utterance_ms: int = 8000) -> None:
        self._vad = None
        self._aggressiveness = aggressiveness
        self._speech_chunks: list = []
        self._silence_ms: int = 0
        self._in_speech: bool = False
        self._muted: bool = False
        self.MIN_SPEECH_MS = 250
        self.MAX_SILENCE_MS = 400
        # V1: this processor is the SOLE owner of the utterance buffer, and the
        # max-utterance cap lives here with it. It is checked on speech frames
        # only, so the trailing-silence window still finalizes normally; the
        # buffer is therefore bounded by max_utterance_ms + MAX_SILENCE_MS
        # (~8.4 s = ~538 KB float32 at the defaults).
        # Clamped so a misconfigured cap can neither flush every single chunk
        # nor sit below the min-speech gate it must cooperate with.
        self.max_utterance_ms = max(max_utterance_ms, self.MIN_SPEECH_MS)

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
        if not self._in_speech and rms < 0.006:
            return False, None

        pcm = np.clip(chunk * 32768, -32768, 32767).astype(np.int16).tobytes()
        try:
            is_speech = self._vad is not None and self._vad.is_speech(pcm, self.SAMPLE_RATE)
        except Exception:
            is_speech = False

        if is_speech:
            self._in_speech = True
            self._silence_ms = 0
            self._speech_chunks.append(chunk.copy())
            if len(self._speech_chunks) * self.CHUNK_MS >= self.max_utterance_ms:
                # Forced flush of an over-long utterance: an atomic
                # take-and-reset, exactly like the silence path below, so the
                # flushed part can never be transcribed a second time. Staying
                # in-speech keeps the continuation flowing without re-arming
                # the idle energy gate.
                completed = list(self._speech_chunks)
                self._reset()
                self._in_speech = True
                return True, completed
            return True, None

        if self._in_speech:
            self._silence_ms += self.CHUNK_MS
            self._speech_chunks.append(chunk.copy())
            if self._silence_ms >= self.MAX_SILENCE_MS:
                total_ms = len(self._speech_chunks) * self.CHUNK_MS
                # Audio before the trailing-silence window. Zero means the
                # buffer is nothing but silence (only reachable right after a
                # forced flush) — Whisper hallucinates words on silence, so it
                # must never be transcribed.
                speech_ms = total_ms - self._silence_ms
                if total_ms >= self.MIN_SPEECH_MS and speech_ms > 0:
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
