"""Glue between the HTTP endpoints and the agent seam.

The split this module enforces:

    agent  -> judgement   (what is a problem, which trade, why)
    API    -> arithmetic  (salaries, deltas, benchmarks, ranking, caching)

So an agent's output is never returned raw. A Gap Finder verdict gets the
measured benchmark numbers attached; an Opportunity Finder proposal gets priced
through the trader, assigned an id, and dropped if it turns out to be illegal.
An agent cannot put a number it invented into a response.
"""

from __future__ import annotations

import statistics
from datetime import timedelta
from uuid import uuid4

from ..agents.base import (
    GapFinderContext,
    GapFinderVerdict,
    OpportunityFinderContext,
    ProposedOpportunity,
    get_agents,
)
from ..core.config import get_settings
from ..models.domain import Opportunity, TradeLegRequest
from ..models.enums import (
    AgentName,
    InsightType,
    Position,
    PositionGroup,
    Severity,
)
from ..models.requests import GapFinderRequest, OpportunityFinderRequest
from ..models.responses import (
    CoverageWarning,
    FlaggedPlayer,
    FlaggedPosition,
    FlaggedPositionMetrics,
    GapFinderResponse,
    OpportunityFinderResponse,
)
from ..repositories.store import InsightRecord, RosterEntryRecord, Store, utcnow
from . import scoring, team_service, trader_service
from .agent_runtime import agent_run
from .opportunity_cache import get_opportunity_cache, new_opportunity_id
from .scoring import LeagueContext


# --------------------------------------------------------------------------
# Gap Finder
# --------------------------------------------------------------------------


def run_gap_finder(store: Store, request: GapFinderRequest) -> GapFinderResponse:
    team = team_service.require_team(store, request.team_id)
    entries = store.current_roster(team.id)
    ctx = LeagueContext.build(store.all_current_entries())
    minimums = team_service.resolve_minimums(request.constraints.min_position_group_counts)

    bundle = get_agents()
    payload = {
        "team_id": str(team.id),
        "roster_version": team.roster_version,
        "constraints": request.constraints.model_dump(mode="json"),
        "agent": bundle.describe(),
    }

    with agent_run(AgentName.GAP_FINDER, payload, bundle.mode, bundle.model) as meta:
        verdict = bundle.gap_finder.analyze(
            GapFinderContext(
                store=store,
                team_id=team.id,
                roster_version=team.roster_version,
                constraints=request.constraints,
            )
        )

    flagged_positions = _attach_position_metrics(verdict, entries, ctx)
    flagged_players = _attach_player_metrics(store, verdict, entries)
    # Coverage is arithmetic, not judgement: a count either meets the minimum or
    # it does not. The API owns this regardless of what the agent said.
    coverage = _coverage_warnings(entries, minimums)

    if request.persist_insights:
        _persist(store, team.id, flagged_positions, flagged_players, coverage)

    return GapFinderResponse(
        team_id=team.id,
        flagged_positions=flagged_positions,
        flagged_players=flagged_players,
        coverage_warnings=coverage,
        roster_version=team.roster_version,
        agent_meta=meta[0],
        generated_at=utcnow(),
    )


def _attach_position_metrics(
    verdict: GapFinderVerdict, entries: list[RosterEntryRecord], ctx: LeagueContext
) -> list[FlaggedPosition]:
    by_position: dict[Position, list[RosterEntryRecord]] = {}
    for entry in entries:
        by_position.setdefault(entry.position, []).append(entry)

    out: list[FlaggedPosition] = []
    for judgement in verdict.positions:
        occupants = by_position.get(judgement.position, [])
        out.append(
            FlaggedPosition(
                position=judgement.position,
                position_group=team_service.group_of(judgement.position),
                severity=judgement.severity,
                problem_score=judgement.problem_score,
                health_status=judgement.health_status,
                reasons=judgement.reasons,
                metrics=FlaggedPositionMetrics(
                    team_avg_cost=(
                        int(round(statistics.fmean([e.cost for e in occupants])))
                        if occupants
                        else 0
                    ),
                    team_avg_value=(
                        round(statistics.fmean([e.value_score for e in occupants]), 1)
                        if occupants
                        else 0.0
                    ),
                    league_avg_cost=ctx.league_avg_cost(judgement.position),
                    league_avg_value=ctx.league_avg_value(judgement.position),
                ),
            )
        )
    return sorted(out, key=lambda f: f.problem_score, reverse=True)


def _attach_player_metrics(
    store: Store, verdict: GapFinderVerdict, entries: list[RosterEntryRecord]
) -> list[FlaggedPlayer]:
    positions = {e.player_id: e.position for e in entries}
    out: list[FlaggedPlayer] = []
    for judgement in verdict.players:
        if judgement.player_id not in positions:
            # The agent flagged someone who is not on the current roster; drop it
            # rather than surface a player the UI cannot render.
            continue
        out.append(
            FlaggedPlayer(
                player=team_service.player_ref(
                    store, judgement.player_id, positions[judgement.player_id]
                ),
                severity=judgement.severity,
                problem_score=judgement.problem_score,
                health_status=judgement.health_status,
                reasons=judgement.reasons,
            )
        )
    return sorted(out, key=lambda f: f.problem_score, reverse=True)


def _coverage_warnings(
    entries: list[RosterEntryRecord], minimums: dict[PositionGroup, int]
) -> list[CoverageWarning]:
    counts = team_service.group_counts(entries)
    warnings: list[CoverageWarning] = []
    for group, required in minimums.items():
        actual = counts.get(group, 0)
        if actual < required:
            warnings.append(
                CoverageWarning(
                    position_group=group,
                    required=required,
                    actual=actual,
                    severity=Severity.HIGH if required - actual > 1 else Severity.MEDIUM,
                )
            )
    return warnings


def apply_verdict_to_pitch(pitch, flagged: list[FlaggedPosition]):
    """Overlay Gap Finder judgements onto the measured pitch map."""
    judgements = {f.position: f for f in flagged}
    for slot in pitch.slots:
        found = judgements.get(slot.position)
        if found is not None:
            slot.health_status = found.health_status
            slot.problem_score = found.problem_score
            slot.headline = found.reasons[0] if found.reasons else None
    return pitch


def apply_verdict_to_roster(rows, flagged: list[FlaggedPlayer]):
    """Overlay per-player judgements onto the measured roster rows."""
    judgements = {f.player.player_id: f for f in flagged}
    for row in rows:
        found = judgements.get(row.player.player_id)
        if found is not None:
            row.health_status = found.health_status
    return rows


# --------------------------------------------------------------------------
# Opportunity Finder
# --------------------------------------------------------------------------


def run_opportunity_finder(
    store: Store, request: OpportunityFinderRequest
) -> OpportunityFinderResponse:
    team = team_service.require_team(store, request.team_id)
    trader_service._check_version(team, request.roster_version)

    bundle = get_agents()
    payload = {
        "team_id": str(team.id),
        "roster_version": team.roster_version,
        "focus": request.focus.model_dump(mode="json"),
        "constraints": request.constraints.model_dump(mode="json"),
        "agent": bundle.describe(),
    }

    with agent_run(
        AgentName.OPPORTUNITY_FINDER, payload, bundle.mode, bundle.model
    ) as meta:
        proposals = bundle.opportunity_finder.find(
            OpportunityFinderContext(
                store=store,
                team_id=team.id,
                roster_version=team.roster_version,
                focus=request.focus,
                constraints=request.constraints,
            )
        )
        opportunities = _price_and_rank(store, team, proposals, request)

    get_opportunity_cache().put_many(opportunities, team.id, team.roster_version)

    return OpportunityFinderResponse(
        team_id=team.id,
        focus=request.focus,
        opportunities=opportunities,
        candidates_evaluated=len(proposals),
        roster_version=team.roster_version,
        agent_meta=meta[0],
        generated_at=utcnow(),
    )


def _price_and_rank(
    store: Store,
    team,
    proposals: list[ProposedOpportunity],
    request: OpportunityFinderRequest,
) -> list[Opportunity]:
    """Price every proposal, drop the illegal ones, rank what survives.

    The agent chose these trades and wrote the justifications; every number
    attached here is computed from the roster and the market.
    """
    settings = get_settings()
    constraints = request.constraints
    minimums = team_service.resolve_minimums(constraints.min_position_group_counts)

    priced: list[tuple[ProposedOpportunity, list, object]] = []
    for proposal in proposals:
        try:
            legs = [TradeLegRequest.model_validate(leg) for leg in proposal.legs]
            trader_service.validate_leg_shape(legs)
            resolved = trader_service.resolve_legs(store, team, legs)
            impact = trader_service.compute_impact(store, team, resolved, minimums)
        except Exception:
            # An unpriceable or malformed proposal never reaches the UI.
            continue

        if not impact.valid:
            continue
        if (
            constraints.max_cost_increase is not None
            and impact.projected_cost_delta > constraints.max_cost_increase
        ):
            continue
        if (
            constraints.min_value_gain is not None
            and impact.projected_value_delta < constraints.min_value_gain
        ):
            continue
        priced.append((proposal, [leg.model for leg in resolved], impact))

    if not priced:
        return []

    scores = scoring.opportunity_scores(
        value_gains=[impact.projected_value_delta for _, _, impact in priced],
        cost_savings=[-impact.projected_cost_delta for _, _, impact in priced],
        risks=[1.0 - p.confidence for p, _, _ in priced],
    )

    ttl = timedelta(seconds=settings.opportunity_ttl_seconds)
    expires_at = utcnow() + ttl

    ranked = sorted(
        zip(priced, scores, strict=True),
        key=lambda pair: (pair[1], pair[0][0].rank_hint or 0.0),
        reverse=True,
    )

    out: list[Opportunity] = []
    for (proposal, leg_models, impact), score in ranked[: constraints.max_results]:
        out.append(
            Opportunity(
                opportunity_id=new_opportunity_id(),
                type=proposal.type,
                target_position=proposal.target_position,
                opportunity_score=score,
                confidence=max(0.0, min(1.0, proposal.confidence)),
                legs=leg_models,
                impact=impact,
                risks=proposal.risks,
                reasoning_summary=proposal.reasoning_summary,
                reasoning_steps=proposal.reasoning_steps,
                expires_at=expires_at,
            )
        )
    return out


# --------------------------------------------------------------------------


def _persist(
    store: Store,
    team_id,
    positions: list[FlaggedPosition],
    players: list[FlaggedPlayer],
    warnings: list[CoverageWarning],
) -> None:
    for item in positions:
        store.add_insight(
            InsightRecord(
                id=uuid4(),
                team_id=team_id,
                agent_name=AgentName.GAP_FINDER.value,
                insight_type=InsightType.PROBLEM_FLAG.value,
                severity=item.severity.value,
                position=item.position,
                player_id=None,
                summary=f"{item.position.value}: " + "; ".join(item.reasons),
                details={"problem_score": item.problem_score},
            )
        )
    for item in players:
        store.add_insight(
            InsightRecord(
                id=uuid4(),
                team_id=team_id,
                agent_name=AgentName.GAP_FINDER.value,
                insight_type=InsightType.PROBLEM_FLAG.value,
                severity=item.severity.value,
                position=item.player.position,
                player_id=item.player.player_id,
                summary=f"{item.player.name}: " + "; ".join(item.reasons),
                details={"problem_score": item.problem_score},
            )
        )
    for warning in warnings:
        store.add_insight(
            InsightRecord(
                id=uuid4(),
                team_id=team_id,
                agent_name=AgentName.GAP_FINDER.value,
                insight_type=InsightType.RISK_NOTE.value,
                severity=warning.severity.value,
                position=None,
                player_id=None,
                summary=(
                    f"{warning.position_group.value} coverage is {warning.actual} "
                    f"against a minimum of {warning.required}"
                ),
                details={"required": warning.required, "actual": warning.actual},
            )
        )
