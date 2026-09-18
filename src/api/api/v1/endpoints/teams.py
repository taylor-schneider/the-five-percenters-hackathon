"""Team data endpoints: list, dashboard, roster (api.md 5.3-5.5)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from ....core.errors import error_responses
from ....models.responses import (
    DashboardResponse,
    Page,
    RosterResponse,
    TeamsPage,
)
from ....repositories.store import utcnow
from ....services import orchestration, team_service
from ....services.scoring import LeagueContext
from ...deps import StoreDep

router = APIRouter()


@router.get(
    "/teams",
    response_model=TeamsPage,
    tags=["Teams"],
    summary="List selectable teams",
    description="Powers the team picker. Not paginated -- the seeded league is small.",
)
async def list_teams(store: StoreDep) -> TeamsPage:
    teams = [team_service.team_summary(t) for t in store.list_teams()]
    return Page(items=teams, next_cursor=None, total=len(teams))


@router.get(
    "/teams/{team_id}/dashboard",
    response_model=DashboardResponse,
    tags=["Teams"],
    summary="Everything Stage 1 renders, in one call",
    description=(
        "KPI cards, roster table with league benchmark columns, and the pitch map "
        "traffic lights. Single call by design so the dashboard never shows a "
        "half-loaded state."
    ),
    responses=error_responses(404, 422),
)
async def get_dashboard(
    team_id: UUID,
    store: StoreDep,
    include_gaps: bool = Query(
        default=True,
        description="Runs the Gap Finder agent inline and overlays its judgements "
        "onto the pitch map and roster. Set false for a fast, agent-free render -- "
        "health_status and problem_score then come back null.",
    ),
) -> DashboardResponse:
    team = team_service.require_team(store, team_id)
    entries = store.current_roster(team_id)
    ctx = LeagueContext.build(store.all_current_entries())

    # Measured facts first. These are true regardless of any agent.
    roster = team_service.roster_rows(store, entries, ctx, include_benchmarks=True)
    pitch = team_service.build_pitch_map(entries)

    flagged = []
    agent_meta = None
    if include_gaps:
        from ....models.requests import GapFinderRequest

        gaps = orchestration.run_gap_finder(
            store, GapFinderRequest(team_id=team_id, persist_insights=False)
        )
        flagged = gaps.flagged_positions
        agent_meta = gaps.agent_meta
        # Traffic lights are the agent's judgement, overlaid onto the facts.
        orchestration.apply_verdict_to_pitch(pitch, flagged)
        orchestration.apply_verdict_to_roster(roster, gaps.flagged_players)

    return DashboardResponse(
        team=team_service.team_summary(team),
        metrics=team_service.metrics_from_entries(team, entries),
        roster=roster,
        pitch=pitch,
        flagged_positions=flagged,
        roster_version=team.roster_version,
        agent_meta=agent_meta,
        generated_at=utcnow(),
    )


@router.get(
    "/teams/{team_id}/roster",
    response_model=RosterResponse,
    tags=["Teams"],
    summary="Raw roster without benchmark joins or agent analysis",
    description="Cheap, and useful for debugging when the dashboard looks wrong.",
    responses=error_responses(404, 422),
)
async def get_roster(team_id: UUID, store: StoreDep) -> RosterResponse:
    team = team_service.require_team(store, team_id)
    entries = store.current_roster(team_id)
    return RosterResponse(
        team_id=team_id,
        roster_version=team.roster_version,
        items=team_service.roster_rows(store, entries, ctx=None, include_benchmarks=False),
    )
