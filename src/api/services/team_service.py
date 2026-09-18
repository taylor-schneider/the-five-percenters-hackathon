"""Roster, metrics, benchmark and pitch-map assembly.

Shared by the dashboard endpoint and both finder agents so they can never
disagree about what a team's numbers are.
"""

from __future__ import annotations

import statistics
from uuid import UUID

from ..core.errors import ErrorCode, not_found
from ..models.domain import (
    MarketListing,
    PitchMap,
    PitchSlot,
    PlayerRef,
    PositionBenchmark,
    RosterRow,
    TeamMetrics,
    TeamSummary,
)
from ..models.enums import (
    FORMATIONS,
    PITCH_COORDINATES,
    Position,
    PositionGroup,
    group_of,
)
from ..repositories.store import (
    MarketListingRecord,
    RosterEntryRecord,
    Store,
    TeamRecord,
)
from . import scoring
from .scoring import LeagueContext


def require_team(store: Store, team_id: UUID) -> TeamRecord:
    team = store.get_team(team_id)
    if team is None:
        raise not_found(ErrorCode.TEAM_NOT_FOUND, f"Team {team_id} not found", team_id=str(team_id))
    return team


def team_summary(team: TeamRecord) -> TeamSummary:
    return TeamSummary(
        team_id=team.id,
        name=team.name,
        budget_cap=team.budget_cap,
        roster_version=team.roster_version,
    )


def player_ref(store: Store, player_id: UUID, position: Position | None = None) -> PlayerRef:
    player = store.get_player(player_id)
    if player is None:
        raise not_found(
            ErrorCode.PLAYER_NOT_FOUND, f"Player {player_id} not found", player_id=str(player_id)
        )
    pos = position or player.position
    return PlayerRef(
        player_id=player.id,
        name=player.name,
        position=pos,
        position_group=group_of(pos),
        age=player.age,
    )


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def metrics_from_entries(team: TeamRecord, entries: list[RosterEntryRecord]) -> TeamMetrics:
    total_cost = sum(e.cost for e in entries)
    avg_value = round(statistics.fmean([e.value_score for e in entries]), 1) if entries else 0.0
    return TeamMetrics(
        team_cost=total_cost,
        team_score=avg_value,
        budget_cap=team.budget_cap,
        budget_remaining=team.budget_cap - total_cost,
        squad_size=len(entries),
    )


def group_counts(entries: list[RosterEntryRecord]) -> dict[PositionGroup, int]:
    counts: dict[PositionGroup, int] = {g: 0 for g in PositionGroup}
    for entry in entries:
        counts[group_of(entry.position)] += 1
    return counts


# --------------------------------------------------------------------------
# Roster rows
# --------------------------------------------------------------------------


def roster_rows(
    store: Store,
    entries: list[RosterEntryRecord],
    ctx: LeagueContext | None = None,
    include_benchmarks: bool = True,
) -> list[RosterRow]:
    rows: list[RosterRow] = []
    for entry in sorted(entries, key=lambda e: (_slot_order(e.position), -e.value_score)):
        row = RosterRow(
            roster_entry_id=entry.id,
            player=player_ref(store, entry.player_id, entry.position),
            cost=entry.cost,
            value_score=entry.value_score,
            available=entry.available,
        )
        if include_benchmarks and ctx is not None:
            avg_cost = ctx.league_avg_cost(entry.position)
            avg_value = ctx.league_avg_value(entry.position)
            efficiency = ctx.cost_efficiency(entry.value_score, entry.cost)
            score = scoring.problem_score(
                value_percentile=ctx.value_percentile(entry.position, entry.value_score),
                cost_efficiency=efficiency,
            )
            row.league_avg_cost = avg_cost
            row.league_avg_value = avg_value
            row.cost_vs_league_pct = scoring.pct_vs_league(entry.cost, avg_cost)
            row.value_vs_league_pct = scoring.pct_vs_league(entry.value_score, avg_value)
            row.cost_efficiency = round(efficiency, 2)
            row.health_status = scoring.health_status(score)
        rows.append(row)
    return rows


def _slot_order(position: Position) -> int:
    order = FORMATIONS["4-3-3"]
    return order.index(position) if position in order else len(order)


# --------------------------------------------------------------------------
# Pitch map
# --------------------------------------------------------------------------


def build_pitch_map(
    entries: list[RosterEntryRecord],
    ctx: LeagueContext,
    minimums: dict[PositionGroup, int],
    formation: str = "4-3-3",
) -> PitchMap:
    counts = group_counts(entries)
    by_position: dict[Position, list[RosterEntryRecord]] = {}
    for entry in entries:
        by_position.setdefault(entry.position, []).append(entry)

    slots: list[PitchSlot] = []
    for position in FORMATIONS.get(formation, FORMATIONS["4-3-3"]):
        occupants = by_position.get(position, [])
        x, y = PITCH_COORDINATES[position]

        if occupants:
            avg_cost = int(round(statistics.fmean([e.cost for e in occupants])))
            avg_value = round(statistics.fmean([e.value_score for e in occupants]), 1)
            value_pct = statistics.fmean(
                [ctx.value_percentile(position, e.value_score) for e in occupants]
            )
            efficiency = statistics.fmean(
                [ctx.cost_efficiency(e.value_score, e.cost) for e in occupants]
            )
        else:
            avg_cost, avg_value, value_pct, efficiency = 0, 0.0, 0.0, 0.0

        penalty = scoring.coverage_penalty_for(position, len(occupants), counts, minimums)
        score = scoring.problem_score(value_pct, efficiency, penalty)
        status = scoring.health_status(score)

        slots.append(
            PitchSlot(
                position=position,
                position_group=group_of(position),
                x=x,
                y=y,
                health_status=status,
                problem_score=score,
                occupants=[e.player_id for e in occupants],
                slot_avg_cost=avg_cost,
                slot_avg_value=avg_value,
                headline=_headline(position, occupants, ctx, penalty) if status.value == "red" else None,
            )
        )
    return PitchMap(formation=formation, slots=slots)


def _headline(
    position: Position,
    occupants: list[RosterEntryRecord],
    ctx: LeagueContext,
    penalty: float,
) -> str:
    if not occupants:
        return f"No {position.value} on the roster"
    if penalty > 0:
        return f"{position.value} depth is below the squad minimum"
    avg_value = statistics.fmean([e.value_score for e in occupants])
    avg_cost = statistics.fmean([e.cost for e in occupants])
    value_gap = scoring.pct_vs_league(avg_value, ctx.league_avg_value(position))
    cost_gap = scoring.pct_vs_league(avg_cost, ctx.league_avg_cost(position))
    if value_gap < 0 and cost_gap > 0:
        return f"{abs(value_gap):.1f}% below league value at {cost_gap:.1f}% above league cost"
    if value_gap < 0:
        return f"{abs(value_gap):.1f}% below league average value"
    return f"{cost_gap:.1f}% above league average cost"


# --------------------------------------------------------------------------
# Benchmarks and market
# --------------------------------------------------------------------------


def benchmarks(ctx: LeagueContext, positions: list[Position] | None = None) -> list[PositionBenchmark]:
    wanted = positions or list(Position)
    out: list[PositionBenchmark] = []
    for position in wanted:
        values = ctx.value_by_position.get(position, [])
        costs = ctx.cost_by_position.get(position, [])
        if not values:
            continue
        out.append(
            PositionBenchmark(
                position=position,
                league_avg_cost=ctx.league_avg_cost(position),
                league_avg_value=ctx.league_avg_value(position),
                cost_p50=int(round(statistics.median(costs))),
                value_p50=round(statistics.median(values), 1),
                sample_size=len(values),
            )
        )
    return out


def listing_model(store: Store, record: MarketListingRecord) -> MarketListing:
    return MarketListing(
        listing_id=record.id,
        player=player_ref(store, record.player_id, record.position),
        source_team_id=record.source_team_id,
        cost=record.cost,
        expected_value_score=record.expected_value_score,
        available=record.available,
        updated_at=record.updated_at,
    )
