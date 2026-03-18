from __future__ import annotations

from pydantic import BaseModel, Field


class WorldModelTriple(BaseModel):
    subject: str
    predicate: str
    object: str


class WorldModelUpdate(BaseModel):
    triple: WorldModelTriple
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    timestamp: float = Field(default_factory=lambda: __import__('time').time())


class SymbolicResponse(BaseModel):
    symbolic_inference: str
    world_model_update: WorldModelUpdate | None = None
    natural_language_response: str


class VisionContext(BaseModel):
    emotion: str = "neutral"
    confidence: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0
    face_detected: bool = False
    hands_detected: bool = False


class CognitionRequest(BaseModel):
    message: str
    vision_context: VisionContext = Field(default_factory=VisionContext)
    conversation_history: list[dict] = Field(default_factory=list)
    working_memory: list[str] = Field(default_factory=list)
    episodic_memory: list[str] = Field(default_factory=list)


class VisionState(BaseModel):
    face_landmarks: list[list[float]] = Field(default_factory=list)
    emotion: str = "neutral"
    head_pose: dict[str, float] = Field(default_factory=dict)
    hand_landmarks: list[list[float]] = Field(default_factory=list)
    timestamp: float = 0.0


class GestureState(BaseModel):
    gesture_name: str = "none"
    confidence: float = 0.0
    hand_landmarks: list[list[float]] = Field(default_factory=list)


class AudioTranscript(BaseModel):
    transcript: str = ""
    is_final: bool = False
    confidence: float = 0.0
    duration_ms: int = 0
    timestamp: float = Field(default_factory=lambda: __import__('time').time())
