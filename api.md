# Soccer GM Trade Assistant — API Specification

**Status:** v1, frozen for hackathon implementation
**Owner:** taylor.schneider@us.gt.com
**Last updated:** 2026-09-18
**Companion doc:** [HACKATHON_DESIGN.md](HACKATHON_DESIGN.md)

This document is the contract between the React frontend, the FastAPI backend, and the three
agents (Gap Finder, Opportunity Finder, Trader). Section 3 is the canonical data model — every
endpoint in section 5 is expressed in terms of those objects and nothing is re-declared inline.

---

## 0) Decisions locked for v1

These were open in the design doc or ambiguous in the earlier API draft. They are settled here
so implementation can start. Each is reversible, but flipping one changes payload shapes, so
raise it before coding rather than during.

| # | Decision | Resolution | Why |
|---|---|---|---|
| D1 | Money model | **Salary is the only money concept.** Every player carries exactly one number, `cost` — their per-season salary, integer whole euros. A team's cost is the sum of its roster's salaries. **A trade's cost is the total salary coming on minus the total salary going off.** There is no transfer fee, no acquisition price, no second money field anywhere in the API. | The earlier draft folded a one-time `transfer_cost` into `post_trade_team_cost`, which is a recurring total — that math does not close. One number matches the original roster table (`Team, Player, Cost, Value`) and makes `post_trade_team_cost = team_cost + projected_cost_delta` exactly true by construction. |
| D2 | Leg pricing | **Clients never send prices.** A trade leg is `{action, player_id}`. The server derives `cost_delta` and `value_delta` from authoritative roster/market data and returns them read-only. | Stops a client quoting a stale or fabricated price, and removes sign ambiguity at the source. |
| D3 | Sign convention | All `*_delta` fields are **signed from the acting team's perspective**. Negative `cost_delta` = the team spends less. Positive `value_delta` = the team gets better. | Was implicit and inconsistent between the two example payloads in the earlier draft. |
| D4 | Value scale | `value_score` is a float **0.0–100.0**, one decimal. `team_score` is the unweighted mean of current roster `value_score`. | Matches "Team score = average player value". Name unified to `team_score` everywhere — `avg_value_score` is retired. |
| D5 | Position taxonomy | Two levels. `position` is a specific slot (10 values; benchmarks computed at this level). `position_group` is GK/DEF/MID/FWD (squad minimums enforced at this level). | Benchmarks need "league average for the same position" precision; roster-legality rules need coarse buckets. The earlier draft used the two interchangeably. |
| D6 | Status for rule violations | **409** for state/rule violations (budget cap, squad minimums, stale roster, idempotency conflict). **422 is reserved exclusively for FastAPI's own payload validation.** | FastAPI emits 422 automatically on schema failure. Overloading it makes "your JSON is malformed" indistinguishable from "this trade breaks the salary cap". |
| D7 | Concurrency | Every team carries a monotonic integer `roster_version`. `simulate` and `execute` echo the version they were computed against. Mismatch → `409 STALE_ROSTER_VERSION`. | The design requires an optimistic lock; it was absent from the API surface entirely. |
| D8 | Stack | **Python 3.11 + FastAPI + Pydantic v2 + PostgreSQL.** | `HACKATHON_DESIGN.md` §2.13 still specifies Node + Fastify. That section is stale and should be updated to match this doc. |
| D9 | Swap balance | A `swap` is **not** required to balance across both teams in v1. The counterparty's books are not updated; market listings are simply consumed. | Multi-team negotiation is explicitly Phase 3 in the design. |
| D10 | Budget cap | **Hard cap.** Any simulate/execute whose `post_trade_team_cost` exceeds `budget_cap` is rejected, not penalised. | Soft-cap penalties need a tuned penalty function nobody has time to calibrate this week. |
| D11 | Agent implementation | Endpoints are **contract-first**. Phase 1 backs them with deterministic heuristics; Phase 2 swaps in LLM calls behind the same schema. `agent_meta.mode` tells the client which produced a result. | Lets the UI be built and demoed before any agent is wired up. |

---

## 1) Transport and conventions

| Aspect | Convention |
|---|---|
| Base URL (local) | `http://localhost:8000` — the server *binds* `0.0.0.0:8000`; `0.0.0.0` is a bind address, never a client URL |
| Version prefix | `/api/v1` on everything except `/health` |
| Content type | `application/json; charset=utf-8`, request and response |
| Field casing | `snake_case` throughout |
| IDs | UUID v4 strings, except `opportunity_id`, an ephemeral opaque string `opp_<12 hex>` |
| Money | Integer, whole euros. Never a float, never a formatted string. `42500000` = €42,500,000 |
| Scores | Float, one decimal, 0.0–100.0 |
| Unit-interval values | Float 0.0–1.0 — `confidence`, `problem_score`, `opportunity_score` |
| Timestamps | RFC 3339 UTC with `Z`: `2026-09-18T10:00:00Z` |
| Nulls | Absent and `null` are equivalent. Arrays are never null — use `[]` |
| Tracing | Every response carries an `X-Request-Id` header, echoed in error bodies as `trace_id` |

### Interactive docs

FastAPI generates these with no extra work:

- Swagger UI — `/docs`
- ReDoc — `/redoc`
- OpenAPI JSON — `/openapi.json`

Leave all three enabled for the hackathon. For production, auth-protect `/docs` and `/redoc`
but keep `/openapi.json` reachable so client codegen keeps working.

### Idempotency

`POST /api/v1/agents/trader/execute` is the only state-mutating endpoint. It requires an
`idempotency_key` (client-generated UUID v4). Replaying a key:

- with an **identical** body → returns the original `200` verbatim, plus header `Idempotency-Replayed: true`
- with a **different** body → `409 IDEMPOTENCY_KEY_REUSED`

Keys are retained 24 hours. Every other endpoint is safe to retry freely.

### Pagination

Only unbounded lists paginate: `/market/listings`, `/insights`, `/trades`. Query params
`limit` (default 50, max 200) and `cursor` (opaque). Envelope:

```json
{ "items": [], "next_cursor": null, "total": 137 }
```

`next_cursor` is `null` on the last page. Rosters and dashboards do not paginate — a squad is
bounded at roughly 30 players.

---

## 2) Endpoint catalogue

| Method | Path | Purpose | UI stage | MVP |
|---|---|---|---|---|
| GET | `/health` | Liveness + dependency check | — | ✅ |
| GET | `/api/v1/version` | Build and agent model metadata | — | ✅ |
| GET | `/api/v1/teams` | List selectable teams | Team picker | ✅ |
| GET | `/api/v1/teams/{team_id}/dashboard` | KPIs + roster rows + pitch map, one call | Stage 1 | ✅ |
| GET | `/api/v1/teams/{team_id}/roster` | Raw roster without benchmark joins | — | ⬜ |
| GET | `/api/v1/benchmarks/positions` | League averages per position | Stage 1 | ✅ |
| GET | `/api/v1/market/listings` | Browse acquirable players | Stage 2 | ⬜ |
| POST | `/api/v1/agents/gap-finder/analyze` | Flag problem positions and players | Stage 1 | ✅ |
| POST | `/api/v1/agents/opportunity-finder/find` | Generate ranked trade options | Stage 2 | ✅ |
| POST | `/api/v1/agents/trader/simulate` | What-if a trade, no writes | Stage 2 | ✅ |
| POST | `/api/v1/agents/trader/execute` | Commit a trade, transactional | Stage 2 → 3 | ✅ |
| GET | `/api/v1/trades/{trade_id}` | Trade record | Stage 3 | ✅ |
| GET | `/api/v1/trades/{trade_id}/reasoning` | Full reasoning trace for a trade | Stage 3 | ⬜ |
| GET | `/api/v1/teams/{team_id}/insights` | Persisted agent insight trail | Stage 1/3 | ⬜ |

**Route shape.** The agent-segmented style is kept and formalised as
`/api/v1/agents/{agent}/{action}`. It reads well, maps one-to-one onto the three agents, and
groups cleanly under Swagger tags.

A generic `POST /api/v1/agents/{agent}/invoke` is deliberately **omitted**. It would force a
union-typed request and response body, which destroys the per-endpoint Pydantic response models
and makes the OpenAPI schema useless for client codegen — exactly the benefit you are adopting
FastAPI for. Add it only if a workflow engine later needs dynamic dispatch, and add it
*alongside* the explicit routes rather than replacing them.

Pure data reads (`/teams`, `/benchmarks`, `/market`) sit outside `/agents/`. Only endpoints
that actually run an agent live under it.

---

## 3) Canonical data model

These are the shared objects. Endpoints compose them; they never redefine fields. Names here
match the Pydantic models in `app/models/` one-to-one.

### 3.1 Enums

```python
Position        = "GK" | "RB" | "CB" | "LB" | "CDM" | "CM" | "CAM" | "LW" | "RW" | "ST"
PositionGroup   = "GK" | "DEF" | "MID" | "FWD"
HealthStatus    = "green" | "white" | "red"          # pitch-map traffic light
Severity        = "low" | "medium" | "high"
OpportunityType = "buy" | "sell" | "swap"
TradeAction     = "buy" | "sell" | "swap_in" | "swap_out"
TradeStatus     = "proposed" | "executed" | "rejected" | "failed"
InsightType     = "problem_flag" | "recommendation" | "risk_note"
AgentMode       = "heuristic" | "llm"
```

Fixed `position` → `position_group` mapping, applied server-side and never sent by clients:

| Group | Positions |
|---|---|
| `GK` | GK |
| `DEF` | RB, CB, LB |
| `MID` | CDM, CM, CAM |
| `FWD` | LW, RW, ST |

### 3.2 `TeamSummary`

```json
{
  "team_id": "5f2c1e90-3d4a-4f11-9a7e-1b2c3d4e5f60",
  "name": "Riverside FC",
  "budget_cap": 50000000,
  "roster_version": 17
}
```

| Field | Type | Notes |
|---|---|---|
| `team_id` | uuid | |
| `name` | string | Unique |
| `budget_cap` | int | Hard cap per D10 |
| `roster_version` | int | Increments on every committed trade. Optimistic-lock token per D7 |

### 3.3 `TeamMetrics`

The Stage 1 KPI cards, and the `post_trade_*` block on every simulation.

```json
{
  "team_cost": 43000000,
  "team_score": 77.8,
  "budget_cap": 50000000,
  "budget_remaining": 7000000,
  "squad_size": 24
}
```

| Field | Type | Definition |
|---|---|---|
| `team_cost` | int | `SUM(cost)` over current roster |
| `team_score` | float | `AVG(value_score)` over current roster, 1dp |
| `budget_cap` | int | Copied from the team |
| `budget_remaining` | int | `budget_cap - team_cost`. May be negative on a pre-existing overspend; a *trade* may never make it negative |
| `squad_size` | int | Count of current roster entries |

### 3.4 `PlayerRef`

The minimal player identity embedded wherever a player is referenced. Never carries money or
scores — those are contextual to a roster entry or a listing.

```json
{
  "player_id": "9a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
  "name": "T. Alvarez",
  "position": "CB",
  "position_group": "DEF",
  "age": 27
}
```

### 3.5 `RosterRow`

One row of the Stage 1 roster table. This is the shape that carries the league-benchmark
columns the design calls for.

```json
{
  "roster_entry_id": "1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f",
  "player": {
    "player_id": "9a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    "name": "T. Alvarez",
    "position": "CB",
    "position_group": "DEF",
    "age": 27
  },
  "cost": 4200000,
  "value_score": 61.5,
  "league_avg_cost": 3100000,
  "league_avg_value": 70.2,
  "cost_vs_league_pct": 35.5,
  "value_vs_league_pct": -12.4,
  "cost_efficiency": 0.41,
  "health_status": "red",
  "available": true
}
```

| Field | Type | Definition |
|---|---|---|
| `cost` | int | This player's salary on this team |
| `value_score` | float | Team-contextual contribution, 0–100 |
| `league_avg_cost` | int | League mean cost for the same `position` |
| `league_avg_value` | float | League mean value for the same `position` |
| `cost_vs_league_pct` | float | `(cost / league_avg_cost - 1) * 100`. Positive = overpaid |
| `value_vs_league_pct` | float | `(value_score / league_avg_value - 1) * 100`. Negative = underperforming |
| `cost_efficiency` | float | Normalised `value_score / cost` scaled to 0–1 across the league |
| `health_status` | HealthStatus | Player-level traffic light, thresholds in §4 |
| `available` | bool | Whether this player may legally be sold or swapped out |

Both `_vs_league_pct` fields are precomputed server-side. The frontend renders them; it does
not do this arithmetic, so the benchmark definition stays in one place.

### 3.6 `PitchSlot`

One circle on the cartoon pitch. Coordinates are normalised so the frontend can size the pitch
however it likes.

```json
{
  "position": "CB",
  "position_group": "DEF",
  "x": 0.35,
  "y": 0.25,
  "health_status": "red",
  "problem_score": 0.79,
  "occupants": ["9a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"],
  "slot_avg_cost": 4200000,
  "slot_avg_value": 61.5,
  "headline": "Below league median value at a premium price"
}
```

| Field | Type | Notes |
|---|---|---|
| `x`, `y` | float | 0.0–1.0. Origin top-left; `y=0` is the team's own goal line |
| `health_status` | HealthStatus | Circle colour: `red` problem, `green` good, `white` neutral |
| `problem_score` | float | 0.0–1.0, drives the colour. Formula in §4 |
| `occupants` | uuid[] | Players currently filling this slot. Empty array = unfilled slot, which is itself a gap |
| `headline` | string | One-line tooltip. Present only when `health_status` is `red` |

Clicking a slot navigates to Stage 2 carrying `position` (and `player_id` when the user clicked
a specific occupant).

### 3.7 `PositionBenchmark`

```json
{
  "position": "CB",
  "league_avg_cost": 3100000,
  "league_avg_value": 70.2,
  "cost_p50": 2900000,
  "value_p50": 71.0,
  "sample_size": 48
}
```

`sample_size` matters: with a small league seed, a benchmark over 3 players is noise. The UI
should mute benchmark columns when `sample_size < 5`.

### 3.8 `TradeLeg`

**Request form** — this is all a client ever sends (D2):

```json
{ "action": "swap_out", "player_id": "9a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d" }
```

**Response form** — server-enriched, all deltas signed per D3:

```json
{
  "action": "swap_out",
  "player": {
    "player_id": "9a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    "name": "T. Alvarez",
    "position": "CB",
    "position_group": "DEF",
    "age": 27
  },
  "cost_delta": -4200000,
  "value_delta": -61.5,
  "counterparty_team_id": null,
  "listing_id": null
}
```

| Action | `cost_delta` | `value_delta` | Source of truth |
|---|---|---|---|
| `buy` / `swap_in` | `+listing.cost` | `+listing.expected_value_score` | `market_listings` |
| `sell` / `swap_out` | `−roster_entry.cost` | `−roster_entry.value_score` | `roster_entries` |

`cost_delta` is just that player's salary, signed by direction. Nothing else contributes.

`counterparty_team_id` is the selling team for an incoming player, `null` for a free agent.
`listing_id` is set on `buy`/`swap_in` only, and pins the exact listing the salary came from.

Note that `value_delta` on a leg is a **raw score delta**, not a team-average delta — the two
are different and the team-level number is computed once over the whole trade in `TradeImpact`.

### 3.9 `TradeImpact`

Returned by `simulate`, and embedded in every `Opportunity`. This is the pre/post comparison
the Stage 2 panel renders.

```json
{
  "valid": true,
  "violations": [],
  "projected_cost_delta": -300000,
  "projected_value_delta": 2.1,
  "current_metrics": {
    "team_cost": 43300000,
    "team_score": 75.7,
    "budget_cap": 50000000,
    "budget_remaining": 6700000,
    "squad_size": 24
  },
  "post_trade_metrics": {
    "team_cost": 43000000,
    "team_score": 77.8,
    "budget_cap": 50000000,
    "budget_remaining": 7000000,
    "squad_size": 24
  },
  "position_group_counts_after": { "GK": 2, "DEF": 7, "MID": 8, "FWD": 7 },
  "roster_version": 17
}
```

| Field | Type | Notes |
|---|---|---|
| `valid` | bool | `false` when any hard constraint is broken. `violations` is then non-empty |
| `violations` | Violation[] | See §3.10 |
| `projected_cost_delta` | int | `post_trade_metrics.team_cost − current_metrics.team_cost`. Always exactly the sum of leg `cost_delta` values (this identity is what D1 buys you) |
| `projected_value_delta` | float | `post_trade_metrics.team_score − current_metrics.team_score`. **Not** the sum of leg `value_delta` values, because `team_score` is a mean over a changing squad size |
| `roster_version` | int | The version this was computed against. Pass it back to `execute` |

A `simulate` that returns `valid: false` is still **HTTP 200** — an invalid what-if is a
successful simulation of an invalid trade, and the UI wants to render the violations. Only
`execute` turns a violation into a 409.

### 3.10 `Violation`

```json
{
  "code": "BUDGET_CAP_EXCEEDED",
  "severity": "high",
  "message": "Trade would exceed budget cap by €1,000,000",
  "details": { "post_trade_cost": 51000000, "budget_cap": 50000000, "overage": 1000000 }
}
```

`severity` distinguishes hard blockers (`high`, always block execute) from soft warnings
(`low`/`medium`, surfaced in the UI but do not block). See the violation catalogue in §6.2.

### 3.11 `Opportunity`

The Stage 2 card. Ranked by `opportunity_score` descending.

```json
{
  "opportunity_id": "opp_4f2a9c1e8b03",
  "type": "swap",
  "target_position": "CB",
  "opportunity_score": 0.81,
  "confidence": 0.74,
  "legs": [
    {
      "action": "swap_out",
      "player": { "player_id": "9a1b...", "name": "T. Alvarez", "position": "CB", "position_group": "DEF", "age": 27 },
      "cost_delta": -4200000,
      "value_delta": -61.5,
      "counterparty_team_id": null,
      "listing_id": null
    },
    {
      "action": "swap_in",
      "player": { "player_id": "7e8f...", "name": "K. Osei", "position": "CB", "position_group": "DEF", "age": 24 },
      "cost_delta": 3700000,
      "value_delta": 78.9,
      "counterparty_team_id": "2b3c4d5e-6f70-4812-9a3b-4c5d6e7f8091",
      "listing_id": "aa11bb22-cc33-4d44-8e55-ff66aa77bb88"
    }
  ],
  "impact": { "...": "TradeImpact" },
  "risks": ["Only 11 league appearances for the incoming player"],
  "reasoning_summary": "Upgrades the weakest centre-back slot while cutting €500k of salary.",
  "reasoning_steps": [
    "CB unit value 61.5 sits 12.4% below the league average of 70.2.",
    "Alvarez costs 35.5% above the CB league average, the worst cost efficiency in the squad.",
    "Osei scores 78.9 at €3.7M, a better value-per-euro profile at the same position.",
    "Post-trade cost €43.0M leaves €7.0M of headroom under the €50M cap."
  ],
  "expires_at": "2026-09-18T10:15:00Z"
}
```

| Field | Type | Notes |
|---|---|---|
| `opportunity_id` | string | `opp_<12 hex>`. **Ephemeral** — see the caching note below |
| `opportunity_score` | float | 0.0–1.0 ranking key. Formula in §4. The UI sorts on this |
| `confidence` | float | 0.0–1.0, the agent's own certainty. Distinct from `opportunity_score`: a trade can be clearly good (high score) but rest on thin data (low confidence) |
| `impact` | TradeImpact | Full pre/post block, so the card needs no second round-trip |
| `reasoning_steps` | string[] | Ordered, human-readable. Rendered as the agent justification panel |
| `expires_at` | timestamp | Typically +15 min. Past this, `execute` returns `410 OPPORTUNITY_EXPIRED` |

**Caching.** Opportunities are held server-side (Redis or an in-process TTL dict for the
hackathon) keyed by `opportunity_id` so `execute` can be called with just the id. They are
invalidated whenever `roster_version` changes — every executed trade wipes the team's cached
opportunities, because their `impact` blocks are now computed against a stale roster.

### 3.12 `TradeRecord`

```json
{
  "trade_id": "3d4e5f60-7182-4934-a5b6-c7d8e9f0a1b2",
  "team_id": "5f2c1e90-3d4a-4f11-9a7e-1b2c3d4e5f60",
  "status": "executed",
  "initiated_by": "taylor.schneider@us.gt.com",
  "source_opportunity_id": "opp_4f2a9c1e8b03",
  "legs": [],
  "projected_cost_delta": -300000,
  "projected_value_delta": 2.1,
  "metrics_before": { "...": "TeamMetrics" },
  "metrics_after": { "...": "TeamMetrics" },
  "roster_version_before": 17,
  "roster_version_after": 18,
  "rationale_snapshot": {},
  "agent_meta": { "...": "AgentMeta" },
  "created_at": "2026-09-18T10:01:00Z",
  "executed_at": "2026-09-18T10:01:00Z"
}
```

There is no separate `realized_*` pair. Under D1 a trade's cost is just the salaries that moved,
so the projected figures are the realized figures — a second set of columns would always hold
identical values. The design doc's "projected vs realized" telemetry (§2.9) only becomes
meaningful once salaries can change after a trade, which is not a v1 concern.

`rationale_snapshot` is the frozen `Opportunity` as it was at approval time — the audit record
of what the GM actually agreed to.

### 3.13 `AgentInsight`

```json
{
  "insight_id": "6f708192-a3b4-45c6-87d8-e9f0a1b2c3d4",
  "team_id": "5f2c1e90-3d4a-4f11-9a7e-1b2c3d4e5f60",
  "agent_name": "gap_finder",
  "insight_type": "problem_flag",
  "severity": "high",
  "position": "CB",
  "player_id": "9a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
  "summary": "Centre-back unit is 12.4% below league average value at 35.5% above league cost",
  "details": { "problem_score": 0.79, "value_percentile": 0.18, "cost_percentile": 0.88 },
  "created_at": "2026-09-18T10:00:00Z"
}
```

### 3.14 `AgentMeta`

Attached to every agent response. This is the explainability and reproducibility hook.

```json
{
  "agent_name": "opportunity_finder",
  "mode": "heuristic",
  "version": "1.0.0",
  "model": null,
  "input_snapshot_hash": "sha256:1f3a...",
  "latency_ms": 412,
  "generated_at": "2026-09-18T10:00:00Z"
}
```

`model` is null in `heuristic` mode and carries the model id in `llm` mode. `input_snapshot_hash`
is a SHA-256 over the canonicalised agent input, which is what lets you prove after the fact
which roster state a recommendation was made against.

### 3.15 `ErrorEnvelope`

```json
{
  "error": {
    "code": "BUDGET_CAP_EXCEEDED",
    "message": "Trade would exceed team budget cap",
    "details": { "post_trade_cost": 51000000, "budget_cap": 50000000 },
    "trace_id": "req-abc-123"
  }
}
```

Every non-2xx response uses this shape, including FastAPI's own 422s — install an exception
handler that rewrites `RequestValidationError` into this envelope with
`code: "VALIDATION_ERROR"` and the raw Pydantic errors under `details.fields`. Without that
handler you ship two different error formats, and the frontend has to branch on status code to
parse them.

---

## 4) Scoring formulas

Single source of truth for anything the UI colours or sorts. All percentiles are computed
within `position` across all current roster entries in the league.

**Per-player cost efficiency**

```
cost_efficiency = normalize_0_1( value_score / cost )
```

**Position problem score** (drives `PitchSlot.health_status`)

```
value_gap        = 1 - value_percentile
cost_penalty     = 1 - cost_efficiency
coverage_penalty = 1 if the slot is unfilled or below its group minimum, else 0

problem_score = w1*value_gap + w2*cost_penalty + w3*coverage_penalty
w1 = 0.45, w2 = 0.35, w3 = 0.20
```

**Traffic light thresholds**

| `problem_score` | `health_status` |
|---|---|
| `>= 0.67` | `red` |
| `0.34 – 0.67` | `white` |
| `< 0.34` | `green` |

**Opportunity ranking**

```
opportunity_score = a1*value_gain_norm + a2*cost_saving_norm - a3*risk_norm
a1 = 0.50, a2 = 0.35, a3 = 0.15
```

`value_gain_norm` and `cost_saving_norm` are min-max normalised across the candidate set
returned by a single Opportunity Finder call, so `opportunity_score` is only comparable *within*
one response — do not persist it for cross-run comparison.

Weights live in `app/core/config.py` and are exposed read-only at `GET /api/v1/version` so a
demo can show that the thresholds are tunable rather than magic.

---

## 5) Endpoint specifications

### 5.1 `GET /health`

No auth. Returns 200 when the process is up and the database answers `SELECT 1`; 503 otherwise.

```json
{
  "status": "ok",
  "checks": { "database": "ok", "cache": "ok" },
  "uptime_seconds": 8421
}
```

### 5.2 `GET /api/v1/version`

```json
{
  "api_version": "v1",
  "build": "2026-09-18.3",
  "git_sha": "a1b2c3d",
  "agents": {
    "gap_finder": { "mode": "heuristic", "version": "1.0.0", "model": null },
    "opportunity_finder": { "mode": "heuristic", "version": "1.0.0", "model": null },
    "trader": { "mode": "heuristic", "version": "1.0.0", "model": null }
  },
  "scoring_weights": { "w1": 0.45, "w2": 0.35, "w3": 0.2, "a1": 0.5, "a2": 0.35, "a3": 0.15 }
}
```

### 5.3 `GET /api/v1/teams`

Returns `TeamSummary[]` for the team picker. Not paginated — the seeded league is ~20 teams.

```json
{ "items": [ { "...": "TeamSummary" } ], "total": 20 }
```

### 5.4 `GET /api/v1/teams/{team_id}/dashboard`

**The single most important endpoint.** Stage 1 renders entirely from this one response — KPI
cards, roster table, and pitch map — so the dashboard never shows a half-loaded state.

Query params:

| Param | Type | Default | Notes |
|---|---|---|---|
| `include_gaps` | bool | `true` | Runs Gap Finder inline and populates `health_status` / `problem_score`. Set `false` for a fast data-only render |

Response:

```json
{
  "team": { "...": "TeamSummary" },
  "metrics": { "...": "TeamMetrics" },
  "roster": [ { "...": "RosterRow" } ],
  "pitch": {
    "formation": "4-3-3",
    "slots": [ { "...": "PitchSlot" } ]
  },
  "flagged_positions": [
    { "position": "CB", "severity": "high", "problem_score": 0.79, "reasons": ["value 12.4% below league average", "cost 35.5% above league average"] }
  ],
  "roster_version": 17,
  "agent_meta": { "...": "AgentMeta" },
  "generated_at": "2026-09-18T10:00:00Z"
}
```

Errors: `404 TEAM_NOT_FOUND`.

`pitch.formation` is a string the frontend uses to pick a slot layout. v1 seeds everything as
`4-3-3`; the slot coordinates come from the server regardless, so adding formations later is a
data change, not a frontend change.

### 5.5 `GET /api/v1/teams/{team_id}/roster`

The roster without benchmark joins or agent analysis — cheap, and useful for debugging when the
dashboard looks wrong. Returns `{ "team_id", "roster_version", "items": RosterRow[] }` with the
`league_avg_*`, `health_status` and `problem_score` fields omitted.

### 5.6 `GET /api/v1/benchmarks/positions`

Query params: `position` (optional, repeatable) to filter.

```json
{ "items": [ { "...": "PositionBenchmark" } ], "computed_at": "2026-09-18T09:55:00Z" }
```

Backed by the `v_position_league_benchmarks` view. Cache for 60s — it changes only when a trade
commits.

### 5.7 `GET /api/v1/market/listings`

Query params: `position`, `position_group`, `max_cost`, `min_value`, `exclude_team_id`,
`limit`, `cursor`.

```json
{
  "items": [
    {
      "listing_id": "aa11bb22-cc33-4d44-8e55-ff66aa77bb88",
      "player": { "...": "PlayerRef" },
      "source_team_id": "2b3c4d5e-6f70-4812-9a3b-4c5d6e7f8091",
      "cost": 3700000,
      "expected_value_score": 78.9,
      "available": true,
      "updated_at": "2026-09-18T09:00:00Z"
    }
  ],
  "next_cursor": null,
  "total": 137
}
```

`cost` is the salary this player will carry once on your roster — the same field, with the same
meaning, as `cost` on a `RosterRow`. One concept, one name, everywhere.

If the database keeps the design doc's `market_listings.asking_price` column, map it to `cost`
in the repository layer. Do not surface two names for one number through the API.

### 5.8 `POST /api/v1/agents/gap-finder/analyze`

Analyses a team against league benchmarks and flags problems. Read-only, but `POST` because the
constraint block is a structured body and it may trigger an LLM call in Phase 2.

Request:

```json
{
  "team_id": "5f2c1e90-3d4a-4f11-9a7e-1b2c3d4e5f60",
  "constraints": {
    "budget_cap": null,
    "min_position_group_counts": { "GK": 2, "DEF": 6, "MID": 6, "FWD": 4 }
  },
  "persist_insights": true
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `team_id` | uuid | ✅ | |
| `constraints.budget_cap` | int? | ⬜ | Overrides the team's stored cap for what-if analysis. `null` uses the stored value |
| `constraints.min_position_group_counts` | map | ⬜ | Keyed by `PositionGroup` per D5. Defaults to `{GK:2, DEF:6, MID:6, FWD:4}` |
| `persist_insights` | bool | ⬜ | Default `true`. Writes results to `agent_insights` for the explainability trail |

Response:

```json
{
  "team_id": "5f2c1e90-3d4a-4f11-9a7e-1b2c3d4e5f60",
  "flagged_positions": [
    {
      "position": "CB",
      "position_group": "DEF",
      "severity": "high",
      "problem_score": 0.79,
      "health_status": "red",
      "reasons": ["value 12.4% below league average", "cost 35.5% above league average"],
      "metrics": { "team_avg_cost": 4200000, "team_avg_value": 61.5, "league_avg_cost": 3100000, "league_avg_value": 70.2 }
    }
  ],
  "flagged_players": [
    {
      "player": { "...": "PlayerRef" },
      "severity": "medium",
      "problem_score": 0.71,
      "health_status": "red",
      "reasons": ["cost efficiency 0.41, lowest in squad"]
    }
  ],
  "coverage_warnings": [
    { "position_group": "GK", "required": 2, "actual": 1, "severity": "high" }
  ],
  "roster_version": 17,
  "agent_meta": { "...": "AgentMeta" },
  "generated_at": "2026-09-18T10:00:00Z"
}
```

`coverage_warnings` is new relative to the earlier draft: a squad can be *under-filled* at a
position without any individual player being bad, and the earlier response shape had nowhere to
express that.

Errors: `404 TEAM_NOT_FOUND`, `422` on payload validation.

### 5.9 `POST /api/v1/agents/opportunity-finder/find`

Generates ranked trade options for a focus area. Results are cached server-side keyed by
`opportunity_id` so `execute` can reference one by id.

Request:

```json
{
  "team_id": "5f2c1e90-3d4a-4f11-9a7e-1b2c3d4e5f60",
  "focus": {
    "positions": ["CB"],
    "player_ids": [],
    "types": ["buy", "sell", "swap"]
  },
  "constraints": {
    "budget_cap": null,
    "min_position_group_counts": { "GK": 2, "DEF": 6, "MID": 6, "FWD": 4 },
    "max_results": 20,
    "max_cost_increase": 0,
    "min_value_gain": 0.5
  },
  "roster_version": 17
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `focus.positions` | Position[] | ⬜ | Empty = analyse the whole squad |
| `focus.player_ids` | uuid[] | ⬜ | Narrows to trades involving these players. Combined with `positions` as OR |
| `focus.types` | OpportunityType[] | ⬜ | Defaults to all three |
| `constraints.max_results` | int | ⬜ | Default 20, max 50 |
| `constraints.max_cost_increase` | int? | ⬜ | Hard filter. `0` = only cost-neutral-or-better trades |
| `constraints.min_value_gain` | float? | ⬜ | Hard filter on `projected_value_delta` |
| `roster_version` | int? | ⬜ | If supplied and stale → `409 STALE_ROSTER_VERSION`, so a user cannot act on a dashboard rendered before someone else's trade |

Response:

```json
{
  "team_id": "5f2c1e90-3d4a-4f11-9a7e-1b2c3d4e5f60",
  "focus": { "positions": ["CB"], "player_ids": [], "types": ["buy", "sell", "swap"] },
  "opportunities": [ { "...": "Opportunity" } ],
  "candidates_evaluated": 184,
  "roster_version": 17,
  "agent_meta": { "...": "AgentMeta" },
  "generated_at": "2026-09-18T10:00:00Z"
}
```

`opportunities` is sorted by `opportunity_score` descending. An empty array is a valid 200 —
the UI shows a "no viable moves under these constraints" empty state, and `candidates_evaluated`
lets it say whether that was because nothing was considered or because everything was filtered out.

Errors: `404 TEAM_NOT_FOUND`, `409 STALE_ROSTER_VERSION`.

### 5.10 `POST /api/v1/agents/trader/simulate`

Pure what-if. Writes nothing. Accepts either a cached opportunity or explicit legs, so the user
can hand-build a trade in Stage 2.

Request — exactly one of `opportunity_id` or `legs`:

```json
{
  "team_id": "5f2c1e90-3d4a-4f11-9a7e-1b2c3d4e5f60",
  "opportunity_id": null,
  "legs": [
    { "action": "sell", "player_id": "9a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d" },
    { "action": "buy",  "player_id": "7e8f9a0b-1c2d-4e3f-8a9b-0c1d2e3f4a5b" }
  ],
  "roster_version": 17
}
```

Response: a `TradeImpact`, plus the enriched legs.

```json
{
  "impact": { "...": "TradeImpact" },
  "legs": [ { "...": "TradeLeg (response form)" } ],
  "agent_meta": { "...": "AgentMeta" }
}
```

Returns **200 even when `impact.valid` is false** — the UI needs the violation list to explain
why the Execute button is disabled. The only 4xx cases are structural: unknown team, unknown
player, expired opportunity, stale version.

Errors: `400 INVALID_LEG_COMBINATION` (e.g. both `opportunity_id` and `legs`, or a `swap_in`
with no matching `swap_out`), `404 TEAM_NOT_FOUND` / `PLAYER_NOT_FOUND`,
`409 STALE_ROSTER_VERSION`, `410 OPPORTUNITY_EXPIRED`.

### 5.11 `POST /api/v1/agents/trader/execute`

Commits a trade. The only mutating endpoint, and the only one gated on explicit human approval.

Request:

```json
{
  "team_id": "5f2c1e90-3d4a-4f11-9a7e-1b2c3d4e5f60",
  "opportunity_id": "opp_4f2a9c1e8b03",
  "legs": null,
  "roster_version": 17,
  "user_confirmation": true,
  "idempotency_key": "7d10ea31-1d0c-4f2f-8d58-3139af7336f3"
}
```

| Field | Required | Notes |
|---|---|---|
| `opportunity_id` \| `legs` | ✅ | Exactly one. Same rule as `simulate` |
| `roster_version` | ✅ | **Required here**, unlike simulate. Mismatch → `409 STALE_ROSTER_VERSION` |
| `user_confirmation` | ✅ | Must be literally `true`. `false` → `400 CONFIRMATION_REQUIRED`. This is the human-in-the-loop gate and is enforced server-side, not just in the modal |
| `idempotency_key` | ✅ | UUID v4. See §1 |

Response `200`:

```json
{
  "trade": { "...": "TradeRecord" },
  "metrics_after": { "...": "TeamMetrics" },
  "roster_version_after": 18,
  "applied_changes": {
    "acquired": [ { "...": "PlayerRef" } ],
    "released":  [ { "...": "PlayerRef" } ]
  },
  "invalidated_opportunity_ids": ["opp_4f2a9c1e8b03", "opp_9b8c7d6e5f40"],
  "executed_at": "2026-09-18T10:01:00Z"
}
```

`invalidated_opportunity_ids` tells the frontend exactly which cached cards to drop. Without it
the UI has to blanket-invalidate and refetch everything, which is the slow path in the demo.

**Execution guarantees.** A single database transaction closes the outgoing `roster_entries`
(sets `effective_to`, `is_current = false`), inserts the incoming ones, marks consumed
`market_listings` unavailable, writes `trades` + `trade_items`, and increments
`teams.roster_version` under the optimistic lock. Any failure rolls the whole thing back and
returns `500 EXECUTION_FAILED` with `trade.status = "failed"` persisted for the audit trail.

Errors: `400 CONFIRMATION_REQUIRED` / `INVALID_LEG_COMBINATION`, `404`,
`409 STALE_ROSTER_VERSION` / `IDEMPOTENCY_KEY_REUSED` / any hard `Violation` code,
`410 OPPORTUNITY_EXPIRED`, `500 EXECUTION_FAILED`.

### 5.12 `GET /api/v1/trades/{trade_id}`

Returns a `TradeRecord`. Errors: `404 TRADE_NOT_FOUND`.

### 5.13 `GET /api/v1/trades/{trade_id}/reasoning`

The full explainability payload for a committed trade — the frozen opportunity, the agent chain,
and the input hash.

```json
{
  "trade_id": "3d4e5f60-7182-4934-a5b6-c7d8e9f0a1b2",
  "rationale_snapshot": { "...": "Opportunity as approved" },
  "agent_chain": [
    { "...": "AgentMeta for gap_finder" },
    { "...": "AgentMeta for opportunity_finder" },
    { "...": "AgentMeta for trader" }
  ],
  "insights": [ { "...": "AgentInsight" } ]
}
```

### 5.14 `GET /api/v1/teams/{team_id}/insights`

Query params: `agent_name`, `insight_type`, `severity`, `position`, `since`, `limit`, `cursor`.
Returns a paginated `AgentInsight[]`, newest first.

---

## 6) Errors

### 6.1 Status code usage

| Status | Meaning | Example |
|---|---|---|
| 400 | Malformed request the schema cannot catch | Both `opportunity_id` and `legs` supplied |
| 401 / 403 | Missing or insufficient credentials | No `x-api-key`; non-GM role calling execute |
| 404 | Referenced entity does not exist | Unknown `team_id` |
| 409 | **Valid request, invalid state or business rule** | Budget cap, squad minimum, stale version, idempotency conflict |
| 410 | Referenced ephemeral resource has expired | `opportunity_id` past `expires_at` |
| 422 | **Pydantic/FastAPI schema validation only** | `budget_cap` sent as a string |
| 429 | Rate limited | Agent endpoints under load |
| 500 | Unexpected failure | Transaction rollback |
| 503 | Dependency down | Database unreachable at `/health` |

The 409-vs-422 split is D6 and matters: with FastAPI you do not get to choose what 422 means,
so business-rule failures need their own code.

### 6.2 Error and violation code catalogue

| Code | Status | Hard? | Meaning |
|---|---|---|---|
| `VALIDATION_ERROR` | 422 | — | Payload failed schema validation; `details.fields` carries Pydantic errors |
| `TEAM_NOT_FOUND` | 404 | — | |
| `PLAYER_NOT_FOUND` | 404 | — | |
| `TRADE_NOT_FOUND` | 404 | — | |
| `LISTING_NOT_FOUND` | 404 | — | |
| `OPPORTUNITY_EXPIRED` | 410 | — | Past `expires_at`, or invalidated by a newer trade |
| `INVALID_LEG_COMBINATION` | 400 | — | Zero or both of `opportunity_id`/`legs`; unpaired swap |
| `CONFIRMATION_REQUIRED` | 400 | — | `user_confirmation` was not `true` |
| `STALE_ROSTER_VERSION` | 409 | — | Client's `roster_version` is behind the server's |
| `IDEMPOTENCY_KEY_REUSED` | 409 | — | Same key, different body |
| `BUDGET_CAP_EXCEEDED` | 409 | ✅ | `post_trade_team_cost > budget_cap` |
| `POSITION_MINIMUM_VIOLATED` | 409 | ✅ | A `position_group` would drop below its minimum |
| `PLAYER_NOT_AVAILABLE` | 409 | ✅ | Listing unavailable, or roster player has `available: false` |
| `PLAYER_NOT_ON_ROSTER` | 409 | ✅ | Trying to sell a player the team does not hold |
| `DUPLICATE_PLAYER_IN_TRADE` | 409 | ✅ | Same `player_id` appears in two legs |
| `SQUAD_SIZE_EXCEEDED` | 409 | ✅ | Post-trade squad above the configured max (default 30) |
| `HIGH_UNCERTAINTY` | — | ⬜ | Soft. Incoming player's `expected_value_score` rests on a thin sample |
| `POSITION_CHURN` | — | ⬜ | Soft. Three or more simultaneous changes in one `position_group` |
| `EXECUTION_FAILED` | 500 | — | Transaction rolled back; trade persisted as `failed` |

Hard codes appear both as `Violation` entries inside a 200 `simulate` response and as the error
`code` on a 409 from `execute`. Soft codes only ever appear as `Violation` entries — they never
block. Reusing one vocabulary across both means the frontend renders the same message component
either way.

---

## 7) Security

Hackathon minimum:

- `x-api-key` header between UI and API, checked by a FastAPI dependency on the `/api/v1` router
- CORS locked to the frontend origin — do not ship `allow_origins=["*"]`, even in the demo
- `user_confirmation` enforced server-side on execute
- `idempotency_key` required on execute
- Structured request/response audit log for every `/agents/` call, keyed by `trace_id`

Production path:

- JWT bearer auth carrying user identity, replacing the shared key
- Role check: only `gm` may call `trader/execute`; `analyst` gets read + simulate
- `initiated_by` on `TradeRecord` populated from the token rather than the request body
- Rate limit the agent endpoints — they are the expensive ones

---

## 8) Request flows

**Stage 1 — dashboard load**

```
GET /api/v1/teams/{id}/dashboard?include_gaps=true
  └─ internally: roster + v_position_league_benchmarks + Gap Finder
→ KPI cards, roster table, pitch map, all from one response
```

**Stage 2 — opportunities for a clicked circle**

```
POST /api/v1/agents/opportunity-finder/find
     { focus: { positions: ["CB"] }, roster_version: 17 }
→ ranked Opportunity[], each already carrying its full TradeImpact

[user tweaks legs by hand]
POST /api/v1/agents/trader/simulate  { legs: [...], roster_version: 17 }
→ TradeImpact, 200 even when invalid
```

**Stage 2 → 3 — execution**

```
POST /api/v1/agents/trader/execute
     { opportunity_id, roster_version: 17, user_confirmation: true, idempotency_key }
→ TradeRecord + roster_version_after: 18 + invalidated_opportunity_ids

frontend: invalidate those opportunity queries + the dashboard query, navigate to Stage 1
```

The `roster_version` thread through all three calls is what makes the flow safe: an opportunity
generated against v17 cannot be executed after the roster has moved to v18.

---

## 9) Implementation layout

```text
app/
  main.py                      # FastAPI app, CORS, exception handlers
  core/
    config.py                  # settings + scoring weights (§4)
    logging.py                 # structured logs with trace_id
    errors.py                  # ErrorEnvelope, AppError, handler registration
  api/
    deps.py                    # api-key dep, db session dep
    v1/
      router.py
      endpoints/
        health.py
        teams.py               # dashboard, roster, list
        benchmarks.py
        market.py
        gap_finder.py
        opportunity_finder.py
        trader.py              # simulate + execute
        trades.py              # record + reasoning
        insights.py
  models/
    enums.py                   # §3.1
    domain.py                  # §3.2–3.14 shared objects
    requests.py
    responses.py
  services/
    scoring.py                 # §4 formulas, one implementation
    gap_finder_service.py
    opportunity_finder_service.py
    trader_service.py          # simulate + execute + transaction
    opportunity_cache.py       # TTL store keyed by opportunity_id
  repositories/
    teams_repo.py
    roster_repo.py
    market_repo.py
    trade_repo.py
    insight_repo.py
  db/
    models.py                  # SQLAlchemy tables
    views.sql                  # v_team_cost, v_team_score, v_position_league_benchmarks
    seed.py
```

Two rules that keep this from drifting:

- `models/domain.py` is the only place the §3 objects are defined. `requests.py` and
  `responses.py` compose them and never restate a field.
- `services/scoring.py` is the only place a §4 formula appears. Gap Finder, Opportunity Finder,
  and the dashboard all call it, so a threshold change lands everywhere at once.

### OpenAPI tags

`Health`, `Teams`, `Benchmarks`, `Market`, `Gap Finder`, `Opportunity Finder`, `Trader`,
`Trades`, `Insights`.

Give every route a `summary` stating business intent, a `response_model`, and
`responses={409: {"model": ErrorEnvelope}}` for the error cases — otherwise Swagger documents
only the happy path and the generated client has no error type.

---

## 10) Pydantic sketch

Enough to start from; the full set follows §3 mechanically.

```python
from datetime import datetime
from enum import StrEnum
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class Position(StrEnum):
    GK = "GK"; RB = "RB"; CB = "CB"; LB = "LB"
    CDM = "CDM"; CM = "CM"; CAM = "CAM"
    LW = "LW"; RW = "RW"; ST = "ST"


class HealthStatus(StrEnum):
    GREEN = "green"; WHITE = "white"; RED = "red"


class TradeAction(StrEnum):
    BUY = "buy"; SELL = "sell"
    SWAP_IN = "swap_in"; SWAP_OUT = "swap_out"


class TradeLegRequest(BaseModel):
    action: TradeAction
    player_id: UUID
    # no price fields, by design (D2)


class TeamMetrics(BaseModel):
    team_cost: int
    team_score: float = Field(ge=0, le=100)
    budget_cap: int
    budget_remaining: int
    squad_size: int


class SimulateRequest(BaseModel):
    team_id: UUID
    opportunity_id: str | None = None
    legs: list[TradeLegRequest] | None = None
    roster_version: int | None = None

    @model_validator(mode="after")
    def exactly_one_source(self):
        if bool(self.opportunity_id) == bool(self.legs):
            raise ValueError("supply exactly one of opportunity_id or legs")
        return self


class ExecuteRequest(BaseModel):
    team_id: UUID
    opportunity_id: str | None = None
    legs: list[TradeLegRequest] | None = None
    roster_version: int                      # required, unlike simulate (D7)
    user_confirmation: Literal[True]         # schema-level human-in-the-loop gate
    idempotency_key: UUID
```

`user_confirmation: Literal[True]` is worth noting — it makes an unconfirmed execute
structurally impossible to express, so the guarantee lives in the schema and appears in the
OpenAPI doc rather than relying on a runtime check somebody can forget.

---

## 11) Still open

Not blocking implementation, but decide before Phase 2:

1. **Where `value_score` comes from.** v1 treats it as a seeded static column. If it becomes
   model-derived, it needs `as_of` and `model_version` fields on `RosterRow`, and the benchmark
   cache TTL has to drop.
2. **Free-agent representation.** Currently a `market_listing` with `source_team_id: null`.
   If free agents get their own lifecycle (contract length, signing windows), they want a
   separate resource.
3. **Counterparty consent.** D9 skips it. Phase 3 multi-team negotiation needs a
   `trade_proposals` table and a second approval step, which changes `execute` into a
   propose/accept pair.
4. **Squad maximum.** `SQUAD_SIZE_EXCEEDED` assumes 30. Confirm against whatever league rules
   the seed data is meant to represent.
5. **`HACKATHON_DESIGN.md` §2.13** still names Node + Fastify and should be updated to D8, and
   §2.6's endpoint list should be replaced with a pointer to §2 of this doc so there is one
   route list rather than two.
