"""A trade the agent considered and ruled out."""

from __future__ import annotations

from .....api.models.domain import ApiModel


class RejectedOpportunity(ApiModel):
    summary: str
    why_rejected: str
