"""Agent endpoints: /api/v1/agents/{agent}/{action} (api.md 5.8-5.11).

Only endpoints that actually run an agent live under /agents/. Pure data reads
sit outside it.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from ....core.errors import error_responses
from ....models.requests import (
    ExecuteRequest,
    GapFinderRequest,
    OpportunityFinderRequest,
    SimulateRequest,
)
from ....models.responses import (
    ExecuteResponse,
    GapFinderResponse,
    OpportunityFinderResponse,
    SimulateResponse,
)
from ....services import orchestration, trader_service
from ...deps import StoreDep, UserDep

router = APIRouter(prefix="/agents")


@router.post(
    "/gap-finder/analyze",
    response_model=GapFinderResponse,
    tags=["Gap Finder"],
    summary="Flag problem positions and players against league benchmarks",
    description=(
        "Read-only, but POST because the constraint block is a structured body and "
        "this may become an LLM call in Phase 2.\n\n"
        "`coverage_warnings` exists because a squad can be under-filled at a position "
        "without any individual player being bad -- nothing else in the response can "
        "express that."
    ),
    responses=error_responses(404, 422),
)
async def gap_finder_analyze(
    request: GapFinderRequest, store: StoreDep
) -> GapFinderResponse:
    return orchestration.run_gap_finder(store, request)


@router.post(
    "/opportunity-finder/find",
    response_model=OpportunityFinderResponse,
    tags=["Opportunity Finder"],
    summary="Generate ranked trade options for a focus area",
    description=(
        "Results are cached server-side by `opportunity_id` so `execute` can reference "
        "one by id. Sorted by `opportunity_score` descending.\n\n"
        "An empty `opportunities` array is a valid 200 -- `candidates_evaluated` lets the "
        "UI say whether nothing was considered or everything was filtered out."
    ),
    responses=error_responses(404, 409, 422),
)
async def opportunity_finder_find(
    request: OpportunityFinderRequest, store: StoreDep
) -> OpportunityFinderResponse:
    return orchestration.run_opportunity_finder(store, request)


@router.post(
    "/trader/simulate",
    response_model=SimulateResponse,
    tags=["Trader"],
    summary="What-if a trade. Writes nothing.",
    description=(
        "Accepts either a cached `opportunity_id` or explicit `legs`, so the user can "
        "hand-build a trade in Stage 2.\n\n"
        "**Returns 200 even when `impact.valid` is false** -- the UI needs the violation "
        "list to explain why Execute is disabled. Only structural problems (unknown team, "
        "expired opportunity, stale version) produce a 4xx."
    ),
    responses=error_responses(400, 404, 409, 410, 422),
)
async def trader_simulate(request: SimulateRequest, store: StoreDep) -> SimulateResponse:
    return trader_service.simulate(store, request)


@router.post(
    "/trader/execute",
    response_model=ExecuteResponse,
    tags=["Trader"],
    summary="Commit a trade. The only mutating endpoint.",
    description=(
        "Gated on explicit human approval: `user_confirmation` is typed `Literal[True]`, "
        "so an unconfirmed execute is structurally impossible to express.\n\n"
        "Requires `roster_version` (optimistic lock) and `idempotency_key`. Replaying a "
        "key with an identical body returns the original response and sets "
        "`Idempotency-Replayed: true`; a different body is a 409."
    ),
    responses=error_responses(400, 404, 409, 410, 422, 500),
    status_code=status.HTTP_200_OK,
)
async def trader_execute(
    request: ExecuteRequest,
    store: StoreDep,
    user: UserDep,
    response: Response,
) -> ExecuteResponse:
    replayed = store.get_idempotency(request.idempotency_key) is not None
    result = trader_service.execute(store, request, initiated_by=user)
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return result
