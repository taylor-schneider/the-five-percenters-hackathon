# Soccer GM Trade Assistant - Draft and Low-Level Design

## 1) Captured Initial Draft (from working notes)

### Product concept
A human-in-the-loop chat experience where a soccer team's General Manager can interact with specialized agents to analyze the team and make trades.

Global optimization intent:
- Minimize aggregate player salary cost
- Maximize average player value on each team

### UI/UX workflow
There are three workflow stages.

#### Stage 1: Team Dashboard
Show:
- Team total cost
- Team value (average value)
- Table with columns:
  - Player
  - Position
  - Cost
  - Value
  - League average cost for same position
  - League average value for same position
- A rough/cartoon football pitch with circles for each position
  - Red circle: position/player is a problem
  - Green circle: position/player is good
  - White circle: neutral

Interaction:
- Clicking a circle/player navigates to Stage 2 (Opportunities page) for that position/player context

#### Stage 2: Opportunities
Show:
- All possible trade options
- Cases may include:
  - Buy to fill a gap
  - Sell to free budget
  - Swap players
- For each option show:
  - Budget impact
  - Team value impact
  - Agent reasoning/justification

Interaction:
- User can execute a trade
- After trade execution, navigate back to Stage 1 and reload updated data

#### Stage 3: Return/Refresh
- Dashboard refreshes with latest roster/cost/value after trade execution

### Data tables and views (initial)
Base table:
- Team Roster:
  - Team
  - Player
  - Cost
  - Value
  - Position
  - Available

Views:
- Team cost = total player cost
- Team score = average player value

### Agents (initial)
- Gap Finder: analyzes market data and identifies team problems
- Opportunity Finder: finds trade opportunities and provides justifications
- Trader: updates data to manifest the trade

---

## 2) Low-Level Design

## 2.1 Goals and constraints
Primary goals:
- Keep the human GM in control (approval required for every trade execution)
- Provide transparent rationale from agents
- Provide fast what-if simulation before execution

Optimization framing:
- Multi-objective optimization with weighted score
- Objective = minimize cost, maximize value, preserve positional coverage constraints

## 2.2 Proposed architecture

### Frontend
- React app (TypeScript)
- State/data fetching via React Query
- Simple route flow:
  - /dashboard (Stage 1)
  - /opportunities/:teamId/:position or :playerId (Stage 2)
- Reusable components:
  - TeamKpiCards
  - TeamRosterTable
  - PitchMap
  - OpportunityList
  - OpportunityCardWithReasoning
  - TradeImpactPanel

### Backend API
- Node.js + TypeScript (Express or Fastify)
- Responsibilities:
  - CRUD/read endpoints for roster and market data
  - Computed endpoints for dashboard and opportunities
  - Trade simulation endpoint
  - Trade execution endpoint (transactional)
  - Agent orchestration endpoints

### Agent orchestration layer
- Lightweight service abstraction around three agents
- Each agent has strict input/output JSON contracts
- Opportunity Finder can call Gap Finder outputs as context
- Trader only executes after explicit user action

### Data layer
- PostgreSQL (recommended)
- SQL views/materialized views for aggregates
- Optional Redis cache for dashboard/opportunity snapshots

## 2.3 Domain model and schema

### Core tables

#### teams
- id (uuid, pk)
- name (text, unique)
- budget_cap (numeric)
- created_at (timestamp)

#### players
- id (uuid, pk)
- name (text)
- primary_position (text)
- market_value_score (numeric)  -- global independent quality estimate
- active (boolean)

#### roster_entries
Represents a player's membership in a team for current season state.
- id (uuid, pk)
- team_id (uuid, fk -> teams.id)
- player_id (uuid, fk -> players.id)
- salary_cost (numeric)
- value_score (numeric)         -- team-contextual contribution score
- position (text)
- available (boolean)
- effective_from (timestamp)
- effective_to (timestamp, nullable)
- is_current (boolean)

#### market_listings
Represents players available for purchase/trade.
- id (uuid, pk)
- player_id (uuid, fk -> players.id)
- source_team_id (uuid, fk -> teams.id, nullable for free agents)
- asking_price (numeric)
- expected_value_score (numeric)
- position (text)
- available (boolean)
- updated_at (timestamp)

#### trades
- id (uuid, pk)
- initiated_by_user (text)
- team_id (uuid, fk -> teams.id)
- status (text) -- proposed, executed, rejected, failed
- rationale_snapshot (jsonb)
- projected_cost_delta (numeric)
- projected_value_delta (numeric)
- created_at (timestamp)
- executed_at (timestamp, nullable)

#### trade_items
One trade may include multiple buy/sell/swap legs.
- id (uuid, pk)
- trade_id (uuid, fk -> trades.id)
- action_type (text) -- buy, sell, swap_out, swap_in
- player_id (uuid, fk -> players.id)
- from_team_id (uuid, nullable)
- to_team_id (uuid, nullable)
- transfer_cost (numeric)
- projected_value_change (numeric)

#### agent_insights
Persistent explainability trail.
- id (uuid, pk)
- team_id (uuid, fk -> teams.id)
- player_id (uuid, nullable)
- position (text, nullable)
- agent_name (text) -- gap_finder, opportunity_finder
- insight_type (text) -- problem_flag, recommendation, risk_note
- severity (text) -- low, medium, high
- summary (text)
- details (jsonb)
- created_at (timestamp)

### Derived views

#### v_team_cost
SQL idea:
- group roster_entries where is_current = true by team_id
- sum salary_cost as total_cost

#### v_team_score
SQL idea:
- group roster_entries where is_current = true by team_id
- avg value_score as avg_value_score

#### v_position_league_benchmarks
- position
- avg(salary_cost) as league_avg_position_cost
- avg(value_score) as league_avg_position_value

#### v_team_position_health
For each team and position:
- team_position_avg_cost
- team_position_avg_value
- z-score against league benchmark
- traffic_light_status (red/white/green)

## 2.4 Key formulas and ranking

Define normalized metrics (0 to 1):
- cost_efficiency = normalized(value_score / salary_cost)
- value_percentile = percentile of player value_score by position
- cost_percentile_inverse = 1 - percentile of salary_cost by position

Position problem score:
- problem_score = w1*(1 - value_percentile) + w2*(1 - cost_efficiency) + w3*coverage_penalty

Traffic light thresholds:
- red if problem_score >= 0.67
- white if 0.34 <= problem_score < 0.67
- green if problem_score < 0.34

Opportunity ranking score:
- opportunity_score = a1*(projected_value_delta_norm) + a2*(projected_cost_reduction_norm) - a3*(risk_norm)

## 2.5 Agent tool contracts

Use strict JSON schemas for each tool call.

### Gap Finder
Input:
- team_id
- roster_snapshot (current roster entries)
- league_position_benchmarks
- constraints (budget, min players per position)

Output:
- flagged_positions: [
  - position
  - severity
  - problem_score
  - reasons[]
]
- flagged_players: [
  - player_id
  - severity
  - reasons[]
]

### Opportunity Finder
Input:
- team_id
- target_positions[] or target_player_ids[]
- market_listings
- current_team_metrics
- constraints

Output:
- opportunities: [
  - opportunity_id
  - type (buy/sell/swap)
  - legs[]
  - projected_cost_delta
  - projected_value_delta
  - post_trade_team_cost
  - post_trade_team_score
  - confidence
  - risks[]
  - reasoning_summary
  - reasoning_steps[]
]

### Trader
Input:
- trade_id or opportunity payload
- user_confirmation (boolean)
- idempotency_key

Output:
- execution_status
- applied_changes
- new_team_metrics
- audit_record_id

Execution guarantees:
- Transactional DB update
- Optimistic lock on roster state version
- Rollback on failure
- Idempotent by idempotency_key

## 2.6 API endpoints

### Dashboard
- GET /api/teams/:teamId/dashboard
  - returns KPIs, roster table rows, pitch statuses

### Opportunities
- GET /api/teams/:teamId/opportunities?position=...&playerId=...
  - triggers/reads Opportunity Finder results
- POST /api/teams/:teamId/opportunities/simulate
  - simulate custom user-proposed trade

### Trade execution
- POST /api/trades/execute
  - body: opportunity_id or explicit trade legs
  - executes Trader

### Explainability
- GET /api/trades/:tradeId/reasoning
- GET /api/teams/:teamId/insights

## 2.7 Frontend behavior details

### Stage 1 dashboard behavior
- Load endpoint once on page mount
- Render KPI cards:
  - total cost
  - average value score
  - budget remaining
- Render roster table with league benchmark columns
- Render pitch map circles by position with traffic light color
- Circle click passes context to Stage 2 route params

### Stage 2 opportunities behavior
- Fetch opportunities for selected context
- Show cards ranked by opportunity_score
- For selected card:
  - render projected deltas
  - render pre/post comparison mini-table
  - render agent reasoning
- Execute button opens confirmation modal with final delta summary

### Post-execution flow
- On successful execute:
  - toast success
  - navigate to dashboard
  - invalidate dashboard/opportunity query cache
  - re-fetch latest data

## 2.8 Trade simulation and validation rules

Hard constraints:
- Budget cap cannot be exceeded
- Positional minimum counts must remain satisfied
- Cannot buy unavailable player
- Cannot sell player not in current roster

Soft constraints (ranking penalties):
- Injury risk proxy (if available)
- Large uncertainty in expected value
- Too many simultaneous changes in same position

## 2.9 Auditability and observability

Store for every recommendation and execution:
- Input snapshot hash
- Agent version/model metadata
- Reasoning summary
- Trade decision outcome

Operational telemetry:
- Recommendation generation latency
- Simulation latency
- Execution success rate
- Delta between projected vs realized value over time

## 2.10 Suggested implementation phases

### Phase 1 (MVP)
- Schema + seed data
- Dashboard endpoint + UI
- Gap Finder heuristic rules (non-LLM)
- Opportunity Finder heuristic candidate generator
- Trade execution endpoint with transaction

### Phase 2
- Better ranking model
- Richer reasoning traces
- Chat panel for human-agent conversation
- Saved scenarios and comparison

### Phase 3
- Learning loop from accepted/rejected trades
- Calibration of confidence scores
- Multi-team negotiation simulation

## 2.11 Open decisions
- Confirm if value_score is static, model-derived, or manually curated
- Define league positional requirements (e.g., min defenders/midfielders/forwards)
- Confirm whether swap trades must be balanced by both teams
- Confirm budget rules (hard cap vs soft cap with penalty)

## 2.12 Example JSON payloads

### Opportunity example
{
  "opportunity_id": "opp_123",
  "type": "swap",
  "legs": [
    { "action": "swap_out", "player_id": "p_a", "transfer_cost": -2000000 },
    { "action": "swap_in", "player_id": "p_b", "transfer_cost": 1500000 }
  ],
  "projected_cost_delta": -500000,
  "projected_value_delta": 4.2,
  "post_trade_team_cost": 42500000,
  "post_trade_team_score": 78.4,
  "confidence": 0.74,
  "risks": ["small sample for new player performance"],
  "reasoning_summary": "Improves right-back value while lowering cost.",
  "reasoning_steps": [
    "Current right-back value is below league median.",
    "Incoming player has higher value-to-cost efficiency.",
    "Budget remains under cap after swap."
  ]
}

## 2.13 MVP technology recommendation
- Frontend: React + TypeScript + Vite + React Query + Tailwind
- Backend: Node.js + TypeScript + Fastify
- DB: PostgreSQL
- ORM/query: Prisma or Kysely
- Optional queue for async agent runs: BullMQ + Redis

This stack keeps delivery speed high for a hackathon while preserving a clean path to production hardening.
