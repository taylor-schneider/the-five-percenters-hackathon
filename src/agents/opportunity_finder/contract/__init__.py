"""Opportunity Finder contract.

`submission` is what the model authors: which trades to put in front of the GM,
why, and what could go wrong. It carries no prices, no scores and no rankings --
every leg is re-priced through trader_service and every opportunity_score is
recomputed from api.md section 4 before anything reaches the API.

`responses` is what the agent returns: api.md section 5.9's response, plus
per-opportunity commentary and the trades the agent considered and rejected.
"""

from .responses import OpportunityFinding, OpportunityPlan, RejectedOpportunity
from .submission import OpportunityCall, OpportunityFinderSubmission, RejectedNote

__all__ = [
    "OpportunityCall",
    "OpportunityFinderSubmission",
    "OpportunityFinding",
    "OpportunityPlan",
    "RejectedNote",
    "RejectedOpportunity",
]
