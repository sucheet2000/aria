from __future__ import annotations

from pydantic import BaseModel, Field


class VisionState(BaseModel):
    face_landmarks: list[list[float]] = Field(default_factory=list)
    emotion: str = "neutral"
    head_pose: dict[str, float] = Field(default_factory=dict)
    hand_landmarks: list[list[float]] = Field(default_factory=list)
    timestamp: float = 0.0


class AudioTranscript(BaseModel):
    transcript: str = ""
    is_final: bool = False
    confidence: float = 0.0
    duration_ms: int = 0
    timestamp: float = Field(default_factory=lambda: __import__('time').time())
