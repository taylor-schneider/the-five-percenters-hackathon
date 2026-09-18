"""Shared ReAct machinery: settings, client, tools, loop, trace."""

from .client import get_client, is_available, reset_client_cache
from .config import AgentSettings, get_agent_settings
from .errors import (
    AgentError,
    AgentFailed,
    AgentIterationLimit,
    AgentOutputInvalid,
    AgentUnavailable,
    ToolExecutionError,
)
from .loop import ReActAgent
from .tools import NoArgs, Tool, ToolBox
from .trace import AgentRun, ReActStep, TokenUsage, snapshot_hash

__all__ = [
    "AgentError",
    "AgentFailed",
    "AgentIterationLimit",
    "AgentOutputInvalid",
    "AgentRun",
    "AgentSettings",
    "AgentUnavailable",
    "NoArgs",
    "ReActAgent",
    "ReActStep",
    "TokenUsage",
    "Tool",
    "ToolBox",
    "ToolExecutionError",
    "get_agent_settings",
    "get_client",
    "is_available",
    "reset_client_cache",
    "snapshot_hash",
]
