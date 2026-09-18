"""The ReAct loop, written out rather than delegated to a framework.

Reason -> act -> observe, until the agent calls its terminal tool. Everything
the loop needs to be safe for a hackathon demo is in one file you can read in a
sitting: an iteration ceiling, a tool-error ceiling, a nudge for a model that
forgets to submit, and a trace of every step.

The terminal-tool pattern is the important design choice. The agent finishes by
CALLING a tool whose arguments are the agent's output contract, so the output is
validated by the same Pydantic model that generated its schema. There is no
"parse the final message" step, and a malformed submission comes back as a tool
error the model can fix on the next turn instead of as a 500.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ValidationError

from ...api.models.enums import AgentName
from .client import get_client
from .config import AgentSettings, get_agent_settings
from .errors import (
    AgentFailed,
    AgentIterationLimit,
    AgentOutputInvalid,
    ToolExecutionError,
)
from .tools import ToolBox, observation_text
from .trace import AgentRun, ReActStep, TokenUsage, snapshot_hash

_NUDGE = (
    "You have not submitted yet. Call the {terminal} tool now with your conclusions, "
    "based on the evidence you have already gathered. Do not ask questions -- there is "
    "no human in this loop."
)


class ReActAgent:
    """One agent: a system prompt, a tool set, and the loop that drives them."""

    def __init__(
        self,
        *,
        agent_name: AgentName,
        system_prompt: str,
        toolbox: ToolBox,
        settings: AgentSettings | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.system_prompt = system_prompt
        self.toolbox = toolbox
        self.settings = settings or get_agent_settings()

    # ------------------------------------------------------------------ run

    def run(self, *, task: str, deps: Any, input_payload: dict[str, Any]) -> AgentRun[BaseModel]:
        """Drive the loop until the terminal tool validates.

        `input_payload` is hashed into AgentMeta.input_snapshot_hash, so it must
        describe the state the agent reasoned over (team, roster_version,
        constraints) rather than the prompt text.
        """
        settings = self.settings
        client = get_client()
        started = time.perf_counter()

        messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
        steps: list[ReActStep] = []
        usage = TokenUsage()
        tool_errors = 0
        nudges = 0

        for iteration in range(1, settings.max_iterations + 1):
            response = client.messages.create(
                model=settings.model,
                max_tokens=settings.max_tokens,
                # The system prompt and tool list are byte-stable across every
                # call for this agent, so one breakpoint here caches the whole
                # prefix (tools render before system).
                system=[
                    {
                        "type": "text",
                        "text": self.system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                thinking={"type": "adaptive", "display": settings.thinking_display},
                output_config={"effort": settings.effort},
                tools=self.toolbox.to_api_schemas(),
                messages=messages,
            )
            usage.add(response.usage)

            if response.stop_reason == "refusal":
                raise AgentFailed(
                    f"model declined the request ({_refusal_category(response)})",
                    trace=steps,
                )
            if response.stop_reason == "max_tokens":
                raise AgentFailed("model hit max_tokens before submitting", trace=steps)
            if response.stop_reason == "pause_turn":
                # No server tools are in play today, but a paused turn is
                # resumed by echoing it back, not treated as an answer.
                messages.append({"role": "assistant", "content": response.content})
                continue

            thought = _thinking_text(response) or _text(response)
            tool_uses = [b for b in response.content if b.type == "tool_use"]

            if not tool_uses:
                # The model answered in prose instead of submitting. Prose is
                # not a contract, so we ask once or twice and then fail loudly.
                steps.append(ReActStep(index=len(steps) + 1, thought=thought))
                nudges += 1
                if nudges > settings.max_nudges:
                    raise AgentFailed(
                        "model finished without calling its terminal tool", trace=steps
                    )
                messages.append({"role": "assistant", "content": response.content})
                messages.append(
                    {
                        "role": "user",
                        "content": _NUDGE.format(terminal=self.toolbox.terminal.name),
                    }
                )
                continue

            messages.append({"role": "assistant", "content": response.content})
            results: list[dict[str, Any]] = []

            for block in tool_uses:
                step = ReActStep(
                    index=len(steps) + 1,
                    thought=thought,
                    tool_name=block.name,
                    tool_input=dict(block.input or {}),
                )
                thought = None  # a turn's thinking belongs to its first call only
                call_started = time.perf_counter()
                tool = self.toolbox.get(block.name)

                if tool is None:
                    tool_errors += 1
                    step.is_error = True
                    step.observation = f"unknown tool: {block.name}"
                    steps.append(step)
                    results.append(_error_result(block.id, step.observation))
                    continue

                if tool.terminal:
                    try:
                        output = tool.args_model.model_validate(block.input or {})
                    except ValidationError as exc:
                        tool_errors += 1
                        step.is_error = True
                        step.observation = _validation_feedback(exc)
                        step.latency_ms = _ms(call_started)
                        steps.append(step)
                        if tool_errors > settings.max_tool_errors:
                            raise AgentOutputInvalid(
                                f"terminal tool arguments never validated: {step.observation}",
                                trace=steps,
                            )
                        results.append(_error_result(block.id, step.observation))
                        continue

                    step.observation = "submitted"
                    step.latency_ms = _ms(call_started)
                    steps.append(step)
                    return AgentRun(
                        agent_name=self.agent_name,
                        output=output,
                        model=settings.model,
                        version=settings.version,
                        input_snapshot_hash=snapshot_hash(input_payload),
                        steps=steps,
                        usage=usage,
                        latency_ms=_ms(started),
                        iterations=iteration,
                    )

                try:
                    result = tool.invoke(block.input, deps)
                    step.observation = observation_text(result, settings.observation_char_limit)
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": step.observation,
                        }
                    )
                except ToolExecutionError as exc:
                    tool_errors += 1
                    step.is_error = True
                    step.observation = str(exc)
                    results.append(_error_result(block.id, str(exc)))
                except Exception as exc:  # a tool bug must not kill the request
                    tool_errors += 1
                    step.is_error = True
                    step.observation = f"{type(exc).__name__}: {exc}"
                    results.append(_error_result(block.id, step.observation))
                finally:
                    step.latency_ms = _ms(call_started)
                    steps.append(step)

            if tool_errors > settings.max_tool_errors:
                raise AgentFailed(f"giving up after {tool_errors} tool failures", trace=steps)

            # Every result from one assistant turn goes back in ONE user
            # message. Splitting them teaches the model to stop calling tools in
            # parallel, which doubles the turn count on the next run.
            messages.append({"role": "user", "content": results})

        raise AgentIterationLimit(
            f"no submission after {settings.max_iterations} turns", trace=steps
        )


# --------------------------------------------------------------------------


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _thinking_text(response: Any) -> str | None:
    parts = [b.thinking for b in response.content if b.type == "thinking" and b.thinking]
    return " ".join(p.strip() for p in parts) or None


def _text(response: Any) -> str | None:
    parts = [b.text for b in response.content if b.type == "text" and b.text]
    return " ".join(p.strip() for p in parts) or None


def _refusal_category(response: Any) -> str:
    details = getattr(response, "stop_details", None)
    return getattr(details, "category", None) or "unspecified"


def _error_result(tool_use_id: str, message: str) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": message,
        "is_error": True,
    }


def _validation_feedback(exc: ValidationError) -> str:
    """Validation errors are prompts, not logs. The model reads these and
    retries, so they name the field and say what was wrong."""
    lines = []
    for error in exc.errors()[:8]:
        location = ".".join(str(p) for p in error["loc"]) or "<root>"
        lines.append(f"{location}: {error['msg']}")
    return "submission rejected -- fix these and call the tool again: " + "; ".join(lines)
