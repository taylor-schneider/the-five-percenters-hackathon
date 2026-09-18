"""Storage records -- one module per record.

These are deliberately distinct from the Pydantic API models in
models/domain.py, so a storage change cannot silently reshape a response.
"""

from ._time import utcnow
from .agent_insight import InsightRecord
from .idempotency import IdempotencyRecord
from .market_listing import MarketListingRecord
from .player import PlayerRecord
from .position import PositionRecord
from .roster_entry import RosterEntryRecord
from .team import TeamRecord
from .trade import TradeRecordRow

__all__ = [
    "IdempotencyRecord",
    "InsightRecord",
    "MarketListingRecord",
    "PlayerRecord",
    "PositionRecord",
    "RosterEntryRecord",
    "TeamRecord",
    "TradeRecordRow",
    "utcnow",
]
