from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field

from pydantic import BaseModel, Field


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


# --- Cognition API types ---

class PerceptionFrame(BaseModel):
    """Trimmed per-frame perception data forwarded to the cognition layer.

    Carries only the fields the LLM prompt and cognition route actually
    consume (emotion, head-pose, presence flags). Raw landmarks are stripped
    before this point.
    """
    emotion: str = "neutral"
    confidence: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0
    face_detected: bool = False
    hands_detected: bool = False


class ConversationTurn(BaseModel):
    role: str
    content: str


class CognitionRequest(BaseModel):
    message: str
    vision_state: PerceptionFrame = Field(default_factory=PerceptionFrame)
    conversation_history: list[ConversationTurn] = Field(default_factory=list)
    working_memory: list[str] = Field(default_factory=list)
    # Gesture fields forwarded from the browser perception layer
    gesture: str = "none"
    two_hand_gesture: str = "NONE"
    pointing_vector: list[float] | None = None
    session_id: str = ""


class WorldModelTriple(BaseModel):
    subject: str
    predicate: str
    object: str


class WorldModelUpdate(BaseModel):
    triple: WorldModelTriple
    confidence: float
    source: str


class CognitionResponse(BaseModel):
    """Neurosymbolic response from the LLM client.

    Named CognitionResponse to align with proto CognitionResponse and Go handler.
    """
    symbolic_inference: str
    world_model_update: WorldModelUpdate | None = None
    natural_language_response: str
    # Internal signal (never serialized to the wire): True when the native
    # web_fetch server tool actually ran on this turn. The cognition route uses
    # it to suppress the fact-write so a fetched page cannot poison owner memory.
    used_web_fetch: bool = False


# --- Memory data-control API types (S3) ---

class MemoryEntry(BaseModel):
    """One stored document plus the metadata ARIA actually persists.
    Metadata keys absent from the store are omitted from the response."""
    id: str
    collection: str
    content: str
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    confidence: float | None = None
    source: str | None = None
    timestamp: float | None = None
    expires_at: float | None = None


class MemoryExport(BaseModel):
    profile: list[MemoryEntry]
    episodic: list[MemoryEntry]
    working: list[MemoryEntry]
    truncated: list[str]


class MemoryDeleteCounts(BaseModel):
    profile: int
    episodic: int
    working: int


class MemoryDeleteResult(BaseModel):
    deleted: MemoryDeleteCounts


class MemoryEntryDeleted(BaseModel):
    deleted: str


@dataclass
class SpatialEvent:
    """Typed envelope for a spatial action produced by the gesture-anchor bridge.

    Aligns with proto SpatialEvent message. event_type values:
      "anchor_registered" — anchor_id populated
      "anchors_bonded"    — anchor_ids populated
      "anchor_thrown"     — anchor_id + velocity populated
      "world_expand"      — factor populated
    """
    event_type: str
    anchor_id: str = ""
    anchor_ids: list[str] = dc_field(default_factory=list)
    velocity: list[float] = dc_field(default_factory=list)
    factor: float = 1.0
    label: str = ""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
