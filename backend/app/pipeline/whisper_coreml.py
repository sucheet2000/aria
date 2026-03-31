"""
WhisperCoreML — CoreML encoder + openai-whisper CPU decoder.

Architecture:
  - Encoder: CoreML (ANE-routable, compute_units=ALL)
    Input:  mel spectrogram (1, 80, 3000) float32
    Output: encoder_hidden_states
  - Decoder: openai-whisper BeamSearch on CPU
    (CoreML decoder deferred — dynamic shapes prevent static graph export)

Fallback chain:
  1. CoreML encoder for selected model size present + openai-whisper available → hybrid path
  2. CoreML encoder missing, shape mismatch, OR any import failure → faster-whisper
  3. Runtime CoreML exception → auto-demote to faster-whisper (one-time warning)

Interface matches Transcriber exactly:
  load()
  transcribe(audio_chunks: list[np.ndarray]) -> tuple[str, float]

Thread safety:
  - A threading.Lock serialises ALL state mutation (load and transcribe).
  - An explicit _state machine ("unloaded" | "loading" | "ready" | "failed")
    ensures transcribe() never operates on partially-initialised state.
"""
from __future__ import annotations

import pathlib
import threading
from typing import TYPE_CHECKING, Literal

import numpy as np
import structlog

from app.pipeline.transcriber import BASE_DOMAIN_PROMPT

if TYPE_CHECKING:
    import coremltools as ct
    import whisper as openai_whisper

logger = structlog.get_logger()

SAMPLE_RATE = 16000
MEL_BINS = 80
MEL_FRAMES = 3000

_MODELS_DIR = pathlib.Path(__file__).parent.parent.parent / "models"

_State = Literal["unloaded", "loading", "ready", "failed"]


class WhisperCoreML:
    """
    Drop-in replacement for Transcriber that routes the encoder through CoreML.

    Model-size contract: encoder artifact is bound to self._model_size.
    If no matching whisper-{model_size}-encoder.mlpackage exists, or if the
    encoder fails a load-time shape smoke test, the class falls back to
    faster-whisper without raising.

    Runtime demotion: if a CoreML inference call fails after a successful load,
    _use_coreml is set to False and a one-time warning is emitted. All
    subsequent calls use faster-whisper automatically.
    """

    def __init__(self, model_size: str = "tiny") -> None:
        self._model_size = model_size
        # Encoder path is bound to model_size — prevents tiny/base pairing.
        self._encoder_path = _MODELS_DIR / f"whisper-{model_size}-encoder.mlpackage"

        self._lock = threading.Lock()
        self._state: _State = "unloaded"
        self._use_coreml = False

        # CoreML path
        self._coreml_encoder = None   # ct.models.MLModel
        self._whisper_model = None    # openai_whisper.Whisper (decoder + mel utils)

        # Fallback path
        self._fallback_model = None   # faster_whisper.WhisperModel

    def load(self) -> None:
        """
        Load models. All state mutations are lock-guarded.
        Sets _state to "ready" on success or "failed" on unrecoverable error.
        Falls back to faster-whisper on any CoreML-path failure.
        """
        with self._lock:
            self._state = "loading"
            try:
                self._load_locked()
            except Exception as exc:
                self._state = "failed"
                logger.error("WhisperCoreML load failed entirely", error=str(exc))
                raise

    def _load_locked(self) -> None:
        """Called inside self._lock. Attempts CoreML, always loads faster-whisper fallback."""
        if self._encoder_path.exists():
            try:
                import coremltools as ct
                import whisper as openai_whisper

                logger.info("loading CoreML encoder", path=str(self._encoder_path),
                            model=self._model_size)
                encoder = ct.models.MLModel(str(self._encoder_path))

                # Shape smoke test — verify encoder accepts expected input,
                # was built for this model size, and produces output with the
                # expected encoder hidden-state dimensions.
                _WHISPER_DIMS = {
                    "tiny":  (1, 1500, 384),
                    "base":  (1, 1500, 512),
                    "small": (1, 1500, 768),
                    "medium":(1, 1500, 1024),
                    "large": (1, 1500, 1280),
                }
                dummy = {"mel": np.zeros((1, MEL_BINS, MEL_FRAMES), dtype=np.float32)}
                out = encoder.predict(dummy)
                if "encoder_output" not in out:
                    raise ValueError(
                        f"CoreML encoder missing 'encoder_output' key; got {list(out.keys())}"
                    )
                expected_shape = _WHISPER_DIMS.get(self._model_size)
                if expected_shape is not None:
                    actual_shape = tuple(out["encoder_output"].shape)
                    if actual_shape != expected_shape:
                        raise ValueError(
                            f"CoreML encoder output shape {actual_shape} does not match "
                            f"expected {expected_shape} for model '{self._model_size}'. "
                            f"Encoder/decoder size mismatch — re-export with the correct model."
                        )

                self._coreml_encoder = encoder
                self._whisper_model = openai_whisper.load_model(self._model_size).eval()
                self._use_coreml = True
                logger.info("whisper backend active", backend="coreml+cpu-decoder",
                            model=self._model_size)
            except Exception as exc:
                logger.warning(
                    "CoreML load failed — falling back to faster-whisper",
                    model=self._model_size,
                    encoder_path=str(self._encoder_path),
                    error=str(exc),
                )
                # Clear any partially-set CoreML state before fallback.
                self._coreml_encoder = None
                self._whisper_model = None
                self._use_coreml = False
        else:
            logger.warning(
                "CoreML encoder not found for model size — using faster-whisper",
                model=self._model_size,
                expected_path=str(self._encoder_path),
            )

        # Always pre-load faster-whisper so runtime demotion (_use_coreml → False)
        # can immediately call _transcribe_fallback() without raising.
        # When CoreML already succeeded, guard this separately — a missing
        # faster-whisper install must not kill a healthy CoreML backend.
        if self._use_coreml:
            try:
                self._load_fallback_locked()
            except Exception as exc:
                logger.warning(
                    "faster-whisper preload failed; runtime demotion unavailable",
                    model=self._model_size,
                    error=str(exc),
                )
                # CoreML is ready; keep _use_coreml=True and stay ready.
                self._state = "ready"
        else:
            # CoreML not active — faster-whisper is the only backend; hard fail on error.
            self._load_fallback_locked()

    def _load_fallback_locked(self) -> None:
        """Called inside self._lock. Loads faster-whisper. Does not mutate _use_coreml."""
        from faster_whisper import WhisperModel
        self._fallback_model = WhisperModel(
            self._model_size,
            device="cpu",
            compute_type="int8",
        )
        self._state = "ready"
        logger.info("whisper fallback preloaded", backend="faster-whisper",
                    model=self._model_size)

    def transcribe(self, audio_chunks: list[np.ndarray]) -> tuple[str, float]:
        """
        Transcribe audio. Thread-safe — serialised by internal lock.

        State guards:
          - "unloaded" / "loading": returns ("", 0.0) with a warning.
          - "failed": attempts faster-whisper fallback if model is available,
            otherwise returns ("", 0.0).
          - "ready": runs inference, auto-demotes to faster-whisper on CoreML
            runtime exception (one-time warning).

        Args:
            audio_chunks: list of float32 arrays at 16kHz

        Returns:
            (transcript_text, confidence)  — same contract as Transcriber
        """
        audio = np.concatenate(audio_chunks).astype(np.float32)
        if audio.max() > 1.0:
            audio = audio / 32768.0

        with self._lock:
            if self._state in ("unloaded", "loading"):
                logger.warning("WhisperCoreML not ready", state=self._state)
                return ("", 0.0)

            if self._state == "failed":
                if self._fallback_model is not None:
                    return self._transcribe_fallback(audio)
                return ("", 0.0)

            # _state == "ready"
            if self._use_coreml:
                try:
                    return self._transcribe_coreml(audio)
                except Exception as exc:
                    if self._use_coreml:   # guard: emit warning exactly once
                        if self._fallback_model is not None:
                            self._use_coreml = False
                            logger.warning(
                                "CoreML transcription failed, demoting to faster-whisper",
                                error=str(exc),
                            )
                        else:
                            # No fallback available — keep CoreML active so the next
                            # call retries rather than entering a permanently broken state.
                            logger.error(
                                "CoreML transcription failed; no fallback — dropping utterance",
                                error=str(exc),
                            )
                            return ("", 0.0)
            return self._transcribe_fallback(audio)

    def _transcribe_coreml(self, audio: np.ndarray) -> tuple[str, float]:
        """Hybrid: CoreML encoder → openai-whisper CPU decoder."""
        import torch
        import whisper as openai_whisper
        from whisper.decoding import DecodingOptions, decode

        # pad/trim to exactly 30s (= MEL_FRAMES columns after feature extraction)
        audio_padded = openai_whisper.pad_or_trim(audio)
        mel = openai_whisper.log_mel_spectrogram(audio_padded)  # (80, 3000)

        mel_np = mel.numpy().astype(np.float32)[np.newaxis]  # (1, 80, 3000)
        enc_out_np = self._coreml_encoder.predict({"mel": mel_np})["encoder_output"]
        encoder_output = torch.from_numpy(enc_out_np)

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
        """faster-whisper fallback — behaviorally equivalent to Transcriber."""
        if self._fallback_model is None:
            raise RuntimeError("WhisperCoreML not loaded — call load() first")

        segments, _info = self._fallback_model.transcribe(
            audio,
            language="en",
            beam_size=5,
            vad_filter=False,
            word_timestamps=False,
            initial_prompt=BASE_DOMAIN_PROMPT,
            condition_on_previous_text=True,
        )

        text_parts: list[str] = []
        confidences: list[float] = []
        for seg in segments:
            text_parts.append(seg.text.strip())
            confidences.append(min(1.0, max(0.0, seg.avg_logprob + 1.0)))

        transcript = " ".join(text_parts).strip()
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return transcript, round(avg_confidence, 3)
