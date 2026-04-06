from fastapi import APIRouter

from app.observability.metrics import MetricsCollector

router = APIRouter()


@router.get("/metrics")
def metrics() -> dict:
    return MetricsCollector().snapshot()
