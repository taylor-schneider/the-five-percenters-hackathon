"""What the agent returns.

api.md section 5.9's response, plus per-opportunity commentary and the trades
the agent considered and rejected.
"""

from .opportunity_finding import OpportunityFinding
from .opportunity_plan import OpportunityPlan
from .rejected_opportunity import RejectedOpportunity

__all__ = [
    "OpportunityFinding",
    "OpportunityPlan",
    "RejectedOpportunity",
]
