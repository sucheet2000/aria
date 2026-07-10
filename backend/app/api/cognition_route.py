import dataclasses
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_current_owner
from app.cognition.llm import LLMClient
from app.cognition.memory import MemoryStore
from app.models.schemas import (
    CognitionRequest,
    CognitionResponse,
    PerceptionFrame,
    SpatialEvent,
)
from app.observability.metrics import MetricsCollector
from app.spatial.anchor_registry import AnchorRegistry
from app.spatial.gesture_anchor_bridge import GestureAnchorBridge

router = APIRouter()


# ── dependency providers (services are created once in the app lifespan) ──────

def get_client(request: Request) -> LLMClient:
    return request.app.state.llm


def get_memory(request: Request) -> MemoryStore:
    return request.app.state.memory


def get_bridge(request: Request) -> GestureAnchorBridge:
    return request.app.state.bridge


def get_registry(request: Request) -> AnchorRegistry:
    return request.app.state.registry


@router.post("/api/cognition")
async def cognition(
    req: CognitionRequest,
    client: LLMClient = Depends(get_client),
    memory: MemoryStore = Depends(get_memory),
    bridge: GestureAnchorBridge = Depends(get_bridge),
    owner: str = Depends(get_current_owner),
) -> dict:
    start = time.time()

    vision = PerceptionFrame(
        emotion=req.vision_state.emotion,
        confidence=req.vision_state.confidence,
        pitch=req.vision_state.pitch,
        yaw=req.vision_state.yaw,
        roll=req.vision_state.roll,
        face_detected=req.vision_state.face_detected,
        hands_detected=req.vision_state.hands_detected,
    )

    result: CognitionResponse = await client.complete(
        message=req.message,
        vision=vision,
        conversation_history=req.conversation_history,
        working_memory=req.working_memory,
        episodic_memory=req.episodic_memory,
    )

    processing_ms = int((time.time() - start) * 1000)
    MetricsCollector().record_cognition_latency(processing_ms)

    if result.world_model_update:
        wmu = result.world_model_update
        await memory.store_triple(
            subject=wmu.triple.subject,
            predicate=wmu.triple.predicate,
            obj=wmu.triple.object,
            confidence=wmu.confidence,
            source=wmu.source,
            owner=owner,
        )

    episodic = await memory.query_relevant(req.message, owner=owner, n_results=5)

    spatial_event: SpatialEvent | None = None
    if req.hand_gesture != "none" or req.two_hand_gesture != "NONE":
        spatial_event = bridge.on_gesture_event(
            gesture=req.hand_gesture,
            two_hand_gesture=req.two_hand_gesture,
            pointing_vector=req.pointing_vector,
            session_id=req.session_id,
            owner=owner,
        )
        if spatial_event is not None:
            MetricsCollector().record_anchor_created()

    return {
        "symbolic_inference": result.symbolic_inference,
        "world_model_update": result.world_model_update.model_dump() if result.world_model_update else None,
        "natural_language_response": result.natural_language_response,
        "processing_ms": processing_ms,
        "episodic_memory": episodic,
        "spatial_event": dataclasses.asdict(spatial_event) if spatial_event is not None else None,
    }


@router.get("/api/anchors")
async def list_anchors(
    registry: AnchorRegistry = Depends(get_registry),
    owner: str = Depends(get_current_owner),
) -> dict:
    anchors = registry.list_anchors(owner=owner)
    return {
        "anchors": [
            {
                "anchor_id": a.anchor_id,
                "label": a.label,
                "x": a.x,
                "y": a.y,
                "z": a.z,
                "created_at_us": a.created_at_us,
            }
            for a in anchors
        ]
    }


@router.delete("/api/anchors/{anchor_id}")
async def delete_anchor(
    anchor_id: str,
    registry: AnchorRegistry = Depends(get_registry),
    owner: str = Depends(get_current_owner),
) -> dict:
    if not registry.delete_anchor(anchor_id, owner=owner):
        raise HTTPException(status_code=404, detail="anchor not found")
    return {"deleted": anchor_id}


@router.get("/api/memory/profile")
async def get_profile(
    memory: MemoryStore = Depends(get_memory),
    owner: str = Depends(get_current_owner),
) -> dict:
    facts = await memory.get_profile_facts(owner=owner, n=20)
    return {"facts": facts, "count": len(facts)}


@router.get("/api/memory/episodic")
async def get_episodic(
    memory: MemoryStore = Depends(get_memory),
    owner: str = Depends(get_current_owner),
) -> dict:
    if not memory.loaded:
        return {"facts": [], "count": 0}
    try:
        result = memory._episodic.get(where={"owner": owner}, limit=20)  # type: ignore[attr-defined]
        return {"facts": result["documents"], "count": len(result["documents"])}
    except Exception:
        return {"facts": [], "count": 0}


@router.delete("/api/memory/working")
async def clear_working(
    memory: MemoryStore = Depends(get_memory),
    owner: str = Depends(get_current_owner),
) -> dict:
    await memory.clear_working(owner=owner)
    return {"status": "cleared"}
