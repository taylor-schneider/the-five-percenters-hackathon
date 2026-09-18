"""Trader: leg resolution, impact simulation, validation, and execution.

The impact maths here is the load-bearing part of D1. A trade's cost is the
total salary coming on minus the total salary going off -- nothing else
contributes -- which is what makes

    post_trade_metrics.team_cost == current_metrics.team_cost + projected_cost_delta

true by construction rather than by careful bookkeeping.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from ..core.config import get_settings
from ..core.errors import (
    HARD_VIOLATION_CODES,
    AppError,
    ErrorCode,
    bad_request,
    conflict,
    not_found,
)
from ..models.domain import (
    Opportunity,
    TeamMetrics,
    TradeImpact,
    TradeLeg,
    TradeLegRequest,
    TradeRecord,
    Violation,
)
from ..models.enums import (
    AgentName,
    PositionGroup,
    Severity,
    TradeAction,
    TradeStatus,
    group_of,
)
from ..models.requests import ExecuteRequest, SimulateRequest
from ..models.responses import AppliedChanges, ExecuteResponse, SimulateResponse
from ..repositories.store import (
    RosterEntryRecord,
    Store,
    TeamRecord,
    TradeRecordRow,
    utcnow,
)
from . import team_service
from .agent_runtime import agent_run, snapshot_hash
from .gap_finder_service import resolve_minimums
from .opportunity_cache import OpportunityCache, get_opportunity_cache


@dataclass(slots=True)
class ResolvedLeg:
    """A leg with its salary and value resolved from authoritative data (D2)."""

    action: TradeAction
    player_id: UUID
    model: TradeLeg
    entry: RosterEntryRecord | None = None
    listing_id: UUID | None = None
    cost: int = 0
    value_score: float = 0.0
    appearances: int = 30


# --------------------------------------------------------------------------
# Leg resolution
# --------------------------------------------------------------------------


def resolve_legs(
    store: Store, team: TeamRecord, requested: list[TradeLegRequest]
) -> list[ResolvedLeg]:
    """Turn client legs into priced legs. Clients never send prices (D2)."""
    resolved: list[ResolvedLeg] = []
    seen: set[UUID] = set()

    for leg in requested:
        if leg.player_id in seen:
            raise conflict(
                ErrorCode.DUPLICATE_PLAYER_IN_TRADE,
                f"Player {leg.player_id} appears in more than one leg",
                player_id=str(leg.player_id),
            )
        seen.add(leg.player_id)

        player = store.get_player(leg.player_id)
        if player is None:
            raise not_found(
                ErrorCode.PLAYER_NOT_FOUND,
                f"Player {leg.player_id} not found",
                player_id=str(leg.player_id),
            )

        if leg.action.is_outgoing:
            entry = store.find_roster_entry(team.id, leg.player_id)
            if entry is None:
                raise conflict(
                    ErrorCode.PLAYER_NOT_ON_ROSTER,
                    f"{player.name} is not on this team's current roster",
                    player_id=str(leg.player_id),
                    team_id=str(team.id),
                )
            resolved.append(
                ResolvedLeg(
                    action=leg.action,
                    player_id=leg.player_id,
                    entry=entry,
                    cost=entry.cost,
                    value_score=entry.value_score,
                    appearances=player.appearances,
                    model=TradeLeg(
                        action=leg.action,
                        player=team_service.player_ref(store, leg.player_id, entry.position),
                        cost_delta=-entry.cost,
                        value_delta=-entry.value_score,
                        counterparty_team_id=None,
                        listing_id=None,
                    ),
                )
            )
        else:
            listing = store.find_listing_for_player(leg.player_id)
            if listing is None:
                raise conflict(
                    ErrorCode.PLAYER_NOT_AVAILABLE,
                    f"{player.name} has no available market listing",
                    player_id=str(leg.player_id),
                )
            resolved.append(
                ResolvedLeg(
                    action=leg.action,
                    player_id=leg.player_id,
                    listing_id=listing.id,
                    cost=listing.cost,
                    value_score=listing.expected_value_score,
                    appearances=player.appearances,
                    model=TradeLeg(
                        action=leg.action,
                        player=team_service.player_ref(store, leg.player_id, listing.position),
                        cost_delta=listing.cost,
                        value_delta=listing.expected_value_score,
                        counterparty_team_id=listing.source_team_id,
                        listing_id=listing.id,
                    ),
                )
            )
    return resolved


def validate_leg_shape(legs: list[TradeLegRequest]) -> None:
    """Structural checks that the schema cannot express."""
    if not legs:
        raise bad_request(ErrorCode.INVALID_LEG_COMBINATION, "At least one leg is required")
    swap_in = sum(1 for leg in legs if leg.action is TradeAction.SWAP_IN)
    swap_out = sum(1 for leg in legs if leg.action is TradeAction.SWAP_OUT)
    if bool(swap_in) != bool(swap_out):
        raise bad_request(
            ErrorCode.INVALID_LEG_COMBINATION,
            "A swap needs at least one swap_in and one swap_out leg",
            swap_in=swap_in,
            swap_out=swap_out,
        )


# --------------------------------------------------------------------------
# Impact
# --------------------------------------------------------------------------


def compute_impact(
    store: Store,
    team: TeamRecord,
    legs: list[ResolvedLeg],
    minimums: dict[PositionGroup, int] | None = None,
) -> TradeImpact:
    settings = get_settings()
    minimums = minimums or resolve_minimums(None)
    entries = store.current_roster(team.id)
    current = team_service.metrics_from_entries(team, entries)

    outgoing_ids = {leg.player_id for leg in legs if leg.action.is_outgoing}
    remaining = [e for e in entries if e.player_id not in outgoing_ids]

    incoming = [leg for leg in legs if leg.action.is_incoming]
    post_costs = [e.cost for e in remaining] + [leg.cost for leg in incoming]
    post_values = [e.value_score for e in remaining] + [leg.value_score for leg in incoming]

    post_cost_total = sum(post_costs)
    post_score = round(statistics.fmean(post_values), 1) if post_values else 0.0

    post = TeamMetrics(
        team_cost=post_cost_total,
        team_score=post_score,
        budget_cap=team.budget_cap,
        budget_remaining=team.budget_cap - post_cost_total,
        squad_size=len(post_costs),
    )

    # D1 identity: the sum of leg cost_delta values IS the team cost delta.
    cost_delta = sum(leg.model.cost_delta for leg in legs)

    counts: dict[PositionGroup, int] = {g: 0 for g in PositionGroup}
    for entry in remaining:
        counts[group_of(entry.position)] += 1
    for leg in incoming:
        counts[group_of(leg.model.player.position)] += 1

    violations = _validate(
        team=team,
        legs=legs,
        post=post,
        counts=counts,
        minimums=minimums,
        max_squad=settings.max_squad_size,
    )

    return TradeImpact(
        valid=not any(Violation.model_validate(v).severity is Severity.HIGH for v in violations),
        violations=violations,
        projected_cost_delta=cost_delta,
        projected_value_delta=round(post.team_score - current.team_score, 1),
        current_metrics=current,
        post_trade_metrics=post,
        position_group_counts_after=counts,
        roster_version=team.roster_version,
    )


def _validate(
    team: TeamRecord,
    legs: list[ResolvedLeg],
    post: TeamMetrics,
    counts: dict[PositionGroup, int],
    minimums: dict[PositionGroup, int],
    max_squad: int,
) -> list[Violation]:
    violations: list[Violation] = []

    if post.team_cost > team.budget_cap:
        overage = post.team_cost - team.budget_cap
        violations.append(
            Violation(
                code=ErrorCode.BUDGET_CAP_EXCEEDED.value,
                severity=Severity.HIGH,
                message=f"Trade would exceed budget cap by EUR {overage:,}",
                details={
                    "post_trade_cost": post.team_cost,
                    "budget_cap": team.budget_cap,
                    "overage": overage,
                },
            )
        )

    for group, required in minimums.items():
        actual = counts.get(group, 0)
        if actual < required:
            violations.append(
                Violation(
                    code=ErrorCode.POSITION_MINIMUM_VIOLATED.value,
                    severity=Severity.HIGH,
                    message=f"{group.value} would fall to {actual}, below the minimum of {required}",
                    details={"position_group": group.value, "required": required, "actual": actual},
                )
            )

    if post.squad_size > max_squad:
        violations.append(
            Violation(
                code=ErrorCode.SQUAD_SIZE_EXCEEDED.value,
                severity=Severity.HIGH,
                message=f"Squad would grow to {post.squad_size}, above the maximum of {max_squad}",
                details={"squad_size": post.squad_size, "max_squad_size": max_squad},
            )
        )

    for leg in legs:
        if leg.action.is_outgoing and leg.entry is not None and not leg.entry.available:
            violations.append(
                Violation(
                    code=ErrorCode.PLAYER_NOT_AVAILABLE.value,
                    severity=Severity.HIGH,
                    message=f"{leg.model.player.name} is not available to leave the squad",
                    details={"player_id": str(leg.player_id)},
                )
            )

    # --- soft violations: surfaced, never blocking ------------------------
    for leg in legs:
        if leg.action.is_incoming and leg.appearances < 12:
            violations.append(
                Violation(
                    code=ErrorCode.HIGH_UNCERTAINTY.value,
                    severity=Severity.MEDIUM,
                    message=(
                        f"{leg.model.player.name}'s expected value rests on only "
                        f"{leg.appearances} league appearances"
                    ),
                    details={"player_id": str(leg.player_id), "appearances": leg.appearances},
                )
            )

    churn: dict[PositionGroup, int] = {}
    for leg in legs:
        grp = group_of(leg.model.player.position)
        churn[grp] = churn.get(grp, 0) + 1
    for grp, count in churn.items():
        if count >= 3:
            violations.append(
                Violation(
                    code=ErrorCode.POSITION_CHURN.value,
                    severity=Severity.LOW,
                    message=f"{count} simultaneous changes in {grp.value}",
                    details={"position_group": grp.value, "changes": count},
                )
            )

    return violations


# --------------------------------------------------------------------------
# Simulate
# --------------------------------------------------------------------------


def _check_version(team: TeamRecord, supplied: int | None) -> None:
    if supplied is not None and supplied != team.roster_version:
        raise conflict(
            ErrorCode.STALE_ROSTER_VERSION,
            "Roster has changed since this view was rendered",
            supplied=supplied,
            current=team.roster_version,
        )


def _legs_from_source(
    store: Store,
    team: TeamRecord,
    opportunity_id: str | None,
    legs: list[TradeLegRequest] | None,
    cache: OpportunityCache,
) -> tuple[list[ResolvedLeg], Opportunity | None]:
    if opportunity_id:
        cached = cache.get(opportunity_id, team.id, team.roster_version)
        requested = [
            TradeLegRequest(action=leg.action, player_id=leg.player.player_id)
            for leg in cached.legs
        ]
        return resolve_legs(store, team, requested), cached
    assert legs is not None  # guaranteed by the request validator
    validate_leg_shape(legs)
    return resolve_legs(store, team, legs), None


def simulate(store: Store, request: SimulateRequest) -> SimulateResponse:
    team = team_service.require_team(store, request.team_id)
    _check_version(team, request.roster_version)
    cache = get_opportunity_cache()

    payload = {
        "team_id": str(team.id),
        "roster_version": team.roster_version,
        "opportunity_id": request.opportunity_id,
        "legs": [leg.model_dump(mode="json") for leg in (request.legs or [])],
    }

    with agent_run(AgentName.TRADER, payload) as meta:
        resolved, _ = _legs_from_source(
            store, team, request.opportunity_id, request.legs, cache
        )
        impact = compute_impact(store, team, resolved)

    # A simulate that returns valid: false is still HTTP 200 -- an invalid
    # what-if is a successful simulation of an invalid trade, and the UI needs
    # the violations to explain the disabled Execute button (api.md 5.10).
    return SimulateResponse(
        impact=impact,
        legs=[leg.model for leg in resolved],
        agent_meta=meta[0],
    )


# --------------------------------------------------------------------------
# Execute
# --------------------------------------------------------------------------


def execute(store: Store, request: ExecuteRequest, initiated_by: str) -> ExecuteResponse:
    cache = get_opportunity_cache()
    request_hash = snapshot_hash(request.model_dump(mode="json", exclude={"idempotency_key"}))

    # Idempotency replay happens before any state check so a retried request
    # returns the original response rather than a STALE_ROSTER_VERSION.
    existing = store.get_idempotency(request.idempotency_key)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise conflict(
                ErrorCode.IDEMPOTENCY_KEY_REUSED,
                "This idempotency key was already used with a different request body",
                idempotency_key=str(request.idempotency_key),
            )
        return ExecuteResponse.model_validate(existing.response)

    with store.lock:  # stands in for the database transaction
        team = team_service.require_team(store, request.team_id)
        _check_version(team, request.roster_version)

        payload = {
            "team_id": str(team.id),
            "roster_version": team.roster_version,
            "opportunity_id": request.opportunity_id,
            "legs": [leg.model_dump(mode="json") for leg in (request.legs or [])],
        }

        with agent_run(AgentName.TRADER, payload) as meta:
            resolved, opportunity = _legs_from_source(
                store, team, request.opportunity_id, request.legs, cache
            )
            impact = compute_impact(store, team, resolved)

        if not impact.valid:
            blocker = next(
                v
                for v in impact.violations
                if v.severity is Severity.HIGH
            )
            # Hard violation codes double as 409 error codes, so the frontend
            # renders the same message component either way (api.md 6.2).
            code = (
                ErrorCode(blocker.code)
                if blocker.code in {c.value for c in HARD_VIOLATION_CODES}
                else ErrorCode.EXECUTION_FAILED
            )
            raise conflict(code, blocker.message, **blocker.details)

        metrics_before = impact.current_metrics
        version_before = team.roster_version

        try:
            acquired, released = _apply(store, team, resolved)
        except AppError:
            raise
        except Exception as exc:  # pragma: no cover - defensive rollback path
            _record_failure(store, team, request, initiated_by, str(exc))
            raise AppError(
                ErrorCode.EXECUTION_FAILED,
                "Trade could not be applied; no changes were committed",
                500,
                {"reason": str(exc)},
            ) from exc

        version_after = store.bump_roster_version(team.id)
        metrics_after = team_service.metrics_from_entries(team, store.current_roster(team.id))
        now = utcnow()

        trade = TradeRecord(
            trade_id=uuid4(),
            team_id=team.id,
            status=TradeStatus.EXECUTED,
            initiated_by=initiated_by,
            source_opportunity_id=request.opportunity_id,
            legs=[leg.model for leg in resolved],
            projected_cost_delta=impact.projected_cost_delta,
            projected_value_delta=impact.projected_value_delta,
            metrics_before=metrics_before,
            metrics_after=metrics_after,
            roster_version_before=version_before,
            roster_version_after=version_after,
            rationale_snapshot=(
                opportunity.model_dump(mode="json") if opportunity is not None else {}
            ),
            agent_meta=meta[0],
            created_at=now,
            executed_at=now,
        )

        store.add_trade(
            TradeRecordRow(
                id=trade.trade_id,
                team_id=team.id,
                status=TradeStatus.EXECUTED,
                initiated_by=initiated_by,
                source_opportunity_id=request.opportunity_id,
                payload=trade.model_dump(mode="json"),
                executed_at=now,
            )
        )

        # Every cached opportunity for this team was computed against the old
        # roster, so its impact block is now wrong.
        invalidated = cache.invalidate_team(team.id)

        response = ExecuteResponse(
            trade=trade,
            metrics_after=metrics_after,
            roster_version_after=version_after,
            applied_changes=AppliedChanges(acquired=acquired, released=released),
            invalidated_opportunity_ids=invalidated,
            executed_at=now,
        )

        store.save_idempotency(
            request.idempotency_key, request_hash, response.model_dump(mode="json")
        )
        return response


def _apply(store: Store, team: TeamRecord, legs: list[ResolvedLeg]):
    acquired = []
    released = []
    for leg in legs:
        if leg.action.is_outgoing and leg.entry is not None:
            store.close_roster_entry(leg.entry)
            released.append(leg.model.player)
        elif leg.action.is_incoming:
            store.add_roster_entry(
                team_id=team.id,
                player_id=leg.player_id,
                position=leg.model.player.position,
                cost=leg.cost,
                value_score=leg.value_score,
            )
            if leg.listing_id is not None:
                listing = store.get_listing(leg.listing_id)
                if listing is not None:
                    listing.available = False
            # The outgoing player becomes available on the market at the salary
            # they were carrying -- D9 means the counterparty's books are not
            # updated, listings are simply consumed and created.
            acquired.append(leg.model.player)
    return acquired, released


def _record_failure(
    store: Store, team: TeamRecord, request: ExecuteRequest, initiated_by: str, reason: str
) -> None:
    store.add_trade(
        TradeRecordRow(
            id=uuid4(),
            team_id=team.id,
            status=TradeStatus.FAILED,
            initiated_by=initiated_by,
            source_opportunity_id=request.opportunity_id,
            payload={"reason": reason},
        )
    )


def trade_to_model(row: TradeRecordRow) -> TradeRecord | dict[str, Any]:
    if row.status is TradeStatus.EXECUTED:
        return TradeRecord.model_validate(row.payload)
    return row.payload
