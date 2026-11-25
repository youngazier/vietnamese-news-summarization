# Day 2 guide: save an article in PostgreSQL and read it through FastAPI

Updated: 2026-10-15. D2.1–D2.12 remain complete. This guide records the Day 2 state; D3.2–D3.9 have since added source configuration, RSS collection and deduplicated persistence. See [todos.md](todos.md) for current progress.

**Your goal today:** create the project's database tables in Supabase, save a test article, and return it through these three endpoints:

```text
GET /api/v1/sources
GET /api/v1/articles
GET /api/v1/articles/{id}
```

You do not need RSS fetching, AI summarization, a worker, or a frontend to finish Day 2. Use a made-up article to prove the database and API work together.

This is a guide for implementing the remaining tasks, not a claim that they already work. Every command below runs from the repository root. Sections marked **Run now** use existing code. Sections marked **Implement first** require you to write the listed files before running their checks.

## 1. Understand what you are building

The request path will be:

```text
curl or browser → FastAPI route → database session → Supabase PostgreSQL
                   ↓
             JSON response
```

| Term | Meaning in this project |
| --- | --- |
| PostgreSQL | The database that stores your rows. Supabase hosts it for you. |
| SQLAlchemy model | A Python class describing a table and letting you work with rows as objects. The existing models do not create tables by themselves. |
| Engine | SQLAlchemy's connection manager. It keeps a small pool of reusable database connections. |
| Session | A short-lived workspace for queries and changes. Each request gets its own session. |
| Transaction | Changes that succeed together when committed, or are undone together when rolled back. Closing a session does not commit your changes. |
| Alembic migration | A versioned Python script that changes the actual database structure. |
| Constraint | A database rule, such as refusing two articles with the same canonical URL. |
| Pydantic response schema | The fields FastAPI is allowed to return as JSON. It is different from a database model. |
| Fixture | Made-up test data with known values. It lets you test without fetching real news. |
| Disposable schema | A temporary namespace inside PostgreSQL that holds test tables separately from application tables. |

The four existing tables describe:

- `sources`: publishers/feed addresses. One source can have many articles.
- `articles`: titles, URLs, source text, and processing status. Each article belongs to one source.
- `summaries`: an article's summary and review result. An article can have at most one summary.
- `ingestion_jobs`: records of collection/processing runs, used in later days.

For example, `Article.source_id` points to `Source.id`. That is a **foreign key**: PostgreSQL must reject an article whose source does not exist. `Article.source` is the Python relationship used to access that source object.

## 2. Know your starting point

The repository was inspected for this guide. Current status:

| Task | Status | What you still need to do |
| --- | --- | --- |
| D2.1: dependencies and models | Implemented | Verify imports below; do not recreate the models or reinstall Alembic. |
| D2.2: relationships and database rules | Complete; hosted tests reported passing | Keep the enforcement tests for future migrations. |
| D2.3: sessions | Complete | 14 session tests; previous full foundation run: 37 passed. |
| D2.4–D2.5: migrations | Complete; upgrade reported working | Keep the committed environment/revision; verify current/head and repeated upgrade on each setup. |
| D2.6–D2.7: database tests | Complete; developer reports passing | Fixtures and migration/persistence tests exist. |
| D2.8–D2.9: read API | Implemented | Source/list/detail routes, visibility rules, search, filters, ordering, totals, and pagination exist. |
| D2.10: source seed and fixture | Implemented; PostgreSQL checks passed | Repeatable inactive candidate seeding; fictional fixture returned by all three endpoints. |
| D2.11: API tests | Complete; 14 API cases passed | Covers filters/order/page, 404/422/503, redaction, and summary visibility. |
| D2.12: setup record | Complete | README records session-pooler mode, head `0002`, seeding, read commands, and final results. |

Follow the steps below in order. Tick tasks in [todos.md](todos.md#phase-2--day-2-database-to-rest) only after their checks pass.

### Run now: verify the existing foundation

```sh
uv sync --locked --python 3.12
uv run --locked pytest tests/test_health.py tests/test_config.py -q
uv run --locked python - <<'PY'
from sqlalchemy.orm import configure_mappers
from app.models import Base

configure_mappers()
print(sorted(Base.metadata.tables))
PY
```

Expected: the existing health/config tests pass, and the last command prints:

```text
['articles', 'ingestion_jobs', 'sources', 'summaries']
```

This proves Python can understand the model relationships. It does **not** connect to Supabase or prove the tables exist there.

## 3. Run now: connect to your Supabase development database

If you already completed [README's database setup](../README.md#5-create-a-supabase-project), keep your existing `.env` and run the probe at the end of this section.

Otherwise:

1. Create a Supabase development project and save its database password privately.
2. Open the project's **Connect** dialog and copy a PostgreSQL URI. Use **Direct connection** when its endpoint is reachable; use **Session pooler** on an IPv4-only network. Copy the exact host, port, and username from the dialog. This guide uses port `5432`, rather than transaction pooling on `6543`.
3. Change the URI prefix from `postgresql://` to `postgresql+psycopg://`. This selects the Python driver installed in this project.
4. Replace the password placeholder with your database password. Encode special characters in the password only: for example, `@` becomes `%40`, `#` becomes `%23`, and `%` becomes `%25`.
5. Add `?sslmode=require`, or `&sslmode=require` if the URI already contains a query. This requires an encrypted connection.
6. Set `DATABASE_URL` in the root `.env`, preserving the other settings.

Example shape for session pooling; replace every placeholder with your own values:

```dotenv
DATABASE_URL="postgresql+psycopg://postgres.PROJECT_REF:ENCODED_PASSWORD@ACTUAL_POOLER_HOST:5432/postgres?sslmode=require"
```

The password is the database password, not a Supabase API key. Keep the real URI out of Git, screenshots, and shared logs.

```sh
git check-ignore .env
uv run --locked python -m app.db.probe
```

Expected output:

```text
.env
Database probe successful: SELECT 1 returned 1.
```

`SELECT 1` asks PostgreSQL to return the number 1. Success proves your credentials and network connection work; it does not create tables.

The settings loader reads `.env` automatically. An exported shell variable overrides the file. If you previously exported an old URL, run `unset DATABASE_URL` in that terminal and retry the probe.

If the probe fails, check the exact copied host/username, password encoding, project readiness, and TLS query. If direct access fails because your network cannot reach IPv6, try the session pooler. The probe hides detailed errors to avoid leaking credentials.

Supabase recommends direct connections for migrations, with session mode as the alternative for IPv4-only access. Use one working `DATABASE_URL` for the same development database throughout this guide; a separate migration URL is not implemented. See [Supabase's connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres).

## 4. Completed: the engine and session — D2.3

**Already exists:** `backend/app/db/session.py` and `tests/test_db_session.py`. The following explains the completed implementation.

Your routes need a reusable way to open and close database sessions. Implement these functions:

| Function | Responsibility |
| --- | --- |
| `get_engine()` | Read settings and create/cache an engine when first called. Validate that DATABASE_URL exists, uses `postgresql+psycopg`, and requires TLS. |
| `get_session_factory()` | Create/cache a `sessionmaker` bound to that engine, with `expire_on_commit=False`. |
| `get_db()` | Open one session, yield it to FastAPI, and close it after the request, including when an error occurs. |

“Lazy” means importing the module does not connect to the database or require credentials. Use `@lru_cache` for the two cached functions, as `get_settings()` already does in `backend/app/core/config.py`.

Engine options to use inside `get_engine()`:

```python
create_engine(
    settings.DATABASE_URL,
    pool_size=2,
    max_overflow=1,
    pool_pre_ping=True,
    connect_args={
        "connect_timeout": 5,
        "options": "-c statement_timeout=10000 -c timezone=UTC",
    },
)
```

`pool_size=2` keeps up to two reusable connections; `max_overflow=1` allows one extra during demand. `pool_pre_ping` checks a reused connection before handing it out. The timeouts bound connection/query waiting; UTC gives consistent timestamps.

Use a context manager in the dependency:

```python
# Pattern to use after get_session_factory() is implemented:
def get_db():
    with get_session_factory()() as session:
        yield session
```

For writes, use an explicit transaction such as `with session.begin(): ...`. A successful block commits; an exception rolls it back. Read endpoints do not need to commit.

Keep the single existing `Base` in `app.models.base`. Do not create a second Base. Do not start migrations or connect to PostgreSQL during module import, startup, or `/health`.

**Check after implementation:** test deferred initialization, reuse of the cached factory, missing/invalid configuration, and session closure on success and failure. These unit tests should use fakes and need no hosted connection.

```sh
uv run --locked pytest tests/test_db_session.py tests/test_health.py -q
```

**Done when:** those tests pass and `/health` still works without database credentials.

## 5. Completed: configure Alembic — D2.4

The backend Alembic environment already exists; root `[tool.alembic]` configuration points to it, so existing root CLI commands work; the setup instructions below explain how it was created. Do not run `init` again. Alembic tracks which database changes have been applied. Its `alembic_version` table stores the current revision.

Run this **once**, if the `backend/alembic/` directory does not exist:

```sh
uv run --locked alembic -c backend/alembic.ini init backend/alembic
```

It creates:

```text
backend/alembic.ini      # Alembic configuration; no real credentials here
backend/alembic/env.py   # How migrations connect and find model definitions
backend/alembic/versions/ # Versioned database change scripts
```

Edit `backend/alembic/env.py`:

1. Import `Base` from `app.models`. This imports all four models so their tables appear in the metadata.
2. Set `target_metadata = Base.metadata`. Metadata is SQLAlchemy's in-memory description of the tables.
3. Read the URL with `get_settings()` from `app.core.config`, using the same URL validation as the session setup.
4. In online mode, create an engine with `poolclass=pool.NullPool`, the connection timeout and UTC options from step 4. Connect, pass that connection and `target_metadata` to `context.configure()`, and run migrations inside `context.begin_transaction()`. Dispose of the engine afterward.
5. Set `compare_type=True` so Alembic compares column types too.
6. Retain the generated online/offline dispatch. For offline SQL generation, pass the settings URL directly to `context.configure(url=..., target_metadata=..., literal_binds=True)`.

Pass the URL directly to SQLAlchemy/Alembic instead of copying credentials into `backend/alembic.ini`; percent-encoded passwords can also conflict with INI interpolation.

Prepare the online function to accept a connection supplied through `config.attributes['connection']`. When supplied, use that connection instead of opening another one. The integration tests in step 7 need this to keep migrations inside their test schema.

**Check after configuration:**

```sh
uv run --locked alembic current
```

On a new database it should connect successfully with no current application revision. It will not show `0001` until the next step succeeds.

See the [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html) for the generated environment's structure.

## 6. Completed: generate, review, and apply the tables — D2.5

Revision `0001` already exists and has been reviewed. On a fresh checkout, skip generation and run the upgrade commands below. The generation command documents how the initial revision was created.

```sh
uv run --locked alembic revision --autogenerate --rev-id 0001 -m "initial news schema"
```

This creates a candidate Python migration under `backend/alembic/versions/`. It does **not** apply the changes yet. `--autogenerate` compares the current database with the models; `--rev-id 0001` gives this first revision a predictable ID.

The initial autogeneration duplicated enum checks. The corrected migration uses `String(20)` columns with one explicit named CHECK each; ORM enums still generate checks in model metadata. Offline SQL was verified against every model constraint and index. Review future generated migrations for this duplication.

Open the migration file and review it before applying:

- `upgrade()` creates `sources`, `articles`, `summaries`, and `ingestion_jobs`, with bigint identity IDs, required/nullable fields, defaults, foreign keys, unique rules, and indexes matching the models.
- Named checks cover enum values, nonnegative job counters, the processed-counter equality, summary draft attempts 1–2, and keywords being a JSON array.
- `downgrade()` removes children before parents, so foreign keys do not block removal.
- There are no seed rows and no operations that remove unrelated existing tables or modify Supabase-managed objects.

Autogeneration needs manual review, especially for CHECK constraints. Compare the file with the existing models and [database contract](todos.md#database-contract). If unrelated objects appear, fix the migration scope before applying. See [Alembic's autogeneration limitations](https://alembic.sqlalchemy.org/en/latest/autogenerate.html).

After review, run against your development database:

```sh
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic upgrade head
```

`head` means the newest migration. The current head is `0002`: revision `0001` creates the four application tables and revision `0002` renames `summaries.model_name` to `summaries.summarize_model_name` without replacing its data. Repeating the upgrade applies no additional changes. Confirm the four application tables and renamed column exist in Supabase's Table Editor.

**Done when:** revision `0001` is applied and the second upgrade leaves the schema unchanged. The enforcement/lifecycle tests below are implemented and reported passing by the developer.

Use migrations rather than `Base.metadata.create_all()` for setup. After a revision has been applied to a shared database, make later schema changes in a new revision.

## 7. Completed: isolated database tests — D2.6–D2.7 and D2.2

**Already implemented:** 28 integration cases cover migrations and persistence. The developer reports D2.7 completed. Collection was verified after the backend relocation; hosted tests were not rerun during that move. The instructions below explain the existing fixtures/tests.

```text
tests/integration/conftest.py
tests/integration/test_migrations.py
tests/integration/test_persistence.py
```

The `integration` pytest marker is registered in `pyproject.toml`. These tests use real PostgreSQL because SQLite cannot verify this project's PostgreSQL-specific behavior.

The fixture must:

1. Generate a fresh schema name such as `test_news_<uuid>` and create it on the configured development database.
2. Accept only the generated test name; reject `public` and the application schema. Quote schema identifiers correctly.
3. Set the test connection's search path to that schema. Ensure schema setup is committed before migration transactions begin.
4. Run Alembic with that same connection through `config.attributes['connection']`, and put `alembic_version` in the test schema too. A search path on one connection does not affect a new connection.
5. Bind test sessions to the isolated schema. For API tests, override `get_db` with these sessions and remove the override afterward.
6. Clean up only the schema the fixture created, even if a test fails.

Do not run downgrade tests against your application tables. Run them through the guarded fixture only.

| Test | Expected result |
| --- | --- |
| Empty schema → upgrade head | Four tables and revision `0002` exist in the test schema. |
| Upgrade head again | No extra changes or duplicate tables. |
| Downgrade → re-upgrade | Tables can be removed/recreated inside the disposable schema. |
| Two articles with the same canonical URL | PostgreSQL rejects the second insert. |
| Two summaries for one article | PostgreSQL rejects the second insert. |
| Article/summary with a nonexistent parent | PostgreSQL rejects the foreign key. |
| Invalid status/category/origin | Database CHECK rejects invalid values; use direct SQL to test the database rather than only SQLAlchemy's validation. |
| Invalid counters, attempts, or keywords shape | Database CHECK rejects each invalid value. |
| Timezone-aware datetime | Read-back value represents the same instant and remains timezone-aware. |
| Failed/rolled-back transaction | Partial writes are not saved; roll back before reusing a failed session. |

**Check after implementation:**

```sh
uv run --locked pytest -m integration tests/integration/test_migrations.py tests/integration/test_persistence.py -q
```

**Completion recorded:** the developer reports these tests passing against hosted PostgreSQL. D2.2, D2.6 and D2.7 are checked in the task list. Keep these commands for regression checks.

## 8. Completed: the three read endpoints — D2.8–D2.9

**Create:** `backend/app/schemas.py`, `backend/app/api/sources.py`, and `backend/app/api/articles.py`. Register the routers in `backend/app/main.py` under `/api/v1`.

Use the session dependency from step 4. With this synchronous database setup, ordinary `def` routes are appropriate.

Build these Pydantic response schemas from the [REST contract](todos.md#rest-contract):

| Schema | Fields to return |
| --- | --- |
| `SourceRead` | `id`, `name`, `rss_url`, nullable `last_fetched_at` |
| `ArticleCard` | `id`, `title`, `original_url`, `source`, nullable `published_at`, `created_at`, nullable `content_origin`, `processing_status`, nullable `category`, `summary_preview`, `input_truncated` |
| `SummaryRead` | `summary_text`, `keywords`, `summarize_model_name`, `agent_model_name`, `created_at`, `input_truncated` |

`summarize_model_name` is used consistently in the response schema, ORM model, and database. Revision `0002` renames the original column while preserving existing values. Run `uv run --locked alembic upgrade head` to apply it; the current head is `0002`.
| `ArticleDetail` | ArticleCard fields plus nullable `summary` and boolean `ai_generated` |
| `ArticlePage` | `items`, `total`, `page`, `page_size` |

Use `from_attributes=True` where constructing responses from ORM objects. Build computed/visibility-controlled fields explicitly.

Implement one endpoint at a time:

1. **Sources:** return active sources sorted by `name`, then `id`.
2. **Article detail:** fetch by positive ID, including its source and optional summary. Return 404 when missing.
3. **Article list:** return the page object, even when there are zero results.
4. **List options:** add the query parameters below, then apply the same filters to the list and total-count queries.

| Parameter | Rules |
| --- | --- |
| `page` | Integer ≥1, default 1 |
| `page_size` | Integer 1–100, default 20 |
| `q` | Optional title search, at most 200 characters |
| `source_id` | Optional positive source ID |
| `category` | Optional value from `Category`: politics, economy, technology, society, sports, other |

Combine supplied filters with AND. Search with a parameterized `ILIKE`; escape `%`, `_`, and the escape character so user input searches literally. Order by `COALESCE(published_at, created_at) DESC, id DESC`, then use offset `(page - 1) * page_size` and limit `page_size`. The ID breaks ties so page order stays predictable.

Only expose category, preview, truncation, summary, and keywords when **both** `article.processing_status == ready` and `summary.approved == True`. Apply that same visibility rule to category filtering. Otherwise use null for hidden fields and `ai_generated=false`. Preview length is at most 240 characters. Do not return raw article content, RSS HTML, rejected drafts, or review prompts.

An unknown but valid source filter returns an empty page; invalid query parameters return FastAPI's standard 422 response. A database outage returns 503 with a safe `detail: {code, message}` object, without credentials or SQL internals.

**Done when:** all three routes appear at `http://127.0.0.1:8000/docs`, and their responses follow the contract. Verify their behavior with the next two steps.

## 9. Completed: seed sources and save a fixture — D2.10

**Implemented:** `backend/app/seed_sources.py`, `api_article` in `tests/integration/conftest.py`, and the D2.10 checks in `tests/integration/test_api.py` and `test_seed_sources.py`.

Verified on 2026-10-14 against hosted PostgreSQL: both D2.10 tests passed. They prove repeatable upserts (including stable ID and preserved fetch timestamp) and fixture responses through source/list/detail endpoints. The fixture is pending and has no summary; broader D2.11 error, filtering, and approved/rejected-summary cases remain to be added.

At Day 2 completion, the seed command stored only an inactive VnExpress candidate. D3 replaced that inline seed with validated `config/sources.json`: VnExpress and Tuổi Trẻ are active for the reviewed RSS-reader scope, while Thanh Niên remains inactive. The D3 seed and live collection commands were subsequently run against the application database; integration tests continue to use disposable schemas.

A seed command inserts initial configuration rows. Make it repeatable by upserting sources using their unique `rss_url`: running it twice must not create duplicates. Keep seeds out of migration scripts.

Use [source-evidence.md](source-evidence.md) to review candidate publisher feeds. It records unresolved reuse/AI-processing questions as well as feed availability. Do not label unresolved feeds as approved for collection. Until review is complete, demonstrate Day 2 with a clearly labeled fixture in the disposable test schema.

In the integration fixture, save this sort of data inside an explicit transaction:

```python
from app.models import Article, ProcessingStatus, Source

# session must belong to the disposable test schema from step 7.
with session.begin():
    source = Source(
        name="D2 test fixture — not a publisher",
        rss_url="https://example.com/d2-fixture.xml",
    )
    session.add(source)
    session.flush()  # INSERT now so source.id is available; does not commit.

    article = Article(
        source_id=source.id,
        title="Bài viết thử nghiệm ngày 2",
        original_url="https://example.com/d2-fixture-article",
        canonical_url="https://example.com/d2-fixture-article",
        processing_status=ProcessingStatus.PENDING,
    )
    session.add(article)
```

No summary is required for this pending article. Later API tests should add separate ready/approved and rejected fixtures, with model names clearly identifying them as test data. Those are serialization tests, not real AI results.

After the seed module exists and its source configuration has been reviewed, its command will be:

```sh
uv run --locked python -m app.seed_sources
```

**Done when:** rerunning the seed does not duplicate sources, and integration tests can persist a fixture source/article and read them through all three endpoints.

## 10. Completed: prove full API behavior — D2.11

**Implemented:** `tests/integration/test_api.py` reuses the disposable schema and dependency override from step 7. `app.main` also handles SQLAlchemy `OperationalError` with a redacted 503 response.

Test:

- Source list includes the active fixture and excludes inactive sources.
- Article list/detail returns the saved fixture with the correct source and timestamps.
- Search, source/category filters, and combined filters return the expected rows and matching totals.
- Literal `%` and `_` searches do not accidentally match everything.
- Pagination, equal timestamps, and out-of-range pages behave consistently.
- A missing article returns 404; invalid IDs/query values return 422.
- A controlled simulated connection failure returns a redacted 503.
- Pending/rejected articles hide summary fields, including category/keywords. A ready article with an approved fixture summary exposes them and sets `ai_generated=true`.

Run the full Day 2 checks after creating the files:

```sh
uv run --locked pytest tests/test_health.py tests/test_config.py tests/test_db_session.py -q
uv run --locked pytest -m integration tests/integration/test_migrations.py tests/integration/test_persistence.py tests/integration/test_api.py tests/integration/test_seed_sources.py -q
```

**Verified on 2026-10-14:** the unit command passed 37 tests. The complete hosted PostgreSQL command, including `test_seed_sources.py`, passed 44 tests. The API module contributes 14 cases.

### Manual check after the routes exist

Start the API:

```sh
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

In another terminal:

```sh
curl --fail http://127.0.0.1:8000/api/v1/sources
curl --fail 'http://127.0.0.1:8000/api/v1/articles?page=1&page_size=20'
curl --fail 'http://127.0.0.1:8000/api/v1/articles?q=th%E1%BB%AD&page=1&page_size=20'
```

Expected: sources is a JSON array; articles is an object with `items`, `total`, `page`, and `page_size`. Empty application tables produce empty results, which is valid. Integration fixtures are temporary and will not appear in this server's application schema.

If your development application database contains an article, take its actual ID from the list and request `/api/v1/articles/ID`. For example, use the following only if the returned ID really is 42:

```sh
curl --fail http://127.0.0.1:8000/api/v1/articles/42
```

Otherwise, use the integration test's fixture to verify a nonempty response; do not assume a particular article ID exists.

## 11. Completed: record completion — D2.12

After the checks succeed, update README with:

1. Your chosen endpoint mode: direct or session pooler, without credentials.
2. The migration commands and current head revision `0002`.
3. The implemented source-seeding procedure and any pending publisher review.
4. The server/curl commands for the three read endpoints.
5. The unit/integration commands and actual results.

Then tick the completed D2 boxes in [todos.md](todos.md#phase-2--day-2-database-to-rest).

Your final completion check is:

- [x] Alembic connects to the hosted PostgreSQL database (developer output).
- [x] Revisions `0001`–`0002` and the rename lifecycle work in disposable PostgreSQL schemas.
- [x] PostgreSQL constraints, transactions, and migration lifecycle pass in an isolated schema (developer-reported D2.7).
- [x] A fixture article saved in migrated PostgreSQL is returned by the source/list/detail API test.
- [x] Search/filter/page behavior, 404/422/503, and summary visibility tests pass.
- [x] Source seeding is repeatable and README records the session-pooler, migration, seed, API, and focused test commands.

**Historical handoff completed:** D3 collection and deduplication now exist. Continue with D4 extraction and text-quality labeling, while keeping unresolved publisher candidates and all unapproved extraction/AI flags inactive.
