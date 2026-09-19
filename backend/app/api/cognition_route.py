import dataclasses
import time

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_owner
from app.cognition.llm import LLMClient
from app.cognition.memory import MemoryStore
from app.models.schemas import (
    CognitionRequest,
    CognitionResponse,
    MemoryDeleteResult,
    MemoryEntryDeleted,
    MemoryExport,
    SpatialEvent,
)
from app.observability.metrics import MetricsCollector
from app.spatial.anchor_registry import AnchorRegistry
from app.spatial.gesture_anchor_bridge import GestureAnchorBridge

logger = structlog.get_logger()

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

    # The validated frame is passed through whole (R2): a field-by-field copy
    # is how a perception field silently goes missing at a boundary.
    vision = req.vision_state

    # S3: Python is the single source of truth for durable memory. Retrieve
    # for THIS turn's message before generating, so a fact deleted before this
    # turn is never replayed and a fact stored last turn is available now. (The
    # Go edge previously cached the previous turn's list and re-sent it.) A
    # delete that lands DURING this turn cannot un-say the reply, but the
    # store drops this turn's fact-write via expected_generation below.
    deletion_gen = memory.deletion_generation(owner)
    episodic = await memory.query_relevant(req.message, owner=owner, n_results=5)

    result: CognitionResponse = await client.complete(
        message=req.message,
        vision=vision,
        conversation_history=req.conversation_history,
        working_memory=req.working_memory,
        episodic_memory=episodic,
    )

    processing_ms = int((time.time() - start) * 1000)
    MetricsCollector().record_cognition_latency(processing_ms)

    if result.world_model_update and result.used_web_fetch:
        # Memory-poisoning guard: never persist a fact inferred on a turn where
        # web_fetch ran, so a hostile page cannot write into owner memory.
        logger.info("fact-write suppressed on web_fetch turn", owner=owner)
    elif result.world_model_update:
        # The store checks ``expected_generation`` under the owner's mutation
        # lock: if the owner deleted memory while this turn was generating,
        # the model saw pre-delete facts and its triple is dropped atomically
        # with that check (the store logs the suppression).
        wmu = result.world_model_update
        await memory.store_triple(
            subject=wmu.triple.subject,
            predicate=wmu.triple.predicate,
            obj=wmu.triple.object,
            confidence=wmu.confidence,
            source=wmu.source,
            owner=owner,
            expected_generation=deletion_gen,
        )

    spatial_event: SpatialEvent | None = None
    if req.gesture != "none" or req.two_hand_gesture != "NONE":
        spatial_event = await run_in_threadpool(
            bridge.on_gesture_event,
            req.gesture,
            req.two_hand_gesture,
            req.pointing_vector,
            req.session_id,
            owner,
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
    anchors = await run_in_threadpool(registry.list_anchors, owner)
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
    deleted = await run_in_threadpool(registry.delete_anchor, anchor_id, owner)
    if not deleted:
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


def _require_store(memory: MemoryStore, owner: str) -> None:
    if not memory.loaded:
        logger.warning("memory store unavailable", owner=owner)
        raise HTTPException(status_code=503, detail="memory store unavailable")


@router.get("/api/memory/export", response_model=MemoryExport, response_model_exclude_none=True)
async def export_memory(
    offset: int = Query(0, ge=0, le=1_000_000),
    memory: MemoryStore = Depends(get_memory),
    owner: str = Depends(get_current_owner),
) -> dict:
    """Everything ARIA stores for the verified owner, grouped by collection,
    paged by ``offset`` (see ``truncated`` in the response). The owner comes
    only from the edge-set header; no other query/body field is honoured."""
    _require_store(memory, owner)
    return await memory.export(owner=owner, offset=offset)


@router.delete("/api/memory", response_model=MemoryDeleteResult)
async def delete_memory(
    memory: MemoryStore = Depends(get_memory),
    owner: str = Depends(get_current_owner),
) -> dict:
    """Delete every stored memory of the verified owner. Synchronous: a 200
    means the data is gone from the store before this returns."""
    _require_store(memory, owner)
    return {"deleted": await memory.delete_all(owner=owner)}


@router.delete("/api/memory/{entry_id}", response_model=MemoryEntryDeleted)
async def delete_memory_entry(
    entry_id: str,
    memory: MemoryStore = Depends(get_memory),
    owner: str = Depends(get_current_owner),
) -> dict:
    _require_store(memory, owner)
    if not await memory.delete_entry(owner=owner, entry_id=entry_id):
        raise HTTPException(status_code=404, detail="memory entry not found")
    return {"deleted": entry_id}
