import time

from fastapi import APIRouter

from app.cognition.llm import LLMClient
from app.cognition.memory import MemoryStore
from app.config import settings
from app.models.schemas import CognitionRequest, SymbolicResponse, VisionContext

router = APIRouter()

_client: LLMClient | None = None
_memory: MemoryStore | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def get_memory() -> MemoryStore:
    global _memory
    if _memory is None:
        _memory = MemoryStore(persist_dir="./memory")
        _memory.load()
    return _memory


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

    memory = get_memory()

    if result.world_model_update:
        wmu = result.world_model_update
        await memory.store_triple(
            subject=wmu.triple.subject,
            predicate=wmu.triple.predicate,
            obj=wmu.triple.object,
            confidence=wmu.confidence,
            source=wmu.source,
        )

    episodic = await memory.query_relevant(req.message, n_results=5)

    return {
        "symbolic_inference": result.symbolic_inference,
        "world_model_update": result.world_model_update.model_dump() if result.world_model_update else None,
        "natural_language_response": result.natural_language_response,
        "processing_ms": processing_ms,
        "episodic_memory": episodic,
    }


@router.get("/api/memory/profile")
async def get_profile() -> dict:
    memory = get_memory()
    facts = await memory.get_profile_facts(n=20)
    return {"facts": facts, "count": len(facts)}


@router.get("/api/memory/episodic")
async def get_episodic() -> dict:
    memory = get_memory()
    if not memory.loaded:
        return {"facts": [], "count": 0}
    try:
        result = memory._episodic.get(limit=20)
        return {"facts": result["documents"], "count": len(result["documents"])}
    except Exception:
        return {"facts": [], "count": 0}


@router.delete("/api/memory/working")
async def clear_working() -> dict:
    memory = get_memory()
    await memory.clear_working()
    return {"status": "cleared"}
