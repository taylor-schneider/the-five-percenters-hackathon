"""api.md Opportunity plus the agent's discussion of it."""

from __future__ import annotations

from .....api.models.domain import Opportunity


class OpportunityFinding(Opportunity):
    """api.md Opportunity plus the agent's discussion of it."""

    commentary: str
