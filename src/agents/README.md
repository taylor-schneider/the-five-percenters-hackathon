# Agents

Three ReAct agents, one per agent endpoint in [api.md](../../api.md). No framework:
a system prompt, a tool set, and a loop you can read in one sitting
([`core/loop.py`](core/loop.py)).

This document is the calling contract. If you are wiring up the FastAPI layer,
sections 1–4 are all you need; the rest explains why the pieces are shaped the
way they are.

---

## 1) Calling an agent

Each agent exposes one function. It takes the store and the api.md request object
the endpoint already parsed, and returns an `AgentRun`.

```python
from src.agents import gap_finder, opportunity_finder, trader
from src.agents import AgentError, is_available

run = gap_finder.analyze(store, request)            # api.md 5.8
run = opportunity_finder.find(store, request)       # api.md 5.9
run = trader.assess(store, simulate_request)        # api.md 5.10
```

`AgentRun` carries:

| Attribute | What it is |
|---|---|
| `.output` | The contract object — `GapFinderAnalysis`, `OpportunityPlan`, `TradeAssessment` |
| `.to_agent_meta()` | The api.md §3.14 `AgentMeta`, with `mode="llm"`, the model id, latency and input hash |
| `.steps` | The ReAct trace — thought, tool, arguments, observation, per-step latency |
| `.reasoning_steps()` | That trace as display lines, for §5.13 and `Opportunity.reasoning_steps` |
| `.usage` | Token counts for the whole run |
| `.iterations` | Model turns used |

Every `.output` has a `to_api_response(...)` that narrows it to the frozen api.md
response model, so the endpoint body is two lines:

```python
@router.post("/agents/gap-finder/analyze", response_model=GapFinderResponse)
def analyze(request: GapFinderRequest, store: Store = Depends(get_store)):
    run = gap_finder.analyze(store, request)
    return run.output.to_api_response(run.to_agent_meta())
```

---

## 2) The fallback rule

Agents are an enhancement, never a dependency. Two exceptions mean the same thing
to you:

- `AgentUnavailable` — no credentials, SDK not installed, or `GM_AGENT_ENABLED=false`.
  Raised before any network call.
- `AgentFailed` (and its subclasses `AgentIterationLimit`, `AgentOutputInvalid`) —
  the loop ran and produced nothing usable.

Both mean: **fall back to the deterministic service and report `mode="heuristic"`.**

```python
try:
    run = gap_finder.analyze(store, request)
    response = run.output.to_api_response(run.to_agent_meta())
except AgentError:
    logger.warning("gap finder fell back to heuristics", exc_info=True)
    response = gap_finder_service.analyze(store, request)   # mode=heuristic
```

`is_available()` answers cheaply and without a network call, if you want to skip
the try entirely — e.g. to decide what `GET /api/v1/version` should advertise.
It errs towards `False`: a false negative costs a heuristic response, a false
positive costs a failed request in front of the demo.

Structural errors are *not* agent errors. `trader.assess` runs
`trader_service.simulate` first, so an unknown player, an expired opportunity or
a stale roster version raises the normal `AppError` and becomes the 404/409/410
api.md specifies — before a single token is spent.

---

## 3) What the model authors, and what it cannot

This is the load-bearing design decision. The model chooses **which** positions,
players and trades matter, and writes the prose. Every number attached to that
choice is computed afterwards by the same services the heuristic path uses.

| Authored by the model | Computed server-side, model cannot influence |
|---|---|
| Which positions/players to flag | `problem_score`, `health_status`, `severity`, league averages |
| Which trades to propose | `cost_delta`, `value_delta`, `TradeImpact`, every violation |
| `commentary`, `narrative`, `reasons`, `risks`, `headline` | `opportunity_score` and the ranking |
| Per-opportunity `confidence` | The appearance-derived half of the final confidence |
| The trade verdict | Whether the trade is legal at all |

Concretely, in `gap_finder`: the model submits `{position: "CB", commentary,
reasons}` and nothing else. `problem_score` comes from
`services/scoring.py`. A flagged player whose `player_id` is not actually on the
roster is **dropped**, not scored. In `opportunity_finder`: every submitted trade
is re-priced through `trader_service.resolve_legs` + `compute_impact`, and one
that fails or breaches a constraint moves to `considered_and_rejected` instead of
reaching the GM. In `trader`: a `proceed` verdict over a hard violation is
rewritten to `do_not_proceed` — a recommendation next to a disabled Execute
button is worse than no recommendation.

Net effect: a hallucination costs you a missing finding, never a wrong euro.

---

## 4) Caller responsibilities

Things the agents deliberately do **not** do:

1. **`roster_version` checks.** `opportunity_finder.find` trusts the store it is
   handed. Check staleness first (`409 STALE_ROSTER_VERSION`) — burning a model
   call to discover the dashboard is stale is the wrong order.
2. **Persisting insights.** `GapFinderRequest.persist_insights` is yours. The
   agent returns findings; writing `agent_insights` rows is a repository concern.
   `commentary` is the obvious thing to put in `InsightRecord.details`.
3. **Executing trades.** `trader.assess` advises. `trader_service.execute` still
   owns the transaction, the optimistic lock and the `user_confirmation` gate.
   Freeze `TradeAssessment` (or the source `Opportunity`) into
   `TradeRecord.rationale_snapshot` for §5.13.
4. **Opportunity caching** is the one exception — `opportunity_finder.find`
   registers its results in the TTL cache by default, because an
   `opportunity_id` that `execute` cannot resolve is useless. Pass `cache=False`
   for evals and dry runs.

---

## 5) The missing discussion field

You asked whether the data model omits a place for the agent's commentary. It
does, and it is the main thing worth changing in api.md.

Today a `FlaggedPosition` carries `reasons: string[]` — clause-length evidence
bullets. There is nowhere to put the two-to-four sentences that explain what the
numbers *mean for this squad*, which is precisely the part of an agent's output a
GM reads. Same for `Opportunity` (`reasoning_summary` is one line),
`SimulateResponse` (no prose at all), and `RosterRow`.

The agent contracts already carry it, as a superset of the api.md models:

| Contract object | Adds |
|---|---|
| `GapFinderAnalysis` | `narrative`, `priorities[]`, `confidence`; `commentary` on every position, player and coverage warning |
| `OpportunityPlan` | `narrative`, `confidence`, `considered_and_rejected[]`; `commentary` on every opportunity |
| `TradeAssessment` | `verdict`, `headline`, `narrative`, `alternatives[]`, `confidence`; `commentary` per leg |

`to_api_response()` **drops all of it** to fit the frozen shape. Two options:

- **Serve the contract object directly** from the agent endpoints. Fastest path,
  and the one worth demoing — the commentary is the feature.
- **Amend api.md** (the durable fix). The minimal delta:
  - add `commentary: string | null` to `FlaggedPosition`, `FlaggedPlayer`,
    `CoverageWarning`, `Opportunity` and `TradeLeg`;
  - add `narrative: string`, `priorities: string[]` and `confidence: float` to
    `GapFinderResponse`;
  - add `narrative`, `confidence` and `considered_and_rejected[]` to
    `OpportunityFinderResponse`;
  - add `verdict`, `headline`, `narrative`, `risks[]`, `alternatives[]` and
    `confidence` to `SimulateResponse`.

  All additive and nullable, so a heuristic run simply leaves them null — which
  is also how the UI can tell the two modes apart without reading `agent_meta`.

---

## 6) Layout

```text
src/agents/
  core/                 # the ReAct machinery, agent-agnostic
    config.py           # GM_AGENT_* settings: model, effort, ceilings
    client.py           # Anthropic client + the availability check
    tools.py            # Tool = Pydantic args model + handler; ToolBox
    loop.py             # the loop itself
    trace.py            # ReActStep, AgentRun, AgentMeta construction
    errors.py           # AgentUnavailable / AgentFailed
  data/                 # everything the tools read, shared by all three agents
    context.py          # AgentDeps: team, league distribution, minimums
    tools.py            # the tool library
    metrics.py          # deterministic assembly of scores the model may cite
  gap_finder/           # contract.py, prompts.py, agent.py
  opportunity_finder/
  trader/
```

`data/context.py` is the single coupling point to `src/api`. If the repository
layer moves to SQLAlchemy, that file changes and nothing else does.

### Tools

| Tool | Gap Finder | Opportunity Finder | Trader |
|---|:--:|:--:|:--:|
| `get_team_overview` | ✅ | ✅ | ✅ |
| `get_roster` | ✅ | ✅ | ✅ |
| `get_position_benchmarks` | ✅ | ✅ | ✅ |
| `inspect_player` | ✅ | ✅ | ✅ |
| `search_market` | — | ✅ | ✅ |
| `simulate_trade` | — | ✅ | ✅ |
| terminal | `submit_analysis` | `submit_opportunities` | `submit_assessment` |

Gap Finder has no market access on purpose: it diagnoses, it does not shop. That
separation is what keeps the two endpoints from converging into one.

**The terminal tool is how a run ends.** Its argument model *is* the agent's
output contract, so the output is validated by the same Pydantic model that
generated its schema — no "parse the final message" step, and a malformed
submission comes back as a tool error the model fixes on the next turn.

---

## 7) Configuration

All `GM_AGENT_`-prefixed, read from the environment or `.env`:

| Setting | Default | Notes |
|---|---|---|
| `GM_AGENT_ENABLED` | `true` | `false` makes every agent raise `AgentUnavailable` — the kill switch |
| `GM_AGENT_MODEL` | `claude-opus-5` | One model for all three agents |
| `GM_AGENT_EFFORT` | `high` | `low` / `medium` / `high` / `xhigh` / `max` |
| `GM_AGENT_MAX_ITERATIONS` | `12` | Hard ceiling on model turns |
| `GM_AGENT_MAX_TOKENS` | `16000` | Per turn |
| `GM_AGENT_THINKING_DISPLAY` | `summarized` | Gives the trace readable thoughts; `omitted` is cheaper to render |
| `GM_AGENT_VERSION` | `agents-1.0.0` | Surfaces as `AgentMeta.version` |

Credentials come from `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, or an
`ant auth login` profile — resolved by the SDK, never read here.

A typical run is 4–8 model turns. The system prompt and tool list are byte-stable
per agent and carry one cache breakpoint, so the prefix is a cache read from the
second call onwards; keep them that way when editing prompts.

---

## 8) Blockers found in the API package

These are on the API side, not in this package, and two of them stop an agent
demo dead:

1. **Every seeded team is roughly 2× over its budget cap** (`Riverside FC`:
   €88.2M against a €50M cap). Under D10's hard cap, `compute_impact` marks
   essentially *every* trade `BUDGET_CAP_EXCEEDED`, so the Opportunity Finder
   returns an empty list and the Trader always says `do_not_proceed`. Fix in
   `repositories/seed.py`: either scale salaries down by ~2.3× or raise the
   seeded caps to match the rosters.
2. **`opportunity_finder_service.find` raises `AttributeError`** —
   `_response_legs` reads `candidate._resolved_models`, which `_Candidate`
   (with `__slots__`) never sets. The heuristic fallback path for §5.9 is
   currently broken; the candidate needs to keep its resolved leg models.
3. **`constraints.budget_cap` is ignored during validation.** api.md says it
   overrides the stored cap for what-if analysis, but `compute_impact` reads
   `team.budget_cap` directly. The agents' read tools honour the override, so a
   what-if run currently reports headroom against one cap and validates against
   another.

---

## 9) Testing without a key

The loop takes its client from `core.loop.get_client()`, so a scripted fake
exercises tool dispatch, the retry-on-invalid-submission path and the
deterministic join with no network:

```python
from src.agents.core import loop as loop_mod
loop_mod.get_client = lambda: FakeClient(script)   # replays assistant turns
```

A fake needs only `.messages.create(**kwargs)` returning an object with
`.content` (blocks with `.type`), `.stop_reason`, `.stop_details` and `.usage`.
