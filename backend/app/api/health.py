"""Health and metrics API router."""

import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.adapters.observability import get_observability_adapter
from app.core.cache import app_cache
from app.core.config import settings

router = APIRouter(tags=["Ops"])
START_TIME = time.time()


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str


class MetricsResponse(BaseModel):
    uptime_seconds: float
    status: str
    cache_stats: dict[str, Any]
    traces_recorded: int


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint confirming application is up and healthy."""
    return HealthResponse(
        status="ok",
        version="0.1.0",
        environment=settings.ENVIRONMENT,
    )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics() -> MetricsResponse:
    """Metrics endpoint reporting uptime, operational status, and cache statistics."""
    obs = get_observability_adapter()
    return MetricsResponse(
        uptime_seconds=round(time.time() - START_TIME, 2),
        status="healthy",
        cache_stats=app_cache.stats,
        traces_recorded=len(obs.get_recent_traces()),
    )


@router.get("/traces")
async def get_traces() -> dict[str, Any]:
    """Returns recent observability traces and LLM spans."""
    obs = get_observability_adapter()
    return {
        "traces": obs.get_recent_traces(),
        "total": len(obs.get_recent_traces()),
    }
