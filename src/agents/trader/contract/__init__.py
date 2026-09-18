"""Trader contract.

The Trader agent does not move players. Execution is a transaction with an
optimistic lock and a human confirmation gate (api.md 5.11), and none of that
belongs to a language model. What the agent owns is the judgement a GM wants
before clicking Execute: is this trade wise, what does it cost, what breaks.

`submission` is the model's output. `responses` is that judgement joined to the
authoritative TradeImpact from trader_service.simulate. `Verdict` is shared by
both, so it lives at the root of this package.
"""

from .responses import AssessedLeg, TradeAssessment
from .submission import LegNote, TraderSubmission
from .verdict import Verdict

__all__ = [
    "AssessedLeg",
    "LegNote",
    "TradeAssessment",
    "TraderSubmission",
    "Verdict",
]
