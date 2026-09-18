"""FastAPI application entrypoint.

    uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

Swagger UI at /docs, ReDoc at /redoc, OpenAPI JSON at /openapi.json.
Note that 0.0.0.0 is the BIND address -- clients call http://localhost:8000.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.v1.endpoints import health
from .api.v1.router import api_v1_router
from .core.config import get_settings
from .core.errors import register_exception_handlers
from .core.logging import configure_logging, get_logger, register_request_middleware
from .repositories.seed import demo_team_id, seed_store
from .repositories.store import get_store

logger = get_logger(__name__)

DESCRIPTION = """
Human-in-the-loop trade assistant for a soccer GM. Three agents analyse a squad,
propose trades, and execute the one the GM approves.

**Contract:** [api.md](https://github.com/) is the source of truth. Every object
below is defined once in section 3 and composed by the endpoints.

### The money model (D1)

Salary is the only money concept. Every player carries exactly one number,
`cost`. A team's cost is the sum of its roster's salaries. **A trade's cost is
the total salary coming on minus the total salary going off.** There is no
transfer fee and no acquisition price, which is what makes

    post_trade_metrics.team_cost == current_metrics.team_cost + projected_cost_delta

true by construction.

### Things worth knowing before you call anything

* **Clients never send prices** (D2). A trade leg is `{action, player_id}`; the
  server derives `cost_delta` from authoritative data.
* **`simulate` returns 200 even when the trade is invalid.** An invalid what-if
  is a successful simulation of an invalid trade, and the UI needs the violation
  list. Only `execute` turns a violation into a 409.
* **409 means a business rule failed. 422 means your JSON was malformed.** The
  split is deliberate -- FastAPI owns 422.
* **`roster_version` is an optimistic lock.** Thread it through
  find -> simulate -> execute; an opportunity generated against v17 cannot be
  executed once the roster reaches v18.
"""

TAGS_METADATA = [
    {"name": "Health", "description": "Liveness, build metadata, and live scoring weights."},
    {"name": "Teams", "description": "Stage 1 data: dashboard, roster, team list."},
    {"name": "Benchmarks", "description": "League averages per position."},
    {"name": "Market", "description": "Acquirable players."},
    {
        "name": "Gap Finder",
        "description": "Flags problem positions and players against league benchmarks.",
    },
    {
        "name": "Opportunity Finder",
        "description": "Generates and ranks candidate trades for a focus area.",
    },
    {"name": "Trader", "description": "Simulation and execution. The only mutating endpoint."},
    {"name": "Trades", "description": "Committed trade records and their reasoning traces."},
    {"name": "Insights", "description": "Persisted agent explainability trail."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    store = seed_store(get_store())
    logger.info(
        "seeded %s teams, %s players, %s listings | demo team_id=%s",
        len(store.teams),
        len(store.players),
        len(store.listings),
        demo_team_id(store),
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Soccer GM Trade Assistant API",
        version=settings.api_version,
        description=DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        lifespan=lifespan,
        contact={"name": "Hackathon team", "email": "taylor.schneider@us.gt.com"},
    )

    app.add_middleware(
        CORSMiddleware,
        # Never allow_origins=["*"], even in the demo (api.md section 7).
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id", "Idempotency-Replayed"],
    )

    register_request_middleware(app)
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(api_v1_router)

    return app


app = create_app()
