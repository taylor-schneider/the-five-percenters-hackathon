"""What the agent returns.

The model's judgement joined to the authoritative TradeImpact from
trader_service.simulate.
"""

from .assessed_leg import AssessedLeg
from .trade_assessment import TradeAssessment

__all__ = [
    "AssessedLeg",
    "TradeAssessment",
]
