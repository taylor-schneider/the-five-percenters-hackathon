"""Opportunity Finder agent (api.md 5.9)."""

from .agent import TOOLS, build_agent, find
from .contract import (
    OpportunityCall,
    OpportunityFinderSubmission,
    OpportunityFinding,
    OpportunityPlan,
    RejectedOpportunity,
)

__all__ = [
    "TOOLS",
    "OpportunityCall",
    "OpportunityFinderSubmission",
    "OpportunityFinding",
    "OpportunityPlan",
    "RejectedOpportunity",
    "build_agent",
    "find",
]
