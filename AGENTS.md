# Agent Guidelines

Read this file first at the start of every chat session, before taking any other steps.
Keep changes simple and focused. Consult linked docs when needed rather than copying them here.

## Environment Files and Secrets

- Never open, read, search, or print `.env` or secret-bearing `.env.*` files, including
  through scripts or tools. Use `.env.example` as the configuration reference instead.
- Do not expose secrets indirectly through environment dumps, settings objects, database
  connection details, logs, or test tracebacks. For tests using real credentials, use
  `--tb=no` and never use `--showlocals`.
- Applications may load their existing configuration during normal execution, but agents
  must not inspect or display its secret values. Leave credential setup to the user.
- Never commit secrets.

## 1. Project Structure & Module Organization

```text
backend/
  app/
    api/        # FastAPI route handlers (articles, sources, ingestion_jobs)
    core/       # Application settings and configuration
    db/         # Database engine/session management and connection probe
    models/     # SQLAlchemy models and enums
    services/   # Ingestion, RSS collection, extraction, summarization, Gemini, and job services
    agents/     # LangGraph AI workflow (graph, nodes, prompts, schemas, state)
    main.py     # FastAPI entrypoint
    schemas.py  # Shared Pydantic API schemas
    seed_sources.py  # Seed script for news sources
    worker.py   # Background scheduler/worker entrypoint
  alembic/      # Database migration environment and revisions
  Dockerfile    # Backend API and worker container image
tests/          # Unit, integration (PostgreSQL), model, and live tests
docs/           # Architecture, implementation plan, and setup guides
frontend/       # React, Vite, TypeScript web application (see frontend/AGENTS.md)
compose.yaml    # Docker Compose setup for frontend, api, and worker
pyproject.toml  # Python dependencies, packaging, and tool configuration
uv.lock         # Locked Python dependencies
.env.example    # Configuration template without secrets
```

Within `backend/app`, `api/` holds thin route handlers, `core/` holds settings, `db/`
manages database connections, `models/` defines SQLAlchemy models, `services/` holds
reusable business logic (RSS collection, article extraction, image handling, local ViT5
summarization, Gemini integration, ingestion, and job management), and `agents/` implements
the LangGraph AI workflow. Top-level app modules include `main.py` (FastAPI app),
`schemas.py` (shared API schemas), `seed_sources.py` (source seeding), and `worker.py`
(APScheduler background worker).

| Area | Stack | Purpose |
| --- | --- | --- |
| Frontend | React, Vite, TypeScript, Tailwind CSS v4, shadcn/ui | Vietnamese news reader |
| Backend | Python 3.12, FastAPI, Pydantic, Uvicorn | API and configuration |
| Database | Supabase PostgreSQL, SQLAlchemy, psycopg, Alembic | Persistence and migrations |
| Summarization | Local ViT5, Transformers, PyTorch, SentencePiece | Vietnamese summaries |
| AI workflow | LangGraph, Gemini via `google-genai` | Metadata, review, bounded retries |
| Collection | httpx, feedparser, BeautifulSoup, APScheduler 3.x | RSS, extraction, scheduling |
| Containers | Docker, Docker Compose | Separate frontend, API, and worker processes |
| Development | uv, pytest, Ruff, npm, ESLint | Dependencies, tests, linting, formatting |

See [docs/architecture.md](docs/architecture.md) for design details,
[docs/todos.md](docs/todos.md) for implementation progress, and
[frontend/AGENTS.md](frontend/AGENTS.md) for frontend-specific agent guidelines.

## 2. Build, Test, and Development Commands

Run commands from the repository root. The user configures local credentials in `.env`
using `.env.example` as a template; agents must follow the environment-file rules above.

### Frontend

See [frontend/AGENTS.md](frontend/AGENTS.md) for full frontend guidelines. Run frontend
commands from `frontend/`:

```sh
cd frontend
npm install
npm run dev
npm run lint
npm run build
```

For containerized full-stack runs (`frontend`, `api`, `worker`), use `docker compose up --build`
from the repository root (see [compose.yaml](compose.yaml)).

### Backend

```sh
uv sync --locked --python 3.12
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
uv build
uv run --locked pytest -m "not integration" -q
uv run --locked ruff check --line-length 100 backend tests
uv run --locked ruff format --check --line-length 100 backend tests
```

Check API liveness with `curl --fail http://127.0.0.1:8000/health`.
Use `uv add` or `uv add --dev` for dependency changes; keep `pyproject.toml` and
`uv.lock` in sync. Omit `--check` from the format command to apply formatting.

### Database

The user sets `DATABASE_URL` in root `.env` using `postgresql+psycopg://` and TLS.
The database is hosted on Supabase; there is no local database build step.

```sh
uv run --locked --env-file .env python -m app.db.probe
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked pytest -m integration tests/integration -q --tb=no
```

Use the existing Alembic setup and migrations; do not reinitialize them or use
`create_all()` for application setup. Add a new revision for later schema changes.
See [docs/day-2-setup.md](docs/day-2-setup.md) for database setup details.

## 3. Coding Style & Naming Conventions

### Frontend

- Use React, Vite, TypeScript, Tailwind CSS v4, and shadcn/ui with Base UI.
- Follow the conventions in [frontend/AGENTS.md](frontend/AGENTS.md) (separate page
  composition, reusable components, and data/API modules; semantic HTML; mobile-first
  layouts; Vietnamese UI copy).

### Backend

- Use 4-space indentation, `snake_case` for functions and variables, and `PascalCase` for classes.
- Add type hints and follow Ruff's 100-character line limit.
- Keep API handlers thin and place reusable logic in services.

## 4. Testing Guidelines

- Use pytest; name files `test_*.py` and tests `test_*`.
- Unit tests cover health, settings validation, lazy engine/session creation, and cleanup.
  Keep them independent of live databases, publishers, Gemini, and model downloads.
- Mark real PostgreSQL tests with `integration` and place them in `tests/integration/`.
  Use a configured development database with permission to create/drop schemas.
- Reuse the existing fixtures: each test owns a generated `test_news_<uuid>` schema,
  runs migrations and sessions on the same connection, and cleans up only that schema.
  Never run test downgrades against `public` or application tables; use PostgreSQL, not SQLite.
- Verify migration upgrade/repeated upgrade/downgrade/re-upgrade, persistence, uniqueness,
  foreign keys, checks, and transaction rollback when changing database behavior.
- Run tests relevant to the change. Report skipped or unavailable integration checks
  separately; unit test success does not prove live connectivity.

## 5. Commit & Pull Request Guidelines
