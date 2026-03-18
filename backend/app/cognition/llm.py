import json

import structlog
from anthropic import AsyncAnthropic

from app.config import settings
from app.models.schemas import SymbolicResponse, VisionContext, WorldModelUpdate, WorldModelTriple

logger = structlog.get_logger()

_SYSTEM_PROMPT = """\
You are ARIA, a perceptive AI companion with multimodal awareness.

You have access to:
- The user's current message
- Real-time vision state (emotion, head pose, face/hands detected)
- Working memory: recent symbolic inferences from prior turns
- Episodic memory: long-term facts about the user

Respond ONLY with a JSON object using this exact schema:
{
  "symbolic_inference": "<one-sentence summary of what the user is doing or feeling>",
  "world_model_update": {
    "triple": {"subject": "<entity>", "predicate": "<relationship>", "object": "<value>"},
    "confidence": <0.0-1.0>,
    "source": "<explicit_statement | inferred | observed>"
  } or null,
  "natural_language_response": "<2-3 sentence spoken response>"
}

world_model_update must be null if no new durable fact is worth storing.
Do not include markdown, explanation, or any text outside the JSON object.
Keep natural_language_response conversational and concise.
"""


class LLMClient:
    def __init__(self, api_key: str = "") -> None:
        key = api_key or settings.ANTHROPIC_API_KEY
        self._client = AsyncAnthropic(api_key=key)

    async def generate_response(
        self,
        user_message: str,
        system_prompt: str = "You are ARIA, a helpful multimodal AGI avatar.",
        max_tokens: int = 1024,
    ) -> str:
        message = await self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        content = message.content[0]
        if hasattr(content, "text"):
            return content.text
        return ""

    async def complete(
        self,
        message: str,
        vision: VisionContext,
        conversation_history: list,
        working_memory: list[str],
        episodic_memory: list[str],
    ) -> SymbolicResponse:
        user_block = _build_user_block(
            message=message,
            vision=vision,
            working_memory=working_memory,
            episodic_memory=episodic_memory,
        )

        messages = []
        for turn in conversation_history:
            role = turn.role if hasattr(turn, "role") else turn["role"]
            content = turn.content if hasattr(turn, "content") else turn["content"]
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_block})

        response = await self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )

        raw = response.content[0].text if response.content else "{}"
        return _parse_symbolic_response(raw)


def _build_user_block(
    message: str,
    vision: VisionContext,
    working_memory: list[str],
    episodic_memory: list[str],
) -> str:
    lines = [f"User: {message}"]

    lines.append(
        f"Vision: emotion={vision.emotion} confidence={vision.confidence:.2f} "
        f"face={vision.face_detected} hands={vision.hands_detected} "
        f"pitch={vision.pitch:.1f} yaw={vision.yaw:.1f} roll={vision.roll:.1f}"
    )

    if working_memory:
        lines.append("Working memory:")
        for entry in working_memory:
            lines.append(f"  - {entry}")

    if episodic_memory:
        lines.append("Episodic memory:")
        for entry in episodic_memory:
            lines.append(f"  - {entry}")

    return "\n".join(lines)


def _parse_symbolic_response(raw: str) -> SymbolicResponse:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON", raw=raw[:200])
        return SymbolicResponse(
            symbolic_inference="response could not be parsed",
            world_model_update=None,
            natural_language_response=raw,
        )

    wmu_data = data.get("world_model_update")
    wmu = None
    if wmu_data:
        try:
            triple = WorldModelTriple(**wmu_data["triple"])
            wmu = WorldModelUpdate(
                triple=triple,
                confidence=wmu_data.get("confidence", 0.0),
                source=wmu_data.get("source", "inferred"),
            )
        except Exception:
            wmu = None

    return SymbolicResponse(
        symbolic_inference=data.get("symbolic_inference", ""),
        world_model_update=wmu,
        natural_language_response=data.get("natural_language_response", ""),
    )
