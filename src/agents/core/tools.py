"""Tool definitions for the ReAct loop.

A tool is a Pydantic argument model plus a handler. The model does three jobs:
it generates the JSON schema the API sees, it validates what the model sends
back, and it gives the handler typed arguments. Writing the schema by hand and
validating separately is how tool contracts drift.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from .errors import ToolExecutionError

#: A handler takes validated arguments plus the run's dependencies and returns
#: anything JSON-serialisable. Returning plain dicts (not Pydantic models) keeps
#: observations small and stops API response shapes leaking into prompts.
Handler = Callable[[Any, Any], Any]


class NoArgs(BaseModel):
    """Argument model for tools that take nothing.

    The API requires an object schema even for a no-argument tool, and some
    models will happily send `{"random_key": 1}` -- extra="forbid" turns that
    into a validation error the model can see and correct.
    """

    model_config = {"extra": "forbid"}


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Handler
    terminal: bool = False
    """A terminal tool ends the loop. Its arguments ARE the agent's output, so
    there is no separate 'parse the final message' step to get wrong."""

    def to_api_schema(self) -> dict[str, Any]:
        schema = self.args_model.model_json_schema()
        # Pydantic emits `title` on every field; it is noise in a prompt and
        # counts against the cached prefix.
        schema.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }

    def invoke(self, raw_input: Any, deps: Any) -> Any:
        try:
            args = self.args_model.model_validate(raw_input or {})
        except ValidationError as exc:
            raise ToolExecutionError(_validation_message(exc)) from exc
        return self.handler(args, deps)


class ToolBox:
    """The tool set for one agent. Order is fixed, because `tools` is the first
    thing in the cached prefix and reordering it invalidates the cache."""

    def __init__(self, tools: list[Tool]) -> None:
        terminals = [t for t in tools if t.terminal]
        if len(terminals) != 1:
            raise ValueError(
                f"an agent needs exactly one terminal tool, got {len(terminals)}"
            )
        self._tools = list(tools)
        self._by_name = {t.name: t for t in tools}
        if len(self._by_name) != len(tools):
            raise ValueError("duplicate tool name")
        self.terminal = terminals[0]

    def __iter__(self):
        return iter(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._by_name.get(name)

    def to_api_schemas(self) -> list[dict[str, Any]]:
        return [tool.to_api_schema() for tool in self._tools]

    def catalogue(self) -> str:
        """A one-line-per-tool summary for the system prompt. The schemas are
        already in the request; this is about when to reach for what."""
        return "\n".join(
            f"- {tool.name}: {tool.description.strip().splitlines()[0]}" for tool in self._tools
        )


def observation_text(result: Any, limit: int) -> str:
    """Render a handler's return value for the model.

    JSON, not prose: the model is reading data, and a stable serialisation
    makes the same roster produce the same tokens on every run.
    """
    if isinstance(result, str):
        text = result
    else:
        text = json.dumps(result, default=str, ensure_ascii=False, separators=(",", ":"))
    if len(text) > limit:
        return text[:limit] + f'... [truncated at {limit} chars -- narrow your filters]'
    return text


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors()[:6]:
        location = ".".join(str(p) for p in error["loc"]) or "<root>"
        parts.append(f"{location}: {error['msg']}")
    return "invalid arguments -- " + "; ".join(parts)
