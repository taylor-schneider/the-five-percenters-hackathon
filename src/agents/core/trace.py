"""The ReAct trace: what the agent thought, called, and saw.

This is the explainability spine. api.md section 3.14 promises that every
agent response carries an AgentMeta with an input_snapshot_hash, and 5.13
promises a full reasoning trace for a committed trade. Both are built from
what this module records, so the trace is a product surface, not a debug log.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, TypeVar

from ...api.models.domain import AgentMeta
from ...api.models.enums import AgentMode, AgentName
from ...api.repositories.store import utcnow

OutputT = TypeVar("OutputT")


def snapshot_hash(payload: Any) -> str:
    """Stable hash of an agent's input.

    Identical to src/api/services/agent_runtime.snapshot_hash, and deliberately
    so: a heuristic run and an agent run over the same roster must produce the
    same hash, or the audit trail cannot compare them.
    """
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class ReActStep:
    """One turn of the loop: a thought, the tool it led to, and what came back."""

    index: int
    thought: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] = field(default_factory=dict)
    observation: str | None = None
    is_error: bool = False
    latency_ms: int = 0

    def as_line(self) -> str:
        """One human-readable line. These feed Opportunity.reasoning_steps and
        the trade reasoning endpoint, so they are written for a GM to read, not
        for a log aggregator."""
        if self.thought and not self.tool_name:
            return self.thought
        head = f"{self.tool_name}({_brief(self.tool_input)})"
        if self.is_error:
            return f"{head} -> failed: {self.observation}"
        if self.thought:
            return f"{self.thought} -> {head}"
        return head


@dataclass(slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    def add(self, usage: Any) -> None:
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0


@dataclass(slots=True)
class AgentRun(Generic[OutputT]):
    """Everything one agent invocation produced. This is what agents return."""

    agent_name: AgentName
    output: OutputT
    model: str
    version: str
    input_snapshot_hash: str
    steps: list[ReActStep] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    latency_ms: int = 0
    iterations: int = 0
    generated_at: datetime = field(default_factory=utcnow)

    def to_agent_meta(self) -> AgentMeta:
        """Build the api.md section 3.14 object. The API attaches this to its
        response verbatim -- mode is LLM here by construction, because a run
        that did not reach the model never produces an AgentRun."""
        return AgentMeta(
            agent_name=self.agent_name,
            mode=AgentMode.LLM,
            version=self.version,
            model=self.model,
            input_snapshot_hash=self.input_snapshot_hash,
            latency_ms=self.latency_ms,
            generated_at=self.generated_at,
        )

    def reasoning_steps(self) -> list[str]:
        """The trace as display lines, in order."""
        return [step.as_line() for step in self.steps if step.as_line()]

    def tool_calls(self) -> list[str]:
        return [s.tool_name for s in self.steps if s.tool_name]


def _brief(payload: dict[str, Any], limit: int = 120) -> str:
    if not payload:
        return ""
    text = ", ".join(f"{k}={_scalar(v)}" for k, v in payload.items())
    return text if len(text) <= limit else text[: limit - 1] + "..."


def _scalar(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return f"[{len(value)}]"
    if isinstance(value, dict):
        return "{...}"
    return str(value)
