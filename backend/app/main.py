from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

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
from app.config import settings
from app.spatial.anchor_registry import AnchorRegistry
from app.spatial.gesture_anchor_bridge import GestureAnchorBridge

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("ARIA backend starting up", host=settings.HOST, port=settings.PORT)
    # Construct the expensive services once; handlers receive them via Depends.
    app.state.llm = LLMClient(api_key=settings.ANTHROPIC_API_KEY)
    app.state.memory = MemoryStore(persist_dir="./memory")
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
