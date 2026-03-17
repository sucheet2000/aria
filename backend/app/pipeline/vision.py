from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import numpy as np
import structlog

from app.models.schemas import VisionState

if TYPE_CHECKING:
    import mediapipe as mp  # noqa: F401

logger = structlog.get_logger()


class VisionPipeline:
    def __init__(self) -> None:
        self._face_mesh = None
        self._hands = None
        self._initialized = False

    def initialize(self) -> None:
        try:
            import mediapipe as mp

            self._face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._hands = mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=2,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._initialized = True
            logger.info("VisionPipeline initialized")
        except ImportError:
            logger.warning("mediapipe not available, VisionPipeline running in stub mode")

    async def process_frame(self, frame: np.ndarray) -> VisionState:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._process_frame_sync, frame)

    def _process_frame_sync(self, frame: np.ndarray) -> VisionState:
        if not self._initialized or self._face_mesh is None:
            return VisionState()

        import cv2

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        face_results = self._face_mesh.process(rgb_frame)

        face_landmarks: list[list[float]] = []
        if face_results.multi_face_landmarks:
            for landmark in face_results.multi_face_landmarks[0].landmark:
                face_landmarks.append([landmark.x, landmark.y, landmark.z])

        return VisionState(
            face_landmarks=face_landmarks,
            emotion="neutral",
            head_pose={"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
        )

    def close(self) -> None:
        if self._face_mesh:
            self._face_mesh.close()
        if self._hands:
            self._hands.close()
        self._initialized = False
