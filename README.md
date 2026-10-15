# Vietnamese News Summarization

A Vietnamese news reader being built with FastAPI, Supabase PostgreSQL, local ViT5 summarization, and Gemini metadata/review. The planned reader collects reviewed publisher RSS feeds and displays approved summaries through a React interface.

The repository currently provides a Python project, a working health endpoint, three database-backed read endpoints, environment configuration, a database connection probe, SQLAlchemy models, a lazy session factory, and Alembic revisions through `0002`. Manual RSS collection, deduplicated persistence, gated HTML extraction, RSS fallback and source-text quality labeling are implemented through Day 4. Day 5 adds local CPU ViT5 inference, Gemini structured metadata and a draft node; see the [model setup and verification guide](docs/day-5-model.md). The committed publisher configuration keeps article extraction and AI processing disabled under its current reviews; permitted RSS excerpts supply normal ingestion text. A separate user-authorized full-text test verified Day 6 approval and REST visibility. Day 6 adds a source-based review graph with at most two drafts and atomic, replay-safe summary persistence; see the [review and persistence guide](docs/day-6-review.md). Day 7 adds durable job submission/polling, the standalone worker, atomic counters, restart recovery and scheduling; see the [worker guide](docs/day-7-worker.md). The frontend and application containers remain unfinished.

This tutorial walks through the setup available today: install the project, run the API, create a Supabase project, configure its database connection, and prepare a Gemini API key. Commands run from the repository root unless stated otherwise. Shell examples use Bash or Zsh on Linux/macOS; Windows users can use WSL or adapt file commands to PowerShell.

## 1. Install the prerequisites

You need Git and [uv](https://docs.astral.sh/uv/getting-started/installation/) to install and run the Python project. uv manages Python and the virtual environment.

Install uv on Linux/macOS:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Reopen your terminal and verify:

```sh
git --version
uv --version
```

Python 3.12 is selected by this repository. The next step installs it through uv if needed.

Node/npm and Docker are needed for later frontend and container work. You can prepare them now using the [Node.js download instructions](https://nodejs.org/en/download) and [Docker installation guide](https://docs.docker.com/engine/install/). Choose a supported Node LTS release; check the frontend's version requirements once it is available.

```sh
node --version
npm --version
docker --version
docker compose version
docker info
```

`docker info` should display both Client and Server information. CLI version output alone does not confirm daemon access. On macOS/Windows, start Docker Desktop before running this check. No local PostgreSQL installation is needed: this project uses hosted Supabase PostgreSQL.

## 2. Download and install the repository

Clone this repository using its HTTPS or SSH URL from GitHub's **Code** menu. Replace `YOUR_REPOSITORY_URL` below with that URL:

```sh
git clone YOUR_REPOSITORY_URL vietnamese-news-summarization
cd vietnamese-news-summarization
uv python install 3.12
uv sync --locked --python 3.12
uv run --locked python --version
```

Expected Python version: `3.12.x`. `uv sync` creates `.venv` and installs the dependencies recorded in `uv.lock`, including development tools. The current dependency set includes AI libraries, so the first installation can require substantial download time and disk space.

You do not need to activate `.venv` when using `uv run`. Dependencies and package layout are already configured in `pyproject.toml`; normal installation only needs `uv sync --locked`.

### Python libraries and how they are installed

`uv sync --locked` installs all declared runtime libraries and the default development group. You do not need separate `pip install` commands. [pyproject.toml](pyproject.toml) declares requirements; `uv.lock` records the resolved versions.

| Area | Libraries | Purpose |
| --- | --- | --- |
| API and settings | `fastapi`, `uvicorn`, `pydantic-settings` | HTTP routes, development server, environment configuration; Pydantic is installed transitively |
| Database — D2 | `sqlalchemy`, `psycopg[binary]`, `alembic` | ORM/sessions, PostgreSQL driver, schema migrations |
| RSS and extraction — D3–D4 | `httpx`, `feedparser`, `beautifulsoup4` | Bounded HTTP requests, RSS parsing, gated HTML extraction and text cleanup |
| Local summarization — D5 | CPU `torch`, `transformers`, `sentencepiece` | Offline ViT5 inference and tokenization |
| AI workflow — D5–D6 | `google-genai`, `langgraph`, `langchain-google-genai` | Implemented metadata/draft/review graph; optional installed LangChain adapter |
| Scheduling — D7 | `apscheduler` | Standalone worker enqueue timer |
| Development | `pytest`, `httpx`, `ruff` | Tests, HTTP test client dependency, formatting/linting |

### Install dependencies after cloning

Run from the repository root:

```sh
uv sync --locked
```

uv reads [pyproject.toml](pyproject.toml) and [uv.lock](uv.lock), creates `.venv` if needed, and installs the local `app` package plus runtime and development dependencies. `--locked` requires the lockfile to match the project declarations rather than silently changing it. Run the same command after pulling dependency changes.

For a runtime-only environment, omit the development group:

```sh
uv sync --locked --no-dev
```

Use the default sync for development and tests. Model weights are downloaded separately in the model phase.

### Add or remove libraries while developing

These commands are for changing project dependencies; users cloning the project only need the sync command above.

```sh
# Replace LIBRARY_NAME with the package you need.
uv add LIBRARY_NAME

# Add a development tool.
uv add --dev DEVELOPMENT_LIBRARY

# Version ranges must be quoted in the shell.
uv add 'PACKAGE_NAME>=1,<2'

# Remove a runtime dependency.
uv remove LIBRARY_NAME
```

uv updates `pyproject.toml`, `uv.lock`, and the environment. Commit both dependency files after changes so other users can reproduce the installation. The library table includes later phases; installing dependencies does not implement those features.

## 3. Create your environment file

Copy the template only if `.env` does not already exist:

```sh
if [ ! -e .env ]; then
  cp .env.example .env
fi
chmod 600 .env
git check-ignore .env
```

The last command should print `.env`: the repository's ignore rules already exclude it. Edit this file locally and keep `.env.example` free of real credentials.

For now, keep the template's model paths and processing limits. Database and Gemini credentials are configured in the following steps. The API health endpoint works with these credentials left empty.

Application settings load `.env` from the current working directory. Run commands from the repository root. Environment variables already exported in your shell take precedence; restart running processes after changing configuration.

## 4. Run the API before connecting external services

Start the development server:

```sh
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

In another terminal, request the health endpoint:

```sh
curl --fail http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

Interactive API documentation is available at <http://127.0.0.1:8000/docs>. The server binds to loopback for local access. Stop it with Ctrl+C.

`/health` confirms that the API is running. It intentionally does not connect to Supabase, call Gemini, or load an AI model.

## 5. Create a Supabase project

1. Sign in at [Supabase](https://supabase.com/dashboard) and create a new project in your organization.
2. Choose a project name, a region suitable for your location, and a strong database password. Save that password privately; it is needed for the PostgreSQL connection.
3. If offered, select **Enable automatic RLS**. Row Level Security restricts ordinary table access unless policies permit it. Table owners normally bypass RLS unless it is forced; roles with `BYPASSRLS` also bypass it. The backend setup below uses the privileged `postgres` account. [Supabase RLS guide](https://supabase.com/docs/guides/database/postgres/row-level-security).
4. Wait until the project is ready, then open **Connect**.

The application design routes browser requests through FastAPI. Store database credentials only in the backend environment file. No browser Supabase client or user-authentication policies are required for the current setup.

### Select the PostgreSQL connection

In the Connect dialog, open the PostgreSQL connection-string view (the **Direct** tab in the current dashboard), select **URI** if offered, and choose **Session pooler** as the method.

Session pooling works over IPv4 and is a practical choice for local development. Direct connections are also suitable when your network supports the endpoint's IPv6 connectivity or the project has the IPv4 add-on. This repository's setup uses session pooling on port **5432**. [Supabase connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres).

Copy the URI shown by the dashboard. A session-pooler URI has this general shape:

```text
postgresql://postgres.PROJECT_REF:[YOUR-PASSWORD]@POOLER_HOST:5432/postgres
```

Keep the exact username and host from your project's URI. Pooler hosts cannot reliably be inferred from the project region.

### Configure DATABASE_URL

In `.env`, set the copied URI with these changes:

- Replace `postgresql://` with `postgresql+psycopg://`, matching the installed SQLAlchemy driver.
- Replace `[YOUR-PASSWORD]` with your database password, percent-encoding reserved characters. For example, `@` becomes `%40`, `#` becomes `%23`, and `%` becomes `%25`.
- Add `?sslmode=require` to require an encrypted connection. If query parameters already exist, use `&sslmode=require` instead. Full certificate verification additionally requires `verify-full` and the Supabase root certificate, as described in the connection guide.

Example with placeholders:

```dotenv
DATABASE_URL="postgresql+psycopg://postgres.PROJECT_REF:ENCODED_PASSWORD@POOLER_HOST:5432/postgres?sslmode=require"
```

Use the database password, not a Supabase publishable, secret, or service-role API key. The Framework, ORM, and MCP examples are not required to configure the existing Python database probe.

### Verify the database connection

Run:

```sh
uv run --locked --env-file .env python -m app.db.probe
```

Expected output and exit status:

```text
Database probe successful: SELECT 1 returned 1.
```

The command exits with code `0` on success. It makes a real connection, runs `SELECT 1`, then closes the connection. Failures use a generic message to avoid exposing credentials.

This verifies connectivity only. To create the application tables, apply the existing migration next.

### Apply the database migration

Progress as of 2026-10-14: Day 2 is complete through D2.12. The read API provides source, article-list, and article-detail responses with title search, source/category filters, stable ordering, pagination, approved-summary visibility, and redacted database-outage responses. Repeatable source seeding and the full Day 2 hosted PostgreSQL suite are verified.

Run Alembic commands from the repository root. `[tool.alembic]` in `pyproject.toml` points to `backend/alembic`, so the normal commands below still work without `-c`. Logging configuration lives in `backend/alembic.ini`; credentials still come from root `.env`. To explicitly select the backend INI, use `uv run --locked alembic -c backend/alembic.ini current`. Both configurations find migrations relative to their configuration file using `%(here)s`.

The repository already includes the Alembic environment, revision `0001` for the initial schema, and revision `0002` to rename `summaries.model_name` to `summaries.summarize_model_name` without losing data. On a fresh checkout, use these revisions directly; do not reinitialize Alembic or regenerate them.

```sh
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic upgrade head
```

Expected: `current` reports `0002 (head)` and the repeated upgrade makes no changes. Revision `0001` creates `sources`, `articles`, `summaries`, and `ingestion_jobs`; revision `0002` performs the summarization-model column rename. Alembic keeps the applied revision in `alembic_version`. Configuration comes from root `.env`; `backend/alembic.ini` contains no database credentials.

This setup uses the Supabase session pooler on port 5432. The developer reported the initial migration and hosted constraint/lifecycle tests working. Revision `0002` and its data-preserving upgrade/downgrade/re-upgrade path are covered by the migration tests.

### Seed source configuration

The seed command upserts sources by unique RSS URL, so rerunning it does not create duplicates:

```sh
uv run --locked python -m app.seed_sources
```

Source settings and dated review evidence live in `config/sources.json`. The command validates the complete file before connecting, then upserts name, RSS URL and active status. VnExpress and Tuổi Trẻ are active for attributed personal RSS-reader use; Thanh Niên remains inactive pending reuse clarification. Extraction and AI processing remain disabled for all three. Seeding does not fetch RSS or generate summaries. Run from the repository root, or pass `--config /path/to/sources.json`.

### Read sources and articles

Start the API, then call the read endpoints from another terminal:

```sh
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

curl --fail http://127.0.0.1:8000/api/v1/sources
curl --fail 'http://127.0.0.1:8000/api/v1/articles?page=1&page_size=20'
curl --fail 'http://127.0.0.1:8000/api/v1/articles?q=th%E1%BB%AD&page=1&page_size=20'
```

Use an ID returned by the list endpoint for `GET /api/v1/articles/{id}`. Empty application tables legitimately return `[]` for sources and an article page with `items: []`. D2.10 verified nonempty source/list/detail responses using a fictional article in a disposable PostgreSQL schema.

Relevant checks:

```sh
uv run --locked pytest tests/test_health.py tests/test_config.py tests/test_db_session.py -q
uv run --locked pytest -m integration tests/integration/test_migrations.py tests/integration/test_persistence.py tests/integration/test_api.py tests/integration/test_seed_sources.py -q
```

Verified on 2026-10-14: the unit suite above passed **37 tests**, and the complete Day 2 hosted PostgreSQL suite passed **44 tests**. The API portion includes 14 cases covering source visibility/order, literal wildcard search, combined filters and matching totals, stable pagination, 404/422/503 responses, preview limits, and approved/rejected summary visibility.

## 6. Prepare a Gemini API key

1. Open [Google AI Studio's API key page](https://aistudio.google.com/apikey).
2. Follow the prompts to select or create a Google Cloud project and create a Gemini API key.
3. Save it in `.env` using this exact setting name:

```dotenv
GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
GEMINI_MODEL=gemini-3.8-flash
```

See Google's [Gemini API key guide](https://ai.google.dev/gemini-api/docs/api-key) for account and key setup.

The development account verified `gemini-3.8-flash` through the Interactions API on 2026-10-15. Verify your own account with the explicit live test in the [Day 5 guide](docs/day-5-model.md). Calls use `store=False` and validate category/keywords against a Pydantic schema. Saving a key alone does not prove access. The health endpoint and database probe do not require the key.

## 7. Understand the configuration defaults

| Setting | Purpose | Template value |
| --- | --- | --- |
| `DATABASE_URL` | Supabase SQLAlchemy/psycopg connection | Empty; configure in step 5 |
| `GEMINI_API_KEY` | Private Gemini key | Empty; configure in step 6 |
| `GEMINI_MODEL` | Developer API metadata model | `gemini-3.8-flash`; verify account access |
| `SUMMARIZATION_MODEL_ID` | ViT5 model repository and manifest identity | `VietAI/vit5-base-vietnews-summarization` |
| `SUMMARIZATION_MODEL_PATH` | Local artifact directory | `.models/vit5-base-vietnews-summarization` |
| `SUMMARIZATION_CPU_THREADS` | CPU inference threads, validated range 1–32 | `4` |
| `COLLECTION_INTERVAL_MINUTES` | Planned collection interval | `30` |
| `WORKER_POLL_INTERVAL_SECONDS` | Idle worker polling | `10` |
| `JOB_MAX_ARTICLE_INSERTIONS` | Planned per-job insertion limit | `20` |
| `JOB_MAX_ARTICLE_RESULTS` | Text preparation batch limit; later per-job processing limit | `20` |
| `MAX_JOB_BACKLOG` | Planned pending-job limit | `5` |
| `MAX_GRAPH_DRAFT_ATTEMPTS` | Maximum summary drafts; validated range 1–2 | `2` |
| `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE` | Offline runtime flags; set to 0 only for download | `1` |
| `LOG_LEVEL` | Reserved logging configuration | `INFO` |

Processing settings are declared, validated and used by the standalone worker. `uv sync` does not download model artifacts: run the explicit downloader in the [Day 5 guide](docs/day-5-model.md). Runtime loading validates the model manifest and uses only local files. `LOG_LEVEL` is present in the template but is not currently wired into application logging.

## 8. Verify the API and settings

Run the existing tests:

```sh
uv run --locked pytest tests/test_health.py tests/test_config.py tests/test_db_session.py -q
```

The complete unit regression run on 2026-10-15 passed **187 tests**, with three model/live cases skipped by default and 60 database cases deselected (`pytest -m "not integration" -q`). Unit tests use fakes for external services. The existing FastAPI TestClient test required execution outside this session's restricted sandbox. Real model and Gemini checks are selected separately in the [Day 5 guide](docs/day-5-model.md); PostgreSQL connectivity has its own probe and integration suite.

The publisher review is recorded in [source-evidence.md](docs/source-evidence.md). It includes official RSS URLs for VnExpress, Tuổi Trẻ, and Thanh Niên, live XML checks, attribution conditions, and unresolved reuse/AI-processing questions. Source configuration, JSON-backed seeding, collection and Day 4 text preparation are implemented. D3.1 still awaits Thanh Niên reuse clearance.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| `uv` is not found | Reopen the terminal after installation and check the installer instructions for PATH configuration. |
| Wrong Python version | Run from the repository root and repeat `uv sync --locked --python 3.12`. |
| `DATABASE_URL is not configured` | Save the URL in root `.env` and run the probe with `--env-file .env`. |
| Probe says to use `postgresql+psycopg` | Change the copied URI's scheme to `postgresql+psycopg://`. |
| `sqlalchemy.dialects:driver` error | Use the committed Alembic environment; it reads DATABASE_URL instead of the generated INI placeholder. |
| Duplicate enum CHECK during migration | Use the corrected revision 0001, which declares each enum CHECK once. |
| Generic database connection failure | Check the exact host/username, database password encoding, TLS settings, project availability, and network access. Use session pooling if direct IPv6 is unavailable. |
| Edited `.env` appears ignored | Check for an old exported environment variable overriding it, then restart the application. |
| Docker socket permission denied on Linux | Verify with `sudo docker info`, then follow the group-access steps below if it succeeds. |
| Docker daemon cannot be reached | Start Docker Desktop, or check the Docker service on Linux. |

### Docker socket permissions on Linux

If `sudo docker info` succeeds but `docker info` reports permission denied, you can grant your user access through the `docker` group:

```sh
sudo groupadd --force docker
sudo usermod -aG docker "$USER"
newgrp docker
docker info
docker run --rm hello-world
```

`newgrp` activates the group in a child shell. Log out completely and back in to apply membership throughout your login session. Membership grants root-level privileges; see [Docker's Linux post-installation guide](https://docs.docker.com/engine/install/linux-postinstall/).

## Continue with the project

After these steps, you can run the API, verify its configuration tests, and test connectivity to your own Supabase database. Use the [Day 5 guide](docs/day-5-model.md) to download ViT5 and exercise actual local generation and Gemini metadata.

For the implemented database setup and remaining integration tests/article API, see the [database setup guide](docs/day-2-setup.md). The [architecture](docs/architecture.md) explains the intended system, and the [implementation checklist](docs/todos.md) tracks unfinished features. This README will expand as those features become available.

### Manual RSS collection and text preparation (D3–D4)

Run from the repository root with migrations applied and sources seeded. Find an
active source ID using `GET /api/v1/sources`, then run:

```sh
uv run --locked --env-file .env python -m app.services.ingestion --source-id 1 --verify-repeat
uv run --locked --env-file .env pytest -m integration tests/integration/test_ingestion.py -q
```

The collector fetches one reviewed active feed before opening the write transaction.
Insertion uses PostgreSQL canonical-URL uniqueness and `ON CONFLICT DO NOTHING
RETURNING id`. Each run inserts at most `JOB_MAX_ARTICLE_INSERTIONS` (default 20);
duplicates do not consume insertion capacity and existing article data stays unchanged.
RSS descriptions are stored as cleaned metadata. After insertion, a separate bounded
step prepares the oldest pending articles, including older rows absent from the feed.
Usable text stays `pending`; text shorter than 200 characters or missing text becomes
`needs_review`, with a redacted reason stored in `processing_error`.

`--verify-repeat` replays the same attempted entries after the first commit. It must
report zero repeated insertions. A separate fresh collection may add previously
unprocessed or newly published articles. Output reports inserted IDs, duplicate and
examined counts. Successful fetch/persistence updates `last_fetched_at` atomically.

Verified on 2026-10-14: VnExpress source 1 yielded 51 usable entries, inserted 20,
and replayed 20 duplicates with zero new inserts. Real loopback REST source/list/detail
checks returned HTTP 200, source total 20 and article 1 pending without a summary.
Five hosted PostgreSQL ingestion tests passed in disposable schemas; the complete
unit/hosted PostgreSQL regression suite passed 127 tests. Focused lint checks passed
with EXE002 ignored for the existing filesystem permissions limitation. D3.1 still
awaits Thanh Niên reuse clearance; live article extraction and AI processing remain disabled.

To label existing pending rows without collecting another feed, run:

```sh
uv run --locked --env-file .env python -m app.services.ingestion --source-id 1 --prepare-only
uv run --locked pytest tests/test_extractor.py tests/test_collector.py -q
```

Text is capped at 20,000 characters and records `extracted` or `rss_excerpt` provenance;
missing text keeps a NULL origin. The current reviews allow RSS fallback for the two
active sources. The extractor makes no article request while extraction is disabled.
Already prepared pending rows and terminal/in-progress articles are unchanged on replay.
Publisher IO runs outside database transactions, and each guarded result commits separately.

Verified on 2026-10-15: the existing 20 VnExpress articles were labeled from stored RSS
excerpts (1 pending, 19 needs review). A second preparation changed zero rows. A live
RSS-only check found 2/51 VnExpress and 6/50 Tuổi Trẻ excerpts met the provisional
200-character threshold. Length alone does not establish factual completeness or AI
permission. See the [Day 4 guide](docs/day-4-extraction.md) for limits, source gates,
fixtures, and verification details.

Day 4 regression: **184 tests passed**, including **60 hosted PostgreSQL integration
cases**. Package build and focused lint/format checks passed; repository-wide lint
and formatting retain pre-existing issues documented in the guide.


### Review and persist one eligible article (Day 6)

Day 6 adds source-only Gemini review, a LangGraph loop with at most two ViT5 drafts,
and atomic, replay-safe summary/status persistence. The final regression passed
**233 unit tests**, **80 hosted PostgreSQL tests** and **two real Gemini tests**.
Focused lint/format checks and package build pass; older repository-wide Ruff
issues remain. See [Day 6 setup, commands and evidence](docs/day-6-review.md).

The user-selected VnExpress RSS check processed stored article 5 using real ViT5
and Gemini. Both drafts were rejected for unsupported content; it is saved as
`needs_review`, its candidate stays hidden through REST, and replay changes nothing.
The user then authorized a linked public full-text article from the World feed.
Article **41** (source **4**) passed real local ViT5/Gemini review and is saved as
`ready`. HTTP detail and combined list filters return its approved summary; replay
changes nothing. A transient provider failure required one controlled manual retry;
the completed run used one draft. **Day 6 is complete.** Normal publisher AI settings
remain disabled; use an explicitly reviewed source configuration for single-article
processing. Day 7 connects this pipeline to durable jobs and scheduling.


### Manual jobs and the standalone worker (Day 7)

Start the API and worker in separate terminals with the configured root `.env`:

```sh
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked --env-file .env python -m app.worker
```

The worker loads the local model once, recovers abandoned work and polls durable
jobs every ten idle seconds. Run only one worker; stop it before starting another.
The API submits work without loading a model or contacting a publisher/provider.

```sh
curl --fail-with-body -i -X POST http://127.0.0.1:8000/api/v1/ingestion-jobs \
  -H 'Content-Type: application/json' -d '{"source_id":1}'
# Replace JOB_ID with the returned integer:
curl --fail http://127.0.0.1:8000/api/v1/ingestion-jobs/JOB_ID
```

Use `{}` or `{"source_id":null}` for all active sources. POST returns 202/pending;
GET returns durable status, counters and timestamps. The default backlog cap is
five pending/running jobs. A UTC timer enqueues every 30 minutes and suppresses
another scheduled job while one remains pending/running. SIGTERM/SIGINT stops
new work; the next worker startup recovers unfinished processing.

The committed source flags still disable publisher extraction and AI. Usable RSS
text stays pending for an eligible AI policy; insufficient text becomes
needs_review without inference. See the [Day 7 guide](docs/day-7-worker.md) for
transaction boundaries, failures, limits and verification evidence.
