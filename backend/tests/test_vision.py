from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from app.models.schemas import VisionState
from app.pipeline.vision import VisionPipeline

WORKER = Path(__file__).parent.parent / "app" / "pipeline" / "vision_worker.py"


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


def test_worker_synthetic_output_schema() -> None:
    result = subprocess.run(
        [sys.executable, str(WORKER), "--synthetic", "--duration", "1"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"worker exited non-zero: {result.stderr}"
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    assert len(lines) > 0, "worker produced no output lines"

    for line in lines:
        frame = json.loads(line)
        assert "face_landmarks" in frame
        assert "emotion" in frame
        assert "head_pose" in frame
        assert "hand_landmarks" in frame
        assert "timestamp" in frame

        assert frame["emotion"] == "neutral"
        assert isinstance(frame["timestamp"], float)
        assert isinstance(frame["hand_landmarks"], list)

        pose = frame["head_pose"]
        assert "pitch" in pose
        assert "yaw" in pose
        assert "roll" in pose


def test_worker_synthetic_face_landmarks_count() -> None:
    result = subprocess.run(
        [sys.executable, str(WORKER), "--synthetic", "--duration", "1"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"worker exited non-zero: {result.stderr}"
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    assert len(lines) > 0, "worker produced no output lines"

    first = json.loads(lines[0])
    assert len(first["face_landmarks"]) == 478, (
        f"expected 478 face landmarks, got {len(first['face_landmarks'])}"
    )
    for point in first["face_landmarks"]:
        assert len(point) == 3
