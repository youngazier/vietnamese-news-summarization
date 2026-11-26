# Vietnamese News Summarization

A local, single-user Vietnamese news reader. It collects reviewed publisher RSS feeds, summarizes articles with a local ViT5 model, uses Gemini for category/keywords and review, stores everything in Supabase PostgreSQL, and shows it in a React UI.

This README covers setup and running only. For how the system works, see:

- [Architecture](docs/architecture.md) — overview and links to every spec in `docs/specs/`
- [Todos](docs/todos.md) — current status and open tasks
- [Docs index](docs/README.md) — specs, logs, decisions, archive

Run all commands from the repository root unless stated otherwise. Settings load `.env` from the current directory, so running backend commands inside `backend/` will miss it.

## 1. Prerequisites

- Git and [uv](https://docs.astral.sh/uv/getting-started/installation/) (uv installs Python 3.12)
- Node.js 22 and npm (frontend)
- Docker with Compose (optional, for the container workflow)
- A [Supabase](https://supabase.com/dashboard) project and a [Gemini API key](https://aistudio.google.com/apikey)

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh   # install uv on Linux/macOS
git --version && uv --version
node --version && npm --version
docker --version && docker compose version && docker info
```

`docker info` must show both Client and Server; otherwise see [Troubleshooting](#troubleshooting). No local PostgreSQL is needed.

## 2. Clone and install

```sh
git clone YOUR_REPOSITORY_URL vietnamese-news-summarization
cd vietnamese-news-summarization
uv python install 3.12
uv sync --locked --python 3.12
uv run --locked python --version      # 3.12.x

cd frontend && npm install && cd ..
```

`uv sync --locked` installs runtime and dev dependencies from `uv.lock` into `.venv`; no activation is needed with `uv run`. Use `uv sync --locked --no-dev` for a runtime-only environment. To change dependencies use `uv add`, `uv add --dev` or `uv remove`, and commit both `pyproject.toml` and `uv.lock`.

## 3. Create `.env`

```sh
if [ ! -e .env ]; then cp .env.example .env; fi
chmod 600 .env
git check-ignore .env      # should print .env
```

Fill in `DATABASE_URL` (step 4) and `GEMINI_API_KEY` / `GEMINI_MODEL` (step 5). Keep the template defaults for model paths and limits; all settings are described in the [backend spec](docs/specs/backend.md). Exported shell variables override `.env`; restart processes after changing it. Never commit `.env`.

## 4. Configure Supabase

1. Create a Supabase project with a strong database password (save it privately).
2. Open **Connect**, choose the PostgreSQL URI with **Session pooler** (port 5432, works over IPv4).
3. In `.env`, set `DATABASE_URL` from that URI:
   - change `postgresql://` to `postgresql+psycopg://`;
   - replace `[YOUR-PASSWORD]` with the percent-encoded password (`@`→`%40`, `#`→`%23`, `%`→`%25`);
   - append `?sslmode=require` (or `&sslmode=require` if parameters already exist).

```dotenv
DATABASE_URL="postgresql+psycopg://postgres.PROJECT_REF:ENCODED_PASSWORD@POOLER_HOST:5432/postgres?sslmode=require"
```

Use the database password, not a Supabase API key. Then check connectivity:

```sh
uv run --locked --env-file .env python -m app.db.probe
# Database probe successful: SELECT 1 returned 1.
```

### Migrations and seeding

```sh
uv run --locked alembic upgrade head
uv run --locked alembic current          # reports the latest revision (head)
uv run --locked python -m app.seed_sources
```

Use the committed Alembic revisions; never reinitialize Alembic or use `create_all()`. Seeding upserts sources from `config/sources.json` by RSS URL and is safe to rerun. VnExpress and Tuổi Trẻ are active; Thanh Niên is inactive. See the [database spec](docs/specs/database.md) and [source evidence](docs/specs/source-evidence.md).

## 5. Configure Gemini

```dotenv
GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
GEMINI_MODEL=gemini-3.8-flash
```

Verify access to your model with the live test (see [testing spec](docs/specs/testing.md)). The health endpoint and database probe do not need the key.

## 6. Download the ViT5 model (local runs)

`uv sync` does not download model weights. Download once with offline flags off:

```sh
export SUMMARIZATION_MODEL_PATH="$PWD/.models/vit5-base-vietnews-summarization"
HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 uv run --locked --env-file .env python download_summarization_model.py
```

At runtime the model loads only from local files. Never commit model files. The Docker image bakes the model in, so this step is only for running without Docker. See the [deployment spec](docs/specs/deployment.md).

## 7. Run locally

Use three terminals:

```sh
# API
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Worker (run at most one)
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked --env-file .env python -m app.worker

# Frontend
cd frontend && npm run dev
```

| URL | What |
| --- | --- |
| <http://127.0.0.1:5173> | Reader UI (Vite proxies `/api` to port 8000) |
| <http://127.0.0.1:8000/health> | API liveness (`{"status":"ok"}`, no DB needed) |
| <http://127.0.0.1:8000/docs> | Swagger UI |

The worker loads the model once, recovers unfinished jobs, polls every 10 idle seconds and schedules collection every 30 minutes. Useful API calls:

```sh
curl --fail http://127.0.0.1:8000/api/v1/sources
curl --fail 'http://127.0.0.1:8000/api/v1/articles?page=1&page_size=20'

# Start an ingestion job (202); use {} for all active sources
curl --fail-with-body -i -X POST http://127.0.0.1:8000/api/v1/ingestion-jobs \
  -H 'Content-Type: application/json' -d '{"source_id":1}'
curl --fail http://127.0.0.1:8000/api/v1/ingestion-jobs/JOB_ID
```

Manual CLI ingestion (no worker needed):

```sh
uv run --locked --env-file .env python -m app.cli.ingest --source-id 1 --verify-repeat
uv run --locked --env-file .env python -m app.cli.ingest --source-id 1 --prepare-only
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked --env-file .env \
  python -m app.cli.ingest --source-id SOURCE_ID --process-article-id ARTICLE_ID
```

Details: [ingestion spec](docs/specs/ingestion.md), [backend spec](docs/specs/backend.md), [summarization spec](docs/specs/summarization.md).

Frontend commands (from `frontend/`): `npm run lint`, `npm run build`, `npm run preview`.

## 8. Run with Docker Compose

```sh
docker compose build                                                 # bakes ViT5 into the image
docker compose run --rm api uv run --no-sync alembic upgrade head   # migrations first
docker compose up -d
docker compose ps
docker compose logs -f frontend api worker
docker compose down
```

Services: `frontend` (Nginx, <http://127.0.0.1:5173>, proxies `/api`), `api` (<http://127.0.0.1:8000>) and `worker` (no port). All ports bind to loopback. See the [deployment spec](docs/specs/deployment.md) for offline model checks.

## 9. Tests and checks

```sh
uv run --locked pytest -m "not integration" -q
uv run --locked --env-file .env pytest -m integration tests/integration -q --tb=no
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked --env-file .env pytest -m model tests/model -q
uv run --locked --env-file .env pytest -m live tests/live -q --tb=no
uv run --locked ruff check --line-length 100 backend tests
uv run --locked ruff format --check --line-length 100 backend tests
npm --prefix frontend run lint
npm --prefix frontend run build
uv build
```

Unit tests use fakes only. Integration tests need a database role that can create/drop schemas; each test uses its own `test_news_<uuid>` schema. Use `--tb=no` with real credentials. See the [testing spec](docs/specs/testing.md).

## Troubleshooting

| Problem | What to check |
| --- | --- |
| `uv` not found | Reopen the terminal; check the installer's PATH notes. |
| Wrong Python version | Repeat `uv sync --locked --python 3.12` from the repo root. |
| `DATABASE_URL is not set` / not configured | Run from the repo root (where `.env` is), or pass `--env-file .env` (`../.env` from `backend/`). |
| Probe asks for `postgresql+psycopg` | Change the URI scheme to `postgresql+psycopg://`. |
| Generic DB connection failure | Check host/username, password encoding, `sslmode`, project status; use the session pooler if IPv6 is unavailable. |
| `.env` edit seems ignored | An exported shell variable overrides it; unset it and restart. |
| Frontend `/api` network error | Make sure the API runs on `127.0.0.1:8000`. |
| Worker fails to load the model | Download it (step 6) and check `SUMMARIZATION_MODEL_PATH`. |
| Docker daemon unreachable | Start Docker Desktop or the Docker service. |
| Docker socket permission denied | See below. |

### Docker socket permissions on Linux

If `sudo docker info` works but `docker info` reports permission denied, add your user to the `docker` group:

```sh
sudo groupadd --force docker
sudo usermod -aG docker "$USER"
newgrp docker
docker info
docker run --rm hello-world
```

`newgrp` applies only to a child shell; log out and back in to apply it everywhere. The `docker` group grants root-level access; see [Docker's post-install guide](https://docs.docker.com/engine/install/linux-postinstall/).
