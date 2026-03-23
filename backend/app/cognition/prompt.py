from __future__ import annotations

from app.models.schemas import VisionContext
from app.cognition.conflict import detect_conflict

SYSTEM_PROMPT_TEMPLATE = """You are ARIA's reasoning engine. You observe the user through camera and microphone and maintain a persistent world model of who they are.

Current observation:
  Expressive state: {emotion} ({confidence}% confidence)
  Head pose: pitch {pitch} yaw {yaw} roll {roll}
  Hands visible: {hands_detected}
  Speech: "{transcript}"

Recent symbolic state (last 5 inferences):
{working_memory}

Known facts about this user:
{episodic_memory}

Reasoning instructions:
  1. Determine the user's current goal state: blocked, exploring, focused, distressed, or idle.
  2. {conflict_instruction}
  3. Extract any fact worth remembering as a subject-predicate-object triple. Only store high-confidence facts from explicit statements or strong behavioral patterns.
  4. Keep natural_language_response to 2-3 sentences. No markdown. No lists. Spoken register only.

Respond in this exact JSON with no additional text before or after:
{{
  "symbolic_inference": "one sentence describing user goal state and context",
  "world_model_update": {{
    "triple": {{"subject": "...", "predicate": "...", "object": "..."}},
    "confidence": 0.0,
    "source": "explicit_statement"
  }},
  "natural_language_response": "spoken response here"
}}

If no fact is worth storing, set world_model_update to null."""

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

    return SYSTEM_PROMPT_TEMPLATE.format(
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
