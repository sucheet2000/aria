from __future__ import annotations

import numpy as np
import structlog

logger = structlog.get_logger()

EMOTIONS = ["neutral", "happy", "sad", "angry", "surprised", "fearful", "disgusted"]


class EmotionClassifier:
    def __init__(self) -> None:
        self._model = None

    def load(self, model_path: str | None = None) -> None:
        logger.info("EmotionClassifier stub: model loading not yet implemented")

    def predict(self, face_landmarks: list[list[float]]) -> tuple[str, float]:
        return "neutral", 1.0
