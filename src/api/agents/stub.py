"""Placeholder agents. No API calls, no key, no intelligence.

These exist so the frontend can build against real response shapes before the
agent branch merges. They are deliberately, visibly dumb:

* Gap Finder judges nothing and returns no flags.
* Opportunity Finder proposes the first few legal swaps it can find, with
  reasoning text that says outright that it is a stub.
* Trader approves anything the deterministic validator already accepted.

Every piece of generated prose is prefixed `[stub]` so a placeholder can never
be mistaken for agent output in a demo. If you find yourself wanting to make
these smarter, that work belongs in the real agents, not here -- a clever stub
is exactly the rules-engine-cosplaying-as-an-agent this seam exists to avoid.
"""

from __future__ import annotations

from ..models.enums import OpportunityType, TradeAction
from .base import (
    AgentBundle,
    GapFinderContext,
    GapFinderVerdict,
    OpportunityFinderContext,
    ProposedOpportunity,
    TradeReview,
    TraderContext,
)
from .toolbox import check_trade_legality

_STUB = "[stub] placeholder output -- the real agent has not been wired up yet."


class StubGapFinder:
    name = "stub-gap-finder"

    def analyze(self, ctx: GapFinderContext) -> GapFinderVerdict:
        # No judgements. An empty verdict is honest; invented flags are not.
        return GapFinderVerdict(positions=[], players=[], narrative=_STUB)


class StubOpportunityFinder:
    name = "stub-opportunity-finder"

    def find(self, ctx: OpportunityFinderContext) -> list[ProposedOpportunity]:
        from .toolbox import search_market

        store = ctx.store
        entries = store.current_roster(ctx.team_id)
        wanted = set(ctx.focus.positions) or {e.position for e in entries}

        proposals: list[ProposedOpportunity] = []
        limit = min(ctx.constraints.max_results, 5)

        for position in sorted(wanted, key=lambda p: p.value):
            if len(proposals) >= limit:
                break
            occupants = [e for e in entries if e.position == position and e.available]
            listings = search_market(
                store, position=position, exclude_team_id=ctx.team_id, limit=3
            )
            if not occupants or not listings:
                continue

            outgoing = occupants[0]
            incoming = listings[0]
            legs = [
                {"action": TradeAction.SWAP_OUT.value, "player_id": str(outgoing.player_id)},
                {
                    "action": TradeAction.SWAP_IN.value,
                    "player_id": incoming["player"]["player_id"],
                },
            ]
            # Only propose things that actually price and pass the hard rules --
            # a stub should not hand the UI a trade that cannot be executed.
            if not check_trade_legality(store, ctx.team_id, legs)["valid"]:
                continue

            proposals.append(
                ProposedOpportunity(
                    type=OpportunityType.SWAP,
                    legs=legs,
                    target_position=position,
                    confidence=0.0,
                    reasoning_summary=_STUB,
                    reasoning_steps=[
                        _STUB,
                        f"Swapped the first available {position.value} for the first "
                        f"market listing at that position. No analysis was performed.",
                    ],
                    risks=["Stub output: this proposal has no reasoning behind it."],
                )
            )
        return proposals


class StubTrader:
    name = "stub-trader"

    def review(self, ctx: TraderContext) -> TradeReview:
        return TradeReview(
            approved=True,
            summary=_STUB,
            concerns=["Stub review: only the deterministic rule checks were applied."],
            confidence=0.0,
        )


def build_bundle() -> AgentBundle:
    return AgentBundle(
        gap_finder=StubGapFinder(),
        opportunity_finder=StubOpportunityFinder(),
        trader=StubTrader(),
        impl="stub",
        model=None,  # nothing was called, so nothing to name
    )
