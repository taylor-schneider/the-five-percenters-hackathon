"""The deterministic operations agents call.

This is the tool surface. Everything in here is arithmetic, data access, or a
transactional write -- the things an LLM should never do from its own head:

* reading the roster, the benchmarks, and the market
* pricing a trade (summing salaries, recomputing team_score)
* checking hard rules (budget cap, squad minimums, availability)
* committing the write

Judgement -- what counts as a problem, which trade is worth proposing, how to
justify it -- is the agent's job and lives nowhere in this file.

Each public function here is shaped to become one Claude tool. They take plain
JSON-able arguments and return plain JSON-able results, so wrapping them with
`@beta_tool` (or any other binding) is mechanical.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ..models.domain import TradeImpact
from ..models.enums import Position, PositionGroup
from ..models.requests import Constraints
from ..repositories.store import Store
from ..services import team_service, trader_service
from ..services.scoring import LeagueContext


# --------------------------------------------------------------------------
# Read tools
# --------------------------------------------------------------------------


def get_team_context(store: Store, team_id: UUID) -> dict[str, Any]:
    """Everything an agent needs to reason about one squad.

    Returns raw measured numbers only. No traffic lights, no problem scores,
    no "this is bad" -- those are the agent's call.
    """
    team = team_service.require_team(store, team_id)
    entries = store.current_roster(team_id)
    ctx = LeagueContext.build(store.all_current_entries())

    return {
        "team": team_service.team_summary(team).model_dump(mode="json"),
        "metrics": team_service.metrics_from_entries(team, entries).model_dump(mode="json"),
        "roster": [
            row.model_dump(mode="json")
            for row in team_service.roster_rows(store, entries, ctx, include_benchmarks=True)
        ],
        "position_group_counts": {
            g.value: c for g, c in team_service.group_counts(entries).items()
        },
        "roster_version": team.roster_version,
    }


def get_position_benchmarks(
    store: Store, positions: list[Position] | None = None
) -> list[dict[str, Any]]:
    """League average and median cost/value per position, with sample sizes."""
    ctx = LeagueContext.build(store.all_current_entries())
    return [b.model_dump(mode="json") for b in team_service.benchmarks(ctx, positions)]


def search_market(
    store: Store,
    position: Position | None = None,
    position_group: PositionGroup | None = None,
    max_cost: int | None = None,
    min_value: float | None = None,
    exclude_team_id: UUID | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Acquirable players. `cost` is the salary they will carry (D1)."""
    records = store.list_listings(
        position=position,
        position_group=position_group,
        max_cost=max_cost,
        min_value=min_value,
        exclude_team_id=exclude_team_id,
    )
    return [
        team_service.listing_model(store, record).model_dump(mode="json")
        for record in records[:limit]
    ]


# --------------------------------------------------------------------------
# Pricing and validation tools
# --------------------------------------------------------------------------


def price_trade(
    store: Store,
    team_id: UUID,
    legs: list[dict[str, str]],
    constraints: Constraints | None = None,
) -> dict[str, Any]:
    """Price a set of legs and check it against the hard rules.

    `legs` is `[{"action": "swap_out", "player_id": "..."}, ...]`. Prices are
    never supplied by the caller -- they are resolved from the roster and the
    market (D2).

    Returns a TradeImpact: the signed cost/value deltas, the before/after
    metrics, and any violations. An agent should call this before proposing a
    trade rather than estimating the arithmetic itself.
    """
    from ..models.domain import TradeLegRequest

    team = team_service.require_team(store, team_id)
    parsed = [TradeLegRequest.model_validate(leg) for leg in legs]
    trader_service.validate_leg_shape(parsed)
    resolved = trader_service.resolve_legs(store, team, parsed)
    minimums = team_service.resolve_minimums(
        constraints.min_position_group_counts if constraints else None
    )
    impact: TradeImpact = trader_service.compute_impact(store, team, resolved, minimums)
    return impact.model_dump(mode="json")


def check_trade_legality(
    store: Store, team_id: UUID, legs: list[dict[str, str]]
) -> dict[str, Any]:
    """Just the verdict, for when an agent is filtering candidates in bulk."""
    impact = price_trade(store, team_id, legs)
    return {
        "valid": impact["valid"],
        "violations": impact["violations"],
        "projected_cost_delta": impact["projected_cost_delta"],
        "projected_value_delta": impact["projected_value_delta"],
    }


def score_position_baseline(
    store: Store, team_id: UUID, position: Position
) -> dict[str, Any]:
    """The api.md section 4 formula, as an ADVISORY tool.

    Nothing calls this automatically. It exists so an agent can ask for a
    numeric baseline -- value percentile, cost efficiency, the weighted
    problem_score and the traffic-light band it falls in -- and then agree,
    disagree, or ignore it.

    The agent still owns the verdict. If this were wired into the response path
    instead, the formula would be the Gap Finder and the agent would be
    decoration.
    """
    from ..services import scoring

    team_service.require_team(store, team_id)
    ctx = LeagueContext.build(store.all_current_entries())
    occupants = [e for e in store.current_roster(team_id) if e.position == position]
    if not occupants:
        return {
            "position": position.value,
            "occupants": 0,
            "note": "Slot is unfilled, which is itself a gap.",
        }

    value_pct = sum(
        ctx.value_percentile(position, e.value_score) for e in occupants
    ) / len(occupants)
    efficiency = sum(
        ctx.cost_efficiency(e.value_score, e.cost) for e in occupants
    ) / len(occupants)
    score = scoring.problem_score(value_pct, efficiency)

    return {
        "position": position.value,
        "occupants": len(occupants),
        "value_percentile": round(value_pct, 3),
        "cost_efficiency": round(efficiency, 3),
        "problem_score": score,
        "suggested_band": scoring.health_status(score).value,
        "note": "Advisory only. The agent decides the actual health_status.",
    }


#: Names the agent branch can bind to. Kept as data so the tool list and the
#: implementations cannot drift apart.
READ_TOOLS = ("get_team_context", "get_position_benchmarks", "search_market")
PRICING_TOOLS = ("price_trade", "check_trade_legality")
ADVISORY_TOOLS = ("score_position_baseline",)
ALL_TOOLS = READ_TOOLS + PRICING_TOOLS + ADVISORY_TOOLS
