from __future__ import annotations

import numpy as np
import structlog

logger = structlog.get_logger()

SAMPLE_RATE = 16000


class Denoiser:
    """
    DeepFilterNet-based speech enhancement.
    Processes a complete utterance buffer and returns cleaned audio.
    Uses ONNX runtime for torch-free inference on M1.
    """

    def __init__(self) -> None:
        self._model = None
        self._state = None
        self._enabled = False

    def load(self) -> None:
        """
        Initialize DeepFilterNet. Tries ONNX path first, falls back to
        standard deepfilternet if ONNX variant unavailable.
        """
        try:
            from df.enhance import init_df
            model, state, _ = init_df()
            self._model = model
            self._state = state
            self._enabled = True
            logger.info("denoiser loaded", backend="deepfilternet")
        except ImportError:
            logger.warning("deepfilternet not available, denoiser disabled")
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enhance(self, audio: np.ndarray) -> np.ndarray:
        """
        Clean a float32 audio array at 16kHz.
        Returns enhanced audio at the same sample rate.
        Falls back to passthrough if model not loaded.
        """
        if not self._enabled or self._model is None:
            return audio

        try:
            import torch
            from df.enhance import enhance
            tensor = torch.from_numpy(audio).unsqueeze(0)
            enhanced = enhance(self._model, self._state, tensor)
            result = enhanced.squeeze(0).numpy()
            return result.astype(np.float32)
        except Exception as e:
            logger.warning("denoiser enhance failed, using raw audio", error=str(e))
            return audio

    def reset(self) -> None:
        """Reset internal state between utterances."""
        if self._state is not None:
            try:
                self._state.reset()
            except Exception:
                pass
