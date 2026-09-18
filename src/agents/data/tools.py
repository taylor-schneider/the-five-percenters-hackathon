"""The shared tool library. Agents compose their tool set from these.

Two rules hold everywhere in this file:

1. **Tools compute, agents interpret.** Every number a tool returns comes from
   services/scoring.py or services/trader_service.py -- the same code the
   deterministic path uses. The agent's job is to decide what to look at and to
   explain what it means, never to do the arithmetic.
2. **Observations are flat JSON.** No nested API response models. The model
   reads these as data, and a flat shape with explicit units costs fewer tokens
   and produces fewer misreadings than a faithful echo of the response schema.
"""

from __future__ import annotations

import statistics
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ...api.core.errors import AppError
from ...api.models.domain import TradeLegRequest
from ...api.models.enums import Position, PositionGroup, group_of
from ...api.repositories.store import MarketListingRecord, RosterEntryRecord
from ...api.services import scoring, team_service, trader_service
from ..core.errors import ToolExecutionError
from ..core.tools import NoArgs, Tool
from .context import AgentDeps


class ToolArgs(BaseModel):
    """Base for every tool argument model.

    extra="forbid" is load-bearing: it turns an invented argument into a
    validation error the model sees and corrects, instead of a silently ignored
    filter that makes the agent think it narrowed a search when it did not.
    """

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# Shared row builders
# --------------------------------------------------------------------------


def _roster_row(entry: RosterEntryRecord, deps: AgentDeps) -> dict[str, Any]:
    league = deps.league
    player = deps.store.get_player(entry.player_id)
    efficiency = league.cost_efficiency(entry.value_score, entry.cost)
    value_pct = league.value_percentile(entry.position, entry.value_score)
    problem = scoring.problem_score(value_pct, efficiency)
    return {
        "player_id": str(entry.player_id),
        "name": player.name if player else "unknown",
        "position": entry.position.value,
        "position_group": group_of(entry.position).value,
        "age": player.age if player else None,
        "appearances": player.appearances if player else None,
        "cost": entry.cost,
        "value_score": entry.value_score,
        "league_avg_cost": league.league_avg_cost(entry.position),
        "league_avg_value": league.league_avg_value(entry.position),
        "cost_vs_league_pct": scoring.pct_vs_league(
            entry.cost, league.league_avg_cost(entry.position)
        ),
        "value_vs_league_pct": scoring.pct_vs_league(
            entry.value_score, league.league_avg_value(entry.position)
        ),
        "value_percentile": round(value_pct, 2),
        "cost_efficiency": round(efficiency, 2),
        "problem_score": problem,
        "health_status": scoring.health_status(problem).value,
        "available_to_trade": entry.available,
    }


def _listing_row(listing: MarketListingRecord, deps: AgentDeps) -> dict[str, Any]:
    league = deps.league
    player = deps.store.get_player(listing.player_id)
    efficiency = league.cost_efficiency(listing.expected_value_score, listing.cost)
    return {
        "player_id": str(listing.player_id),
        "listing_id": str(listing.id),
        "name": player.name if player else "unknown",
        "position": listing.position.value,
        "position_group": group_of(listing.position).value,
        "age": player.age if player else None,
        "appearances": player.appearances if player else None,
        "cost": listing.cost,
        "expected_value_score": listing.expected_value_score,
        "value_vs_league_pct": scoring.pct_vs_league(
            listing.expected_value_score, league.league_avg_value(listing.position)
        ),
        "cost_vs_league_pct": scoring.pct_vs_league(
            listing.cost, league.league_avg_cost(listing.position)
        ),
        "value_percentile": round(
            league.value_percentile(listing.position, listing.expected_value_score), 2
        ),
        "cost_efficiency": round(efficiency, 2),
        "from_free_agency": listing.source_team_id is None,
    }


# --------------------------------------------------------------------------
# get_team_overview
# --------------------------------------------------------------------------


def _get_team_overview(_: NoArgs, deps: AgentDeps) -> dict[str, Any]:
    metrics = team_service.metrics_from_entries(deps.team, deps.roster)
    counts = deps.group_counts()
    return {
        "team_name": deps.team.name,
        "roster_version": deps.team.roster_version,
        "team_cost": metrics.team_cost,
        "team_score": metrics.team_score,
        "budget_cap": deps.budget_cap,
        "budget_remaining": deps.budget_cap - metrics.team_cost,
        "squad_size": metrics.squad_size,
        "position_group_counts": {g.value: n for g, n in counts.items()},
        "position_group_minimums": {g.value: n for g, n in deps.minimums.items()},
        "coverage_shortfalls": deps.shortfalls(),
        "currency": "EUR, whole euros, per season",
        "score_scale": "value_score and team_score are 0-100; team_score is the roster mean",
    }


get_team_overview = Tool(
    name="get_team_overview",
    description=(
        "Team-level KPIs: total salary, mean squad value score, cap headroom, squad size, "
        "and how many players sit in each position group against the required minimum. "
        "Start here -- it frames every other number you will read."
    ),
    args_model=NoArgs,
    handler=_get_team_overview,
)


# --------------------------------------------------------------------------
# get_roster
# --------------------------------------------------------------------------


class GetRosterArgs(ToolArgs):
    position: Position | None = Field(
        default=None, description="Filter to one specific slot, e.g. CB."
    )
    position_group: PositionGroup | None = Field(
        default=None, description="Filter to one group: GK, DEF, MID or FWD."
    )
    sort_by: Literal["problem_score", "value_score", "cost", "cost_efficiency"] = Field(
        default="problem_score",
        description=(
            "problem_score descending surfaces the weakest links first; value_score and "
            "cost descend; cost_efficiency ascends (worst value per euro first)."
        ),
    )
    limit: int = Field(default=30, ge=1, le=60)


def _get_roster(args: GetRosterArgs, deps: AgentDeps) -> dict[str, Any]:
    entries = deps.roster
    if args.position is not None:
        entries = [e for e in entries if e.position == args.position]
    if args.position_group is not None:
        entries = [e for e in entries if group_of(e.position) == args.position_group]

    rows = [_roster_row(e, deps) for e in entries]
    if args.sort_by == "cost_efficiency":
        rows.sort(key=lambda r: r["cost_efficiency"])
    else:
        rows.sort(key=lambda r: r[args.sort_by], reverse=True)

    return {
        "roster_version": deps.team.roster_version,
        "returned": len(rows[: args.limit]),
        "total_matching": len(rows),
        "players": rows[: args.limit],
        "field_notes": {
            "cost_vs_league_pct": "positive = paid above the league average for this position",
            "value_vs_league_pct": "negative = performing below the league average",
            "cost_efficiency": "0-1, value per euro normalised across the league",
            "problem_score": "0-1 from api.md section 4; >= 0.67 is a red flag",
        },
    }


get_roster = Tool(
    name="get_roster",
    description=(
        "The team's current players with their salary, value score, and how each compares "
        "with the league average for the same position. Filter by position or group, sort "
        "to surface the weakest links."
    ),
    args_model=GetRosterArgs,
    handler=_get_roster,
)


# --------------------------------------------------------------------------
# get_position_benchmarks
# --------------------------------------------------------------------------


class GetBenchmarksArgs(ToolArgs):
    positions: list[Position] = Field(
        default_factory=list,
        description="Empty returns every position. Narrow it once you know where to look.",
    )


def _get_position_benchmarks(args: GetBenchmarksArgs, deps: AgentDeps) -> dict[str, Any]:
    wanted = args.positions or list(Position)
    league = deps.league
    by_position: dict[Position, list[RosterEntryRecord]] = {}
    for entry in deps.roster:
        by_position.setdefault(entry.position, []).append(entry)

    rows = []
    for position in wanted:
        occupants = by_position.get(position, [])
        sample = league.sample_size(position)
        rows.append(
            {
                "position": position.value,
                "position_group": group_of(position).value,
                "league_avg_cost": league.league_avg_cost(position),
                "league_avg_value": league.league_avg_value(position),
                "league_sample_size": sample,
                "thin_sample": sample < 5,
                "team_occupants": len(occupants),
                "team_avg_cost": (
                    int(round(statistics.fmean([e.cost for e in occupants]))) if occupants else 0
                ),
                "team_avg_value": (
                    round(statistics.fmean([e.value_score for e in occupants]), 1)
                    if occupants
                    else 0.0
                ),
            }
        )
    return {
        "benchmarks": rows,
        "note": (
            "thin_sample true means fewer than 5 league players at this position -- say so "
            "in your commentary rather than treating the average as solid."
        ),
    }


get_position_benchmarks = Tool(
    name="get_position_benchmarks",
    description=(
        "League average salary and value score per position, with the sample size behind "
        "each average and this team's own average alongside it. Use it to justify any claim "
        "that a position is over- or under-paid."
    ),
    args_model=GetBenchmarksArgs,
    handler=_get_position_benchmarks,
)


# --------------------------------------------------------------------------
# inspect_player
# --------------------------------------------------------------------------


class InspectPlayerArgs(ToolArgs):
    player_id: UUID = Field(description="Copy the player_id exactly as another tool returned it.")


def _inspect_player(args: InspectPlayerArgs, deps: AgentDeps) -> dict[str, Any]:
    entry = deps.entry_for(args.player_id)
    league = deps.league
    if entry is not None:
        row = _roster_row(entry, deps)
        peers = [
            _roster_row(e, deps)
            for e in deps.roster
            if e.position == entry.position and e.player_id != entry.player_id
        ]
        replacements = deps.store.list_listings(
            position=entry.position, exclude_team_id=deps.team.id, available_only=True
        )[:5]
        return {
            "on_roster": True,
            "player": row,
            "cost_percentile": round(league.cost_percentile(entry.position, entry.cost), 2),
            "same_position_teammates": peers,
            "market_alternatives_at_this_position": [
                _listing_row(listing, deps) for listing in replacements
            ],
        }

    listing = deps.store.find_listing_for_player(args.player_id)
    if listing is None:
        raise ToolExecutionError(
            f"player {args.player_id} is neither on this roster nor on the market; "
            "use get_roster or search_market to get valid player_ids"
        )
    return {"on_roster": False, "listing": _listing_row(listing, deps)}


inspect_player = Tool(
    name="inspect_player",
    description=(
        "One player in depth: their benchmark position, their cost and value percentiles, "
        "who else on the squad plays there, and what the market offers at that position. "
        "Use before writing commentary about an individual."
    ),
    args_model=InspectPlayerArgs,
    handler=_inspect_player,
)


# --------------------------------------------------------------------------
# search_market
# --------------------------------------------------------------------------


class SearchMarketArgs(ToolArgs):
    position: Position | None = None
    position_group: PositionGroup | None = None
    max_cost: int | None = Field(
        default=None, description="Whole euros. Upper bound on the salary you would take on."
    )
    min_value: float | None = Field(
        default=None, description="Lower bound on expected_value_score, 0-100."
    )
    limit: int = Field(default=12, ge=1, le=40)


def _search_market(args: SearchMarketArgs, deps: AgentDeps) -> dict[str, Any]:
    listings = deps.store.list_listings(
        position=args.position,
        position_group=args.position_group,
        max_cost=args.max_cost,
        min_value=args.min_value,
        exclude_team_id=deps.team.id,
        available_only=True,
    )
    rows = [_listing_row(listing, deps) for listing in listings[: args.limit]]
    return {
        "returned": len(rows),
        "total_matching": len(listings),
        "listings": rows,
        "note": (
            "cost is the salary the player will carry on your roster, not a transfer fee. "
            "Low appearances means the expected_value_score rests on a thin sample."
        ),
    }


search_market = Tool(
    name="search_market",
    description=(
        "Acquirable players, filtered by position, group, maximum salary or minimum value "
        "score. Returns each listing benchmarked against the league for its position."
    ),
    args_model=SearchMarketArgs,
    handler=_search_market,
)


# --------------------------------------------------------------------------
# simulate_trade
# --------------------------------------------------------------------------


class SimulateTradeArgs(ToolArgs):
    legs: list[TradeLegRequest] = Field(
        min_length=1,
        max_length=8,
        description=(
            "Each leg is {action, player_id}. action is buy, sell, swap_in or swap_out. "
            "A swap needs at least one swap_in and one swap_out. Never send prices -- the "
            "server prices every leg from authoritative data."
        ),
    )


def _simulate_trade(args: SimulateTradeArgs, deps: AgentDeps) -> dict[str, Any]:
    try:
        trader_service.validate_leg_shape(args.legs)
        resolved = trader_service.resolve_legs(deps.store, deps.team, args.legs)
        impact = trader_service.compute_impact(deps.store, deps.team, resolved, deps.minimums)
    except AppError as exc:
        # A rejected trade is information, not a crash: hand the model the
        # reason so it can propose a legal alternative on the next turn.
        raise ToolExecutionError(f"{exc.code.value}: {exc.message}") from exc

    return {
        "valid": impact.valid,
        "violations": [
            {"code": v.code, "severity": v.severity.value, "message": v.message}
            for v in impact.violations
        ],
        "projected_cost_delta": impact.projected_cost_delta,
        "projected_value_delta": impact.projected_value_delta,
        "current": {
            "team_cost": impact.current_metrics.team_cost,
            "team_score": impact.current_metrics.team_score,
            "squad_size": impact.current_metrics.squad_size,
        },
        "post_trade": {
            "team_cost": impact.post_trade_metrics.team_cost,
            "team_score": impact.post_trade_metrics.team_score,
            "budget_remaining": impact.post_trade_metrics.budget_remaining,
            "squad_size": impact.post_trade_metrics.squad_size,
        },
        "position_group_counts_after": {
            g.value: n for g, n in impact.position_group_counts_after.items()
        },
        "legs": [
            {
                "action": leg.model.action.value,
                "player": leg.model.player.name,
                "player_id": str(leg.model.player.player_id),
                "position": leg.model.player.position.value,
                "cost_delta": leg.model.cost_delta,
                "value_delta": leg.model.value_delta,
            }
            for leg in resolved
        ],
        "note": (
            "valid false with a high-severity violation means this trade can never be "
            "executed. Low and medium violations are risks to mention, not blockers."
        ),
    }


simulate_trade = Tool(
    name="simulate_trade",
    description=(
        "Price and validate a proposed trade against the live roster: cost delta, team score "
        "delta, post-trade cap headroom, squad-minimum checks and any rule violations. "
        "Writes nothing. Run this before proposing any trade -- every number you quote must "
        "come from here."
    ),
    args_model=SimulateTradeArgs,
    handler=_simulate_trade,
)


#: Read-only tools every agent can safely hold.
READ_TOOLS: list[Tool] = [
    get_team_overview,
    get_roster,
    get_position_benchmarks,
    inspect_player,
    search_market,
]
