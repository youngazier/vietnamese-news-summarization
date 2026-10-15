# Agent Guidelines

Read this file first at the start of every chat session, before taking any other steps.
Keep changes simple and focused. Consult linked docs when needed rather than copying them here.

## 1. Project Structure & Module Organization

```text
backend/
  app/          # FastAPI entrypoint, API routes, settings, DB sessions, and models
  alembic/      # Database migration environment and revisions
tests/          # Unit tests and PostgreSQL integration tests
docs/           # Architecture, implementation plan, and setup guides
frontend/       # Planned React application
pyproject.toml  # Python dependencies, packaging, and tool configuration
uv.lock         # Locked Python dependencies
.env.example    # Configuration template without secrets
```

Within `backend/app`, use `api/` for handlers, `core/` for settings, `db/` for database
connections, and `models/` for SQLAlchemy models. Add `services/` for reusable logic
and `agents/` for the planned AI workflow as needed; avoid unnecessary empty modules.

| Area | Stack | Purpose |
| --- | --- | --- |
| Frontend (planned) | React, Vite, TypeScript | Vietnamese news reader |
| Backend | Python 3.12, FastAPI, Pydantic, Uvicorn | API and configuration |
| Database | Supabase PostgreSQL, SQLAlchemy, psycopg, Alembic | Persistence and migrations |
| Summarization (planned) | Local ViT5, Transformers, PyTorch, SentencePiece | Vietnamese summaries |
| AI workflow (planned) | LangGraph, Gemini via `google-genai` | Metadata, review, bounded retries |
| Collection (planned) | httpx, feedparser, BeautifulSoup, APScheduler 3.x | RSS, extraction, scheduling |
| Containers (planned) | Docker, Docker Compose | Separate API and worker processes |
| Development | uv, pytest, Ruff | Dependencies, tests, linting, formatting |

See [docs/architecture.md](docs/architecture.md) for design details and
[docs/todos.md](docs/todos.md) for implementation progress. Article APIs, ingestion,
AI processing, frontend, and containers are not implemented yet.

## 2. Build, Test, and Development Commands

Run commands from the repository root. Copy `.env.example` to `.env` if `.env` does
not exist, then configure credentials locally. Never commit secrets.

### Frontend

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

Set `DATABASE_URL` in root `.env` using `postgresql+psycopg://` and TLS.
The database is hosted on Supabase; there is no local database build step.

```sh
uv run --locked --env-file .env python -m app.db.probe
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked pytest -m integration tests/integration -q
```

Use the existing Alembic setup and migrations; do not reinitialize them or use
`create_all()` for application setup. Add a new revision for later schema changes.
See [docs/day-2-setup.md](docs/day-2-setup.md) for database setup details.

## 3. Coding Style & Naming Conventions

### Frontend

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
