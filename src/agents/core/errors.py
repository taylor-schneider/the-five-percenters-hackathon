"""Agent failure modes.

The caller (the API) needs exactly one decision out of these: can I still
serve a response? AgentUnavailable and AgentFailed both mean "fall back to the
deterministic service and report mode=heuristic". Nothing here should ever
reach the client as a 500 -- an agent that cannot run is a degraded feature,
not a broken endpoint.
"""

from __future__ import annotations


class AgentError(Exception):
    """Base for every agent-side failure."""


class AgentUnavailable(AgentError):
    """No credentials, SDK missing, or the kill switch is off.

    Raised before any network call, so it is cheap and deterministic.
    """


class AgentFailed(AgentError):
    """The loop ran but produced nothing usable.

    Carries the partial trace so the failure is still explainable.
    """

    def __init__(self, message: str, *, trace: object | None = None) -> None:
        super().__init__(message)
        self.trace = trace


class AgentIterationLimit(AgentFailed):
    """Hit max_iterations without the terminal tool being called."""


class AgentOutputInvalid(AgentFailed):
    """The terminal tool was called with arguments that failed validation more
    times than we are willing to retry."""


class ToolExecutionError(AgentError):
    """A tool handler failed. Surfaced to the model as an is_error tool_result
    rather than aborting the run -- a bad argument is something the model can
    correct, and usually does on the next turn."""
