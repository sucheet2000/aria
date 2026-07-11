from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.cognition_route import router as cognition_router
from app.api.deps import require_internal_auth
from app.api.metrics_route import router as metrics_router
from app.api.routes import router
from app.api.tts_route import router as tts_router
from app.api.websocket import ws_router
from app.cognition.llm import LLMClient
from app.cognition.memory import MemoryStore
from app.config import Settings, settings
from app.spatial.anchor_registry import AnchorRegistry
from app.spatial.gesture_anchor_bridge import GestureAnchorBridge

logger = structlog.get_logger()


def validate_anthropic_key(settings: Settings) -> None:
    """Guard against a silently-missing Anthropic key.

    An empty key builds an ``AsyncAnthropic`` client fine and only fails at
    call time, so misconfiguration hides until the first request. When
    ``REQUIRE_ANTHROPIC_KEY`` is set this is a fatal startup error; otherwise it
    is a loud warning so key-less local dev still runs.
    """
    if settings.ANTHROPIC_API_KEY:
        return
    if settings.REQUIRE_ANTHROPIC_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is empty but REQUIRE_ANTHROPIC_KEY is set; "
            "refusing to start"
        )
    logger.warning(
        "ANTHROPIC_API_KEY is empty; cognition will fail at call time. "
        "Set it in backend/.env (continuing for key-less local dev).",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    validate_anthropic_key(settings)
    logger.info("ARIA backend starting up", host=settings.HOST, port=settings.PORT)
    # Ensure the durable-data tree exists before the stores initialize. In the
    # cloud DATA_DIR points at a mounted volume so memory + anchors survive
    # redeploys; locally it defaults to backend/ (unchanged layout).
    Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
    # Construct the expensive services once; handlers receive them via Depends.
    app.state.llm = LLMClient(api_key=settings.ANTHROPIC_API_KEY)
    app.state.memory = MemoryStore()
    app.state.memory.load()
    app.state.registry = AnchorRegistry()
    app.state.bridge = GestureAnchorBridge(app.state.registry)
    yield
    logger.info("ARIA backend shutting down")


app = FastAPI(title="ARIA Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# The Go server is the only legitimate caller of the paid/data API routes, so
# they sit behind the internal trust boundary. /health and /metrics stay open
# for liveness probes and scraping.
app.include_router(cognition_router, dependencies=[Depends(require_internal_auth)])
app.include_router(metrics_router)
app.include_router(router)
app.include_router(tts_router, dependencies=[Depends(require_internal_auth)])
app.include_router(ws_router)
