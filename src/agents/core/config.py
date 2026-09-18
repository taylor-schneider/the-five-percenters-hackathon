"""Agent runtime settings.

Separate from src/api/core/config.py on purpose: the API owns business rules
(caps, minimums, scoring weights), the agent package owns model wiring. An
API deployment that never runs an agent does not need an Anthropic key, and a
harness that runs an agent outside FastAPI does not need the API's settings.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GM_AGENT_", env_file=".env", extra="ignore")

    enabled: bool = Field(
        default=True,
        description="Master switch. False makes every agent raise AgentUnavailable, "
        "so the caller falls back to its deterministic path without touching the network.",
    )
    model: str = Field(
        default="claude-opus-5",
        description="Model id for all three agents. One knob, because a demo that "
        "runs three models is a demo with three failure modes.",
    )
    max_tokens: int = 16_000
    effort: str = Field(
        default="high",
        description="output_config.effort: low | medium | high | xhigh | max.",
    )
    thinking_display: str = Field(
        default="summarized",
        description="'summarized' gives us readable thoughts for the ReAct trace. "
        "'omitted' is the API default and leaves the trace with tool calls only.",
    )
    max_iterations: int = Field(
        default=12,
        description="Hard ceiling on model turns. A ReAct loop with no ceiling is an "
        "unbounded bill.",
    )
    max_tool_errors: int = Field(
        default=4, description="Consecutive-ish tool failures tolerated before giving up."
    )
    max_nudges: int = Field(
        default=2,
        description="Times we may remind the model to call its terminal tool before "
        "declaring the run failed.",
    )
    request_timeout_seconds: float = 120.0
    observation_char_limit: int = Field(
        default=20_000,
        description="Truncation guard on a single tool observation, so one wide roster "
        "cannot crowd out the rest of the conversation.",
    )
    version: str = Field(
        default="agents-1.0.0",
        description="Reported as AgentMeta.version so a recommendation can be traced "
        "back to the prompt/tool set that produced it.",
    )

    @property
    def api_key(self) -> str | None:
        """Read at call time, not import time -- tests set this per-case.

        Unset does not always mean 'no credentials': the SDK also resolves
        ANTHROPIC_AUTH_TOKEN and an `ant auth login` profile. We only use this
        to decide whether to *try*, and a bare Anthropic() still resolves the
        rest.
        """
        return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()
