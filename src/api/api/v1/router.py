"""v1 router assembly."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...api.deps import require_api_key
from .endpoints import agents, market, teams

api_v1_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])

api_v1_router.include_router(teams.router)
api_v1_router.include_router(market.router)
api_v1_router.include_router(agents.router)
