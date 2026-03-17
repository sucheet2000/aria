import numpy as np
import pytest

from app.models.schemas import VisionState
from app.pipeline.vision import VisionPipeline


def test_vision_state_defaults() -> None:
    state = VisionState()
    assert state.emotion == "neutral"
    assert state.face_landmarks == []
    assert state.head_pose == {}


def test_vision_state_with_data() -> None:
    state = VisionState(
        face_landmarks=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        emotion="happy",
        head_pose={"pitch": 5.0, "yaw": -3.0, "roll": 0.5},
    )
    assert state.emotion == "happy"
    assert len(state.face_landmarks) == 2
    assert state.head_pose["pitch"] == 5.0


@pytest.mark.asyncio
async def test_pipeline_returns_vision_state_without_mediapipe() -> None:
    pipeline = VisionPipeline()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = await pipeline.process_frame(frame)
    assert isinstance(result, VisionState)


@pytest.mark.asyncio
async def test_pipeline_uninitialized_returns_defaults() -> None:
    pipeline = VisionPipeline()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = await pipeline.process_frame(frame)
    assert result.emotion == "neutral"
    assert result.face_landmarks == []
