"""One leg of a trade, persisted alongside its TradeRecordRow.

Deltas are stored as computed at execution time and signed from the acting
team's perspective (D3), so a historic trade still renders correctly after
salaries or scores move on.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ..api.models.enums import TradeAction


@dataclass(slots=True)
class TradeItemRecord:
    trade_item_id: UUID
    trade_id: UUID
    action: TradeAction
    player_id: UUID
    cost_delta: int
    """The player's salary, signed by direction. Nothing else contributes (D1)."""
    value_delta: float
    """Raw score delta, NOT a team-average delta."""
    counterparty_team_id: UUID | None = None
    listing_id: UUID | None = None
    """Set on buy/swap_in only. Pins the listing the salary came from."""
