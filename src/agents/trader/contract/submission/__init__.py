"""What the MODEL is trusted to author.

The Trader agent does not move players. Execution is a transaction with an
optimistic lock and a human confirmation gate (api.md 5.11), and none of that
belongs to a language model. What the agent owns is the judgement a GM wants
before clicking Execute: is this trade wise, what does it cost, what breaks.
"""

from .leg_note import LegNote
from .trader_submission import TraderSubmission

__all__ = [
    "LegNote",
    "TraderSubmission",
]
