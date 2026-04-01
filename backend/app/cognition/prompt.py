from __future__ import annotations

import pathlib

from app.models.schemas import VisionContext
from app.cognition.conflict import detect_conflict

_OBSERVATION_TEMPLATE = """\
Current observation:
  Expressive state: {emotion} ({confidence}% confidence)
  Head pose: pitch {pitch} yaw {yaw} roll {roll}
  Hands visible: {hands_detected}
  Speech: "{transcript}"

Recent symbolic state (last 5 inferences):
{working_memory}

Known facts about this user:
{episodic_memory}

{conflict_instruction}"""


def _load_soul() -> str:
    """Load ARIA's identity from SOUL.md at repo root."""
    soul_path = pathlib.Path(__file__).parent.parent.parent.parent / "SOUL.md"
    if soul_path.exists():
        return soul_path.read_text()
    return ""  # fallback if SOUL.md missing

NO_CONFLICT_INSTRUCTION = "Respond naturally to what the user said."

CONFLICT_INSTRUCTION = (
    "Speech sentiment and expressive state conflict significantly. "
    "Do not validate the speech or challenge it. "
    "Respond to the underlying state suggested by the visual evidence "
    "via open invitation, never assertion. "
    "Example: user says 'I am fine' but looks stressed — respond with "
    "'I am here if something is on your mind.' not 'Glad you are fine.'"
)


def build_system_prompt(
    vision: VisionContext,
    transcript: str,
    working_memory: list[str],
    episodic_memory: list[str],
) -> str:
    conflict, delta = detect_conflict(
        transcript, vision.emotion, vision.confidence
    )

    working_mem_text = (
        "\n".join(f"  - {m}" for m in working_memory[-5:])
        if working_memory
        else "  None yet."
    )

    episodic_mem_text = (
        "\n".join(f"  - {m}" for m in episodic_memory[:10])
        if episodic_memory
        else "  None yet."
    )

    observation = _OBSERVATION_TEMPLATE.format(
        emotion=vision.emotion,
        confidence=round(vision.confidence * 100, 1),
        pitch=round(vision.pitch, 1),
        yaw=round(vision.yaw, 1),
        roll=round(vision.roll, 1),
        hands_detected="yes" if vision.hands_detected else "no",
        transcript=transcript,
        working_memory=working_mem_text,
        episodic_memory=episodic_mem_text,
        conflict_instruction=CONFLICT_INSTRUCTION if conflict else NO_CONFLICT_INSTRUCTION,
    )

    return _load_soul() + "\n\n" + observation
