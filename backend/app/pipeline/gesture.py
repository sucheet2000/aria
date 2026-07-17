from __future__ import annotations

import structlog

logger = structlog.get_logger()

GESTURES = ["none", "wave", "thumbs_up", "thumbs_down", "point", "fist", "open_palm"]


class GestureClassifier:
    def __init__(self) -> None:
        self._model = None

    def load(self, model_path: str | None = None) -> None:
        logger.info("GestureClassifier stub: model loading not yet implemented")

    def predict(self, hand_landmarks: list[list[float]]) -> tuple[str, float]:
        return "none", 0.0
