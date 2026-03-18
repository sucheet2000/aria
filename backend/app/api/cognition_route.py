import time

from fastapi import APIRouter

from app.cognition.llm import LLMClient
from app.config import settings
from app.models.schemas import CognitionRequest, SymbolicResponse, VisionContext

router = APIRouter()

_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient(api_key=settings.ANTHROPIC_API_KEY)
    return _client


@router.post("/api/cognition")
async def cognition(req: CognitionRequest) -> dict:
    client = get_client()
    start = time.time()

    vision = VisionContext(
        emotion=req.vision_state.emotion,
        confidence=req.vision_state.confidence,
        pitch=req.vision_state.pitch,
        yaw=req.vision_state.yaw,
        roll=req.vision_state.roll,
        face_detected=req.vision_state.face_detected,
        hands_detected=req.vision_state.hands_detected,
    )

    result: SymbolicResponse = await client.complete(
        message=req.message,
        vision=vision,
        conversation_history=req.conversation_history,
        working_memory=req.working_memory,
        episodic_memory=req.episodic_memory,
    )

    processing_ms = int((time.time() - start) * 1000)

    return {
        "symbolic_inference": result.symbolic_inference,
        "world_model_update": result.world_model_update.model_dump() if result.world_model_update else None,
        "natural_language_response": result.natural_language_response,
        "processing_ms": processing_ms,
    }
