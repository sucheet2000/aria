from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, BeforeValidator, Field


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

# How a provider turn was classified (R5). "valid" is the only status whose
# content is trusted; every other status yields the user-safe fallback.
ResponseStatus = Literal["valid", "malformed", "truncated", "empty", "invalid_schema", "refused"]
RESPONSE_STATUSES: tuple[str, ...] = get_args(ResponseStatus)


# --- Perception input contract (Closure 3) ---

# The browser's facial-affect classifier is the ONLY producer of this field:
# frontend/src/lib/perception/emotion.ts. Its label set is the wire protocol, so
# it is the protocol restated here — Python cannot import a TypeScript module,
# and nothing in proto/ carries an emotion. tests/test_input_contracts.py reads
# that file and fails if the two ever diverge, so this is a mirror with an
# alarm on it, not a second vocabulary.
#
# This is the perception INPUT set (what the camera thinks the USER looks like).
# It is deliberately NOT the cognition OUTPUT set that drives the avatar's own
# expression — that one lives in suggestAvatarEmotion (Go) and includes
# "frustrated", which no camera can report. Keeping R3's two directions apart is
# the whole point; merging them is how the avatar ends up mirroring the user.
PerceptionEmotionName = Literal[
    "neutral", "happy", "sad", "angry", "surprised", "fearful", "disgusted"
]
PERCEPTION_EMOTIONS: tuple[str, ...] = get_args(PerceptionEmotionName)


def _to_known_emotion(value: object) -> object:
    """Map anything the classifier did not produce onto "neutral".

    Unknown here means a browser newer than this server, since the two tiers
    deploy independently. The label is advisory — it tints one prompt line and
    feeds conflict detection, which already scores an unrecognised label as no
    signal — so rejecting the request would turn a cosmetic mismatch into a
    total loss of cognition for that user. Degrade, don't fail.

    A role, by contrast, is rejected outright: see ConversationRole.
    """
    if isinstance(value, str) and value not in PERCEPTION_EMOTIONS:
        return "neutral"
    return value


# The annotation carries both halves of the contract: what is allowed, and what
# happens to anything else.
PerceptionEmotion = Annotated[PerceptionEmotionName, BeforeValidator(_to_known_emotion)]


class PerceptionFrame(BaseModel):
    """Trimmed per-frame perception data forwarded to the cognition layer.

    Carries only the fields the LLM prompt and cognition route actually
    consume (emotion, head-pose, presence flags). Raw landmarks are stripped
    before this point.
    """
    emotion: PerceptionEmotion = "neutral"
    # Canonical wire field ``vision_state.emotion_confidence`` (R2): the
    # browser's heuristic facial-affect score for ``emotion`` in [0, 1] — a
    # weighted action-unit score, not a calibrated probability. ``None`` means
    # perception was unavailable (no camera / no frame / stale frame); ``0.0``
    # means a frame was measured but carried no usable facial signal (no face).
    # Neither is ever treated as certainty.
    emotion_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0
    face_detected: bool = False
    hands_detected: bool = False


# Only two roles are ever sent. The browser's store types its own history shut
# (frontend/src/store/ariaStore.ts: role: "user" | "assistant") and nothing else
# produces history — the Go proxy forwards whatever it is given without looking.
#
# "system" is excluded on purpose, though not for the reason an earlier version
# of this comment gave: the provider's Messages API takes only user/assistant in
# ``messages``, so a "system" turn was never going to land beside ARIA's identity
# prompt — llm.py hands the role over unmapped (llm.py:478) and the provider
# rejects the call. The real cost was a 400 on a request already paid for, and a
# failure surfacing as a fallback rather than as "you sent something invalid".
# Refusing it here is the correct place to say so.
#
# Unknown roles are rejected rather than coerced: there is no safe reading of a
# role nobody sends, and a wrong guess silently re-labels who said something.
ConversationRole = Literal["user", "assistant"]
CONVERSATION_ROLES: tuple[str, ...] = get_args(ConversationRole)


class ConversationTurn(BaseModel):
    role: ConversationRole
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
    # Internal signal (never serialized to the wire): how the provider turn was
    # classified (R5). Anything but "valid" is a user-safe fallback whose
    # symbolic_inference is "" and world_model_update is None.
    response_status: ResponseStatus = "valid"


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
