"""Agents for the Soccer GM Trade Assistant.

Three ReAct agents, one per api.md agent endpoint. Each is a system prompt, a
tool set, and a terminal tool whose arguments are the agent's output contract.

    from src.agents import gap_finder, opportunity_finder, trader

    run = gap_finder.analyze(store, request)          # api.md 5.8
    run = opportunity_finder.find(store, request)     # api.md 5.9
    run = trader.assess(store, simulate_request)      # api.md 5.10

Each returns an AgentRun: the contract object on `.output`, the ReAct trace on
`.steps`, and `.to_agent_meta()` for the api.md section 3.14 block. See
README.md for the calling contract and the fallback rule.
"""

from . import gap_finder, opportunity_finder, trader
from .core import (
    AgentError,
    AgentFailed,
    AgentRun,
    AgentUnavailable,
    get_agent_settings,
    is_available,
)

__all__ = [
    "AgentError",
    "AgentFailed",
    "AgentRun",
    "AgentUnavailable",
    "gap_finder",
    "get_agent_settings",
    "is_available",
    "opportunity_finder",
    "trader",
]
