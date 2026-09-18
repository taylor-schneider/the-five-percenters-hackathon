"""Gap Finder: flags problem positions and players against league benchmarks.

Phase 1 is deterministic heuristics driven by scoring.py. Phase 2 swaps in an
LLM behind this same function signature and response schema (D11) -- the
endpoint and the frontend do not change.
"""

from __future__ import annotations

import statistics
from uuid import uuid4

from ..core.config import get_settings
from ..models.domain import AgentInsight
from ..models.enums import (
    AgentName,
    InsightType,
    Position,
    PositionGroup,
    Severity,
    group_of,
)
from ..models.requests import GapFinderRequest
from ..models.responses import (
    CoverageWarning,
    FlaggedPlayer,
    FlaggedPosition,
    FlaggedPositionMetrics,
    GapFinderResponse,
)
from ..repositories.store import InsightRecord, RosterEntryRecord, Store, utcnow
from . import scoring, team_service
from .agent_runtime import agent_run
from .scoring import LeagueContext


def resolve_minimums(
    requested: dict[PositionGroup, int] | None,
) -> dict[PositionGroup, int]:
    defaults = dict(get_settings().default_min_position_group_counts)
    if requested:
        defaults.update(requested)
    return defaults


def analyze(store: Store, request: GapFinderRequest) -> GapFinderResponse:
    team = team_service.require_team(store, request.team_id)
    entries = store.current_roster(team.id)
    ctx = LeagueContext.build(store.all_current_entries())
    minimums = resolve_minimums(request.constraints.min_position_group_counts)

    payload = {
        "team_id": str(team.id),
        "roster_version": team.roster_version,
        "constraints": request.constraints.model_dump(mode="json"),
        "roster": sorted(f"{e.player_id}:{e.cost}:{e.value_score}" for e in entries),
    }

    with agent_run(AgentName.GAP_FINDER, payload) as meta:
        flagged_positions = _flag_positions(entries, ctx, minimums)
        flagged_players = _flag_players(store, entries, ctx)
        coverage_warnings = _coverage_warnings(entries, minimums)

    if request.persist_insights:
        _persist(store, team.id, flagged_positions, flagged_players, coverage_warnings)

    return GapFinderResponse(
        team_id=team.id,
        flagged_positions=flagged_positions,
        flagged_players=flagged_players,
        coverage_warnings=coverage_warnings,
        roster_version=team.roster_version,
        agent_meta=meta[0],
        generated_at=utcnow(),
    )


# --------------------------------------------------------------------------


def _flag_positions(
    entries: list[RosterEntryRecord],
    ctx: LeagueContext,
    minimums: dict[PositionGroup, int],
) -> list[FlaggedPosition]:
    counts = team_service.group_counts(entries)
    by_position: dict[Position, list[RosterEntryRecord]] = {}
    for entry in entries:
        by_position.setdefault(entry.position, []).append(entry)

    flagged: list[FlaggedPosition] = []
    for position in Position:
        occupants = by_position.get(position, [])
        penalty = scoring.coverage_penalty_for(position, len(occupants), counts, minimums)

        if occupants:
            team_avg_cost = int(round(statistics.fmean([e.cost for e in occupants])))
            team_avg_value = round(statistics.fmean([e.value_score for e in occupants]), 1)
            value_pct = statistics.fmean(
                [ctx.value_percentile(position, e.value_score) for e in occupants]
            )
            efficiency = statistics.fmean(
                [ctx.cost_efficiency(e.value_score, e.cost) for e in occupants]
            )
        else:
            # An unfilled slot is a gap even though there is nobody to score.
            if penalty == 0.0:
                continue
            team_avg_cost, team_avg_value, value_pct, efficiency = 0, 0.0, 0.0, 0.0

        score = scoring.problem_score(value_pct, efficiency, penalty)
        status = scoring.health_status(score)
        if status.value != "red":
            continue

        league_cost = ctx.league_avg_cost(position)
        league_value = ctx.league_avg_value(position)
        flagged.append(
            FlaggedPosition(
                position=position,
                position_group=group_of(position),
                severity=scoring.severity_from_score(score),
                problem_score=score,
                health_status=status,
                reasons=_position_reasons(
                    occupants, team_avg_cost, team_avg_value, league_cost, league_value, penalty
                ),
                metrics=FlaggedPositionMetrics(
                    team_avg_cost=team_avg_cost,
                    team_avg_value=team_avg_value,
                    league_avg_cost=league_cost,
                    league_avg_value=league_value,
                ),
            )
        )
    return sorted(flagged, key=lambda f: f.problem_score, reverse=True)


def _position_reasons(
    occupants: list[RosterEntryRecord],
    team_avg_cost: int,
    team_avg_value: float,
    league_cost: int,
    league_value: float,
    penalty: float,
) -> list[str]:
    reasons: list[str] = []
    if not occupants:
        reasons.append("no player on the roster for this position")
        return reasons
    value_gap = scoring.pct_vs_league(team_avg_value, league_value)
    cost_gap = scoring.pct_vs_league(team_avg_cost, league_cost)
    if value_gap < -2:
        reasons.append(f"value {abs(value_gap):.1f}% below league average")
    if cost_gap > 2:
        reasons.append(f"cost {cost_gap:.1f}% above league average")
    if penalty > 0:
        reasons.append("position group is below its squad minimum")
    if not reasons:
        reasons.append("poor value-to-cost efficiency relative to the league")
    return reasons


def _flag_players(
    store: Store, entries: list[RosterEntryRecord], ctx: LeagueContext
) -> list[FlaggedPlayer]:
    flagged: list[FlaggedPlayer] = []
    for entry in entries:
        efficiency = ctx.cost_efficiency(entry.value_score, entry.cost)
        value_pct = ctx.value_percentile(entry.position, entry.value_score)
        score = scoring.problem_score(value_pct, efficiency)
        status = scoring.health_status(score)
        if status.value != "red":
            continue

        reasons: list[str] = []
        cost_gap = scoring.pct_vs_league(entry.cost, ctx.league_avg_cost(entry.position))
        value_gap = scoring.pct_vs_league(entry.value_score, ctx.league_avg_value(entry.position))
        if cost_gap > 5:
            reasons.append(f"paid {cost_gap:.1f}% above the {entry.position.value} league average")
        if value_gap < -5:
            reasons.append(f"value {abs(value_gap):.1f}% below the {entry.position.value} league average")
        reasons.append(f"cost efficiency {efficiency:.2f}")

        flagged.append(
            FlaggedPlayer(
                player=team_service.player_ref(store, entry.player_id, entry.position),
                severity=scoring.severity_from_score(score),
                problem_score=score,
                health_status=status,
                reasons=reasons,
            )
        )
    return sorted(flagged, key=lambda f: f.problem_score, reverse=True)


def _coverage_warnings(
    entries: list[RosterEntryRecord], minimums: dict[PositionGroup, int]
) -> list[CoverageWarning]:
    counts = team_service.group_counts(entries)
    warnings: list[CoverageWarning] = []
    for group, required in minimums.items():
        actual = counts.get(group, 0)
        if actual < required:
            shortfall = required - actual
            warnings.append(
                CoverageWarning(
                    position_group=group,
                    required=required,
                    actual=actual,
                    severity=Severity.HIGH if shortfall > 1 else Severity.MEDIUM,
                )
            )
    return warnings


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


def to_insight_model(record: InsightRecord) -> AgentInsight:
    return AgentInsight(
        insight_id=record.id,
        team_id=record.team_id,
        agent_name=AgentName(record.agent_name),
        insight_type=InsightType(record.insight_type),
        severity=Severity(record.severity),
        position=record.position,
        player_id=record.player_id,
        summary=record.summary,
        details=record.details,
        created_at=record.created_at,
    )
