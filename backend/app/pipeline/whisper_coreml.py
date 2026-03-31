"""
WhisperCoreML — CoreML encoder + openai-whisper CPU decoder.

Architecture:
  - Encoder: CoreML (ANE-routable, compute_units=ALL)
    Input:  mel spectrogram (1, 80, 3000) float32
    Output: encoder_hidden_states
  - Decoder: openai-whisper BeamSearch on CPU
    (CoreML decoder deferred — dynamic shapes prevent static graph export)

Fallback chain:
  1. CoreML encoder present + openai-whisper available → hybrid path
  2. CoreML encoder missing OR coremltools import fails → faster-whisper

Interface matches Transcriber exactly:
  load()
  transcribe(audio_chunks: list[np.ndarray]) -> tuple[str, float]

Thread safety: a threading.Lock guards all model calls so callers
don't need to serialize externally.
"""
from __future__ import annotations

import pathlib
import threading
from typing import TYPE_CHECKING

import numpy as np
import structlog

if TYPE_CHECKING:
    import coremltools as ct
    import whisper as openai_whisper

logger = structlog.get_logger()

SAMPLE_RATE = 16000
MEL_BINS = 80
MEL_FRAMES = 3000

_MODELS_DIR = pathlib.Path(__file__).parent.parent.parent / "models"
_ENCODER_PATH = _MODELS_DIR / "whisper-tiny-encoder.mlpackage"


class WhisperCoreML:
    """
    Drop-in replacement for Transcriber that routes the encoder through CoreML.

    When the .mlpackage is absent or any import fails, falls back silently to
    faster-whisper so the audio pipeline keeps running.
    """

    def __init__(self, model_size: str = "tiny") -> None:
        self._model_size = model_size
        self._use_coreml = False
        self._lock = threading.Lock()

        # CoreML path
        self._coreml_encoder = None   # ct.models.MLModel
        self._whisper_model = None    # openai_whisper.Whisper (for decoder + mel)

        # Fallback path
        self._fallback_model = None   # faster_whisper.WhisperModel

    def load(self) -> None:
        """
        Try to load the CoreML encoder + openai-whisper.
        Falls back to faster-whisper on any failure.
        """
        if _ENCODER_PATH.exists():
            try:
                import coremltools as ct
                import whisper as openai_whisper

                logger.info("loading CoreML encoder", path=str(_ENCODER_PATH))
                self._coreml_encoder = ct.models.MLModel(str(_ENCODER_PATH))
                self._whisper_model = openai_whisper.load_model(self._model_size).eval()
                self._use_coreml = True
                logger.info("whisper backend active", backend="coreml+cpu-decoder",
                            model=self._model_size)
                return
            except Exception as exc:
                logger.warning("CoreML load failed, falling back to faster-whisper",
                               error=str(exc))

        self._load_fallback()

    def _load_fallback(self) -> None:
        from faster_whisper import WhisperModel
        self._fallback_model = WhisperModel(
            self._model_size,
            device="cpu",
            compute_type="int8",
        )
        self._use_coreml = False
        logger.info("whisper backend active", backend="faster-whisper",
                    model=self._model_size)

    def transcribe(self, audio_chunks: list[np.ndarray]) -> tuple[str, float]:
        """
        Transcribe audio. Thread-safe — serialised by internal lock.

        Args:
            audio_chunks: list of float32 arrays at 16kHz

        Returns:
            (transcript_text, confidence)  — same contract as Transcriber
        """
        audio = np.concatenate(audio_chunks).astype(np.float32)
        if audio.max() > 1.0:
            audio = audio / 32768.0

        with self._lock:
            if self._use_coreml:
                return self._transcribe_coreml(audio)
            return self._transcribe_fallback(audio)

    def _transcribe_coreml(self, audio: np.ndarray) -> tuple[str, float]:
        """Hybrid: CoreML encoder → openai-whisper CPU decoder."""
        import torch
        import whisper as openai_whisper
        from whisper.audio import N_FRAMES, HOP_LENGTH, SAMPLE_RATE as W_SR
        from whisper.decoding import DecodingOptions, decode

        # --- mel spectrogram (openai-whisper) ---
        # pad/trim to exactly 30s (= MEL_FRAMES columns after feature extraction)
        audio_padded = openai_whisper.pad_or_trim(audio)
        mel = openai_whisper.log_mel_spectrogram(audio_padded)  # (80, 3000)

        # --- CoreML encoder ---
        mel_np = mel.numpy().astype(np.float32)[np.newaxis]  # (1, 80, 3000)
        enc_out_np = self._coreml_encoder.predict({"mel": mel_np})["encoder_output"]
        # shape: (1, 1500, 384) for tiny
        encoder_output = torch.from_numpy(enc_out_np)  # (1, 1500, 384)

        # --- openai-whisper decoder (CPU) ---
        options = DecodingOptions(language="en", fp16=False)
        results = decode(self._whisper_model, encoder_output, options)

        if not results:
            return "", 0.0

        result = results[0]
        text = result.text.strip()
        # avg_logprob is in (-inf, 0]. Map to [0, 1] same way Transcriber does.
        confidence = min(1.0, max(0.0, result.avg_logprob + 1.0))
        return text, round(confidence, 3)

    def _transcribe_fallback(self, audio: np.ndarray) -> tuple[str, float]:
        """faster-whisper fallback — same logic as Transcriber."""
        if self._fallback_model is None:
            raise RuntimeError("WhisperCoreML not loaded — call load() first")

        segments, _info = self._fallback_model.transcribe(
            audio,
            language="en",
            beam_size=5,
            vad_filter=False,
            word_timestamps=False,
        )

        text_parts: list[str] = []
        confidences: list[float] = []
        for seg in segments:
            text_parts.append(seg.text.strip())
            confidences.append(min(1.0, max(0.0, seg.avg_logprob + 1.0)))

        transcript = " ".join(text_parts).strip()
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return transcript, round(avg_confidence, 3)
