from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.cognition_route import router as cognition_router
from app.api.metrics_route import router as metrics_router
from app.api.routes import router
from app.api.tts_route import router as tts_router
from app.api.websocket import ws_router
from app.config import settings

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("ARIA backend starting up", host=settings.HOST, port=settings.PORT)
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

app.include_router(cognition_router)
app.include_router(metrics_router)
app.include_router(router)
app.include_router(tts_router)
app.include_router(ws_router)
