"""Opportunity Finder: generates and ranks candidate trades.

Phase 1 is a deterministic candidate generator: for each focus position it pairs
the weakest roster entries against available market listings and scores the
result. Phase 2 swaps in an LLM behind the same signature (D11).

Ranking is api.md section 4's opportunity_score, min-max normalised within the
candidate set -- so scores are comparable inside one response and nowhere else.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from ..core.config import get_settings
from ..models.domain import Opportunity, TradeImpact, TradeLegRequest
from ..models.enums import (
    AgentName,
    OpportunityType,
    Position,
    TradeAction,
    group_of,
)
from ..models.requests import OpportunityFinderRequest
from ..models.responses import OpportunityFinderResponse
from ..repositories.store import RosterEntryRecord, Store, TeamRecord, utcnow
from . import scoring, team_service, trader_service
from .agent_runtime import agent_run
from .gap_finder_service import resolve_minimums
from .opportunity_cache import get_opportunity_cache, new_opportunity_id
from .scoring import LeagueContext

#: Cap on generated candidates before ranking. Keeps a single request bounded
#: when the focus is the whole squad.
_MAX_CANDIDATES = 300


def find(store: Store, request: OpportunityFinderRequest) -> OpportunityFinderResponse:
    team = team_service.require_team(store, request.team_id)
    trader_service._check_version(team, request.roster_version)

    entries = store.current_roster(team.id)
    ctx = LeagueContext.build(store.all_current_entries())
    minimums = resolve_minimums(request.constraints.min_position_group_counts)

    payload = {
        "team_id": str(team.id),
        "roster_version": team.roster_version,
        "focus": request.focus.model_dump(mode="json"),
        "constraints": request.constraints.model_dump(mode="json"),
    }

    with agent_run(AgentName.OPPORTUNITY_FINDER, payload) as meta:
        candidates, evaluated = _generate(store, team, entries, ctx, request, minimums)
        opportunities = _rank_and_trim(candidates, request.constraints.max_results)

    get_opportunity_cache().put_many(opportunities, team.id, team.roster_version)

    return OpportunityFinderResponse(
        team_id=team.id,
        focus=request.focus,
        opportunities=opportunities,
        candidates_evaluated=evaluated,
        roster_version=team.roster_version,
        agent_meta=meta[0],
        generated_at=utcnow(),
    )


# --------------------------------------------------------------------------
# Candidate generation
# --------------------------------------------------------------------------


class _Candidate:
    __slots__ = ("type", "position", "legs", "impact", "risk", "confidence", "incoming", "outgoing")

    def __init__(
        self,
        type_: OpportunityType,
        position: Position,
        legs: list[TradeLegRequest],
        impact: TradeImpact,
        risk: float,
        confidence: float,
        incoming: list[str],
        outgoing: list[str],
    ) -> None:
        self.type = type_
        self.position = position
        self.legs = legs
        self.impact = impact
        self.risk = risk
        self.confidence = confidence
        self.incoming = incoming
        self.outgoing = outgoing


def _focus_positions(
    request: OpportunityFinderRequest, entries: list[RosterEntryRecord]
) -> list[Position]:
    positions: set[Position] = set(request.focus.positions)
    if request.focus.player_ids:
        wanted = set(request.focus.player_ids)
        positions.update(e.position for e in entries if e.player_id in wanted)
    if not positions:
        positions = {e.position for e in entries}
    return sorted(positions, key=lambda p: p.value)


def _generate(
    store: Store,
    team: TeamRecord,
    entries: list[RosterEntryRecord],
    ctx: LeagueContext,
    request: OpportunityFinderRequest,
    minimums,
) -> tuple[list[_Candidate], int]:
    settings = get_settings()
    types = set(request.focus.types)
    focus_player_ids = set(request.focus.player_ids)
    candidates: list[_Candidate] = []
    evaluated = 0

    for position in _focus_positions(request, entries):
        occupants = [e for e in entries if e.position == position]
        if focus_player_ids:
            occupants = [e for e in occupants if e.player_id in focus_player_ids] or occupants

        # Weakest first: these are the players worth moving on.
        occupants.sort(
            key=lambda e: scoring.problem_score(
                ctx.value_percentile(e.position, e.value_score),
                ctx.cost_efficiency(e.value_score, e.cost),
            ),
            reverse=True,
        )
        listings = store.list_listings(
            position=position, exclude_team_id=team.id, available_only=True
        )[:8]

        # --- swaps: replace a weak occupant with a better listing -----------
        if OpportunityType.SWAP in types:
            for entry in occupants[:3]:
                if not entry.available:
                    continue
                for listing in listings:
                    if evaluated >= _MAX_CANDIDATES:
                        break
                    evaluated += 1
                    if listing.expected_value_score <= entry.value_score:
                        continue
                    legs = [
                        TradeLegRequest(action=TradeAction.SWAP_OUT, player_id=entry.player_id),
                        TradeLegRequest(action=TradeAction.SWAP_IN, player_id=listing.player_id),
                    ]
                    candidate = _build(store, team, legs, OpportunityType.SWAP, position, minimums)
                    if candidate is not None:
                        candidates.append(candidate)

        # --- buys: add depth where the squad is thin ------------------------
        if OpportunityType.BUY in types:
            for listing in listings[:4]:
                if evaluated >= _MAX_CANDIDATES:
                    break
                evaluated += 1
                legs = [TradeLegRequest(action=TradeAction.BUY, player_id=listing.player_id)]
                candidate = _build(store, team, legs, OpportunityType.BUY, position, minimums)
                if candidate is not None:
                    candidates.append(candidate)

        # --- sells: free budget by moving on poor value ---------------------
        if OpportunityType.SELL in types:
            for entry in occupants[:2]:
                if evaluated >= _MAX_CANDIDATES:
                    break
                evaluated += 1
                if not entry.available:
                    continue
                legs = [TradeLegRequest(action=TradeAction.SELL, player_id=entry.player_id)]
                candidate = _build(store, team, legs, OpportunityType.SELL, position, minimums)
                if candidate is not None:
                    candidates.append(candidate)

    # --- apply the client's hard filters -----------------------------------
    constraints = request.constraints
    filtered = []
    for candidate in candidates:
        if not candidate.impact.valid:
            continue
        if (
            constraints.max_cost_increase is not None
            and candidate.impact.projected_cost_delta > constraints.max_cost_increase
        ):
            continue
        if (
            constraints.min_value_gain is not None
            and candidate.impact.projected_value_delta < constraints.min_value_gain
        ):
            continue
        filtered.append(candidate)

    return filtered, evaluated


def _build(
    store: Store,
    team: TeamRecord,
    legs: list[TradeLegRequest],
    type_: OpportunityType,
    position: Position,
    minimums,
) -> _Candidate | None:
    try:
        resolved = trader_service.resolve_legs(store, team, legs)
        impact = trader_service.compute_impact(store, team, resolved, minimums)
    except Exception:
        # A candidate that cannot even be priced is not a candidate.
        return None

    incoming = [leg.model.player.name for leg in resolved if leg.action.is_incoming]
    outgoing = [leg.model.player.name for leg in resolved if leg.action.is_outgoing]

    appearances = [leg.appearances for leg in resolved if leg.action.is_incoming]
    if appearances:
        sample = min(appearances)
        confidence = round(max(0.30, min(0.95, sample / 38)), 2)
        risk = round(1.0 - confidence, 2)
    else:
        # Selling carries no incoming-performance uncertainty.
        confidence, risk = 0.88, 0.12

    return _Candidate(
        type_=type_,
        position=position,
        legs=legs,
        impact=impact,
        risk=risk,
        confidence=confidence,
        incoming=incoming,
        outgoing=outgoing,
    )


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------


def _rank_and_trim(candidates: list[_Candidate], max_results: int) -> list[Opportunity]:
    if not candidates:
        return []

    value_gains = [c.impact.projected_value_delta for c in candidates]
    cost_savings = [-c.impact.projected_cost_delta for c in candidates]
    risks = [c.risk for c in candidates]
    scores = scoring.opportunity_scores(value_gains, cost_savings, risks)

    ttl = timedelta(seconds=get_settings().opportunity_ttl_seconds)
    expires_at = utcnow() + ttl

    ranked = sorted(zip(candidates, scores, strict=True), key=lambda pair: pair[1], reverse=True)

    out: list[Opportunity] = []
    for candidate, score in ranked[:max_results]:
        out.append(
            Opportunity(
                opportunity_id=new_opportunity_id(),
                type=candidate.type,
                target_position=candidate.position,
                opportunity_score=score,
                confidence=candidate.confidence,
                legs=_response_legs(candidate),
                impact=candidate.impact,
                risks=_risks(candidate),
                reasoning_summary=_summary(candidate),
                reasoning_steps=_steps(candidate),
                expires_at=expires_at,
            )
        )
    return out


def _response_legs(candidate: _Candidate):
    # compute_impact already resolved these; rebuild the response models from
    # the cached impact by re-resolving is wasteful, so the candidate keeps them.
    return candidate._resolved_models  # type: ignore[attr-defined]


def _risks(candidate: _Candidate) -> list[str]:
    risks = [
        v.message for v in candidate.impact.violations if v.severity.value in ("low", "medium")
    ]
    if candidate.confidence < 0.5 and not risks:
        risks.append("Limited appearance data for the incoming player")
    return risks


def _summary(candidate: _Candidate) -> str:
    cost = candidate.impact.projected_cost_delta
    value = candidate.impact.projected_value_delta
    money = f"EUR {abs(cost):,}"
    direction = "cutting" if cost < 0 else "adding"

    if candidate.type is OpportunityType.SWAP:
        return (
            f"Replace {candidate.outgoing[0]} with {candidate.incoming[0]} at "
            f"{candidate.position.value}, {direction} {money} of salary for "
            f"{value:+.1f} team score."
        )
    if candidate.type is OpportunityType.BUY:
        return (
            f"Sign {candidate.incoming[0]} to strengthen {candidate.position.value} "
            f"for {money} of salary ({value:+.1f} team score)."
        )
    return (
        f"Release {candidate.outgoing[0]} to free {money} of salary "
        f"({value:+.1f} team score)."
    )


def _steps(candidate: _Candidate) -> list[str]:
    impact = candidate.impact
    steps = [
        f"{candidate.position.value} was selected from the current focus.",
    ]
    if candidate.outgoing:
        steps.append(f"{', '.join(candidate.outgoing)} leaves the roster.")
    if candidate.incoming:
        steps.append(f"{', '.join(candidate.incoming)} joins at the listed salary.")
    steps.append(
        f"Team salary moves {impact.projected_cost_delta:+,} to "
        f"EUR {impact.post_trade_metrics.team_cost:,}."
    )
    steps.append(
        f"Team score moves {impact.projected_value_delta:+.1f} to "
        f"{impact.post_trade_metrics.team_score:.1f}."
    )
    steps.append(
        f"EUR {impact.post_trade_metrics.budget_remaining:,} of headroom remains under "
        f"the EUR {impact.post_trade_metrics.budget_cap:,} cap."
    )
    return steps
