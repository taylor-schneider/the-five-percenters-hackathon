"""Health and version (api.md 5.1-5.2)."""

from __future__ import annotations

import time

from fastapi import APIRouter

from ....core.config import get_settings
from ....models.responses import AgentVersionInfo, HealthResponse, VersionResponse
from ....repositories.seed import demo_team_id
from ...deps import StoreDep

router = APIRouter()
_STARTED = time.time()


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Liveness and dependency check",
)
async def health(store: StoreDep) -> HealthResponse:
    store_ok = "ok" if store.teams else "empty"
    return HealthResponse(
        status="ok",
        checks={"store": store_ok, "cache": "ok"},
        uptime_seconds=int(time.time() - _STARTED),
        demo_team_id=demo_team_id(store) or None,
    )


@router.get(
    "/api/v1/version",
    response_model=VersionResponse,
    tags=["Health"],
    summary="Build metadata, agent modes, and the live scoring weights",
    description=(
        "Weights are exposed so a demo can show the thresholds are tunable rather "
        "than magic."
    ),
)
async def version() -> VersionResponse:
    settings = get_settings()
    info = AgentVersionInfo(mode="heuristic", version=settings.agent_version, model=None)
    weights = settings.weights
    return VersionResponse(
        api_version=settings.api_version,
        build=settings.build,
        git_sha=settings.git_sha,
        agents={
            "gap_finder": info,
            "opportunity_finder": info,
            "trader": info,
        },
        scoring_weights={
            "w1": weights.w1,
            "w2": weights.w2,
            "w3": weights.w3,
            "a1": weights.a1,
            "a2": weights.a2,
            "a3": weights.a3,
            "red_threshold": weights.red_threshold,
            "green_threshold": weights.green_threshold,
        },
    )
