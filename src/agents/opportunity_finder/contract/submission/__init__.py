"""What the MODEL is trusted to author.

Which trades to put in front of the GM, why, and what could go wrong. These
models carry no prices, no scores and no rankings -- every leg is re-priced
through trader_service and every opportunity_score is recomputed from api.md
section 4 before anything reaches the API.
"""

from .opportunity_call import OpportunityCall
from .opportunity_finder_submission import OpportunityFinderSubmission
from .rejected_note import RejectedNote

__all__ = [
    "OpportunityCall",
    "OpportunityFinderSubmission",
    "RejectedNote",
]
