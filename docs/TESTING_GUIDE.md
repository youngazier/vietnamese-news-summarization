# Learn software testing through this project

This guide starts with your current code, explains every existing test, and then
shows how to write a small test suite yourself. You need basic Python knowledge;
you do not need previous testing experience.

**Repository snapshot: 15 October 2026.** The current suite contains **127 cases
across eleven test files**: 77 database-free cases and 50 cases selected by the
`integration` marker. On 14 October 2026, the complete suite passed against the
hosted development PostgreSQL using disposable schemas. Examples marked
**suggested** or **exercise** remain learning material rather than implemented
features or files.

## 1. Start with what the project actually does

The project documentation now records the read APIs and migration head `0002`.
This guide gives the detailed test-by-test explanation of that executable state:

| Implemented area | Where to read it | What it does |
| --- | --- | --- |
| FastAPI application | [backend/app/main.py](../backend/app/main.py) | Registers `/health` and the source/article routers. |
| Settings | [backend/app/core/config.py](../backend/app/core/config.py) | Reads `.env`/environment variables, validates limits, caches settings. |
| Database sessions | [backend/app/db/session.py](../backend/app/db/session.py) | Validates driver/TLS, lazily creates and caches an engine/factory, yields a session per dependency call. |
| Database probe | [backend/app/db/probe.py](../backend/app/db/probe.py) | Connects to the configured database, executes `SELECT 1`, returns a success/failure exit code. |
| ORM models | [backend/app/models/](../backend/app/models/) | Defines `Source`, `Article`, `Summary`, `IngestionJob`, enums, relationships, and database rules. |
| Migrations | [backend/alembic/versions/](../backend/alembic/versions/) | `0001` creates the tables; `0002` renames `model_name` to `summarize_model_name`. Current head is `0002`. |
| Read APIs | [articles.py](../backend/app/api/articles.py), [sources.py](../backend/app/api/sources.py) | Lists active sources; lists/searches/filters/paginates articles; returns article details with summary visibility rules. |
| Response schemas | [backend/app/schemas.py](../backend/app/schemas.py) | Defines the Pydantic objects serialized into API responses. |
| Source seeding | [backend/app/seed_sources.py](../backend/app/seed_sources.py) | Validates JSON and upserts sources by RSS URL; two reviewed RSS-reader sources are active and Thanh Niên remains inactive. |
| RSS collector | [backend/app/services/rss_collector.py](../backend/app/services/rss_collector.py) | Fetches reviewed active feeds with bounded retries, redirects and response size; parses cleaned entry metadata. |
| URL normalization | [backend/app/services/url_normalization.py](../backend/app/services/url_normalization.py) | Removes fragments/default ports/tracking parameters while preserving article-identifying URL differences. |
| Ingestion persistence | [backend/app/services/ingestion.py](../backend/app/services/ingestion.py) | Inserts pending articles with PostgreSQL conflict handling and provides a bounded manual collection command. |

RSS collection and deduplicated persistence are implemented. Article extraction,
AI processing, the worker, the React frontend, and application containers are
still planned. Installed libraries such as Torch and LangGraph do not mean those
features exist. Tests for those future features should arrive with their implementations.

The current test structure is:

```text
tests/
├── test_health.py                    # 1 case
├── test_config.py                    # 22 cases
├── test_db_session.py                # 14 cases
├── test_source_config.py             # 7 cases
├── test_url_normalization.py         # 15 cases
├── test_collector.py                 # 18 cases
├── fixtures/rss/valid.xml            # deterministic feed input
└── integration/
    ├── conftest.py                   # shared setup, not a test file
    ├── test_migrations.py            # 4 cases
    ├── test_persistence.py           # 25 cases
    ├── test_api.py                   # 14 cases
    ├── test_seed_sources.py          # 2 cases
    └── test_ingestion.py             # 5 cases
```

The counts include parametrization: one Python test function can become several
separate cases. There are **60 test functions**, expanded to **127 cases**.

## 2. Why testing matters

A test is a repeatable experiment: establish known conditions, run code, and
compare the outcome with an independently chosen expectation.

Suppose you change how articles are saved. Manual inspection of one successful
insert will not tell you whether duplicate URLs are rejected, whether a failed
transaction leaves half its data behind, or whether a summary can point to a
nonexistent article. Your persistence tests check those cases repeatedly.

Tests help you:

- **Catch mistakes early.** A bad retry limit is easier to fix before a worker
  starts using it.
- **Change code with confidence.** A column rename should preserve existing
  summaries. A migration test makes that requirement executable.
- **Record decisions.** `test_one_summary_per_article` communicates a product
  rule more precisely than “summaries should work.”
- **Reproduce bugs.** A small failing test replaces a vague report such as
  “sometimes the article list looks wrong.”
- **Reduce repeated manual work.** You can check many known cases with one command.

Passing tests provide evidence about the cases you checked. They do not prove
there are no bugs. Your current API test exercises one pending article; it does
not establish that filtering, pagination, and approved-summary output work.

### Four different kinds of checks

| Check | Question it answers | Project example | Tool here |
| --- | --- | --- | --- |
| Testing | Does executing the code produce the required behavior? | Does a duplicate canonical URL raise `IntegrityError`? | pytest, with your test code and supporting libraries. |
| Linting | Does source code contain suspicious patterns or rule violations? | Is `Annotated` imported but unused in `config.py`? | Ruff `check`. |
| Formatting | Does code follow a consistent layout? | Indentation, blank lines, quote style, line wrapping. | Ruff `format`. |
| Static type checking | Are annotated types used consistently without executing the program? | Could a function annotated to return `ArticleDetail` return an incompatible value? | No dedicated checker is configured here. |

Type hints alone do not run a static type checker. Ruff includes some checks
related to annotations, but it is not a full type checker. Pydantic validation
is different again: it checks values at runtime when constructing a model.

**pytest** discovers and runs tests, supplies fixtures, expands parametrized
cases, and explains failures. It does not invent your expected behavior.
**Ruff** inspects/formats source code. It does not call your endpoints or prove
that database constraints work.

## 3. Test types: different questions, overlapping labels

Do not assume every test must fit into exactly one category. Some labels describe
scope; others describe purpose.

| Type | Meaning and when useful | Example from this project |
| --- | --- | --- |
| Unit test | Checks a small piece of behavior with external dependencies controlled. Useful during everyday coding. | `test_invalid_positive_limits` constructs `Settings` without a database or network. Session tests replace engine creation with a mock. |
| Integration test | Checks that components really cooperate across a meaningful boundary. Useful for database/driver/migration behavior that fakes cannot establish. | `test_duplicate_canonical_url` uses SQLAlchemy, psycopg, a migrated schema, and real PostgreSQL. |
| End-to-end (E2E) test | Exercises a complete user journey through the running system. Useful once the journey exists. | **Future example:** open the React reader, search, select an article, and see its approved summary from the API/database. No browser E2E suite exists today. |
| Regression test | Protects behavior against a bug returning. Useful after reproducing and fixing a defect. | `test_summary_model_column_rename_preserves_data` protects rename behavior. The session tests protect malformed-URL error handling. A test can prevent regressions even if it was written before a reported bug. |
| Smoke test | A small, broad check that something essential works. Useful after startup/setup/deployment. | The `/health` test checks liveness. The probe is a manual database connectivity smoke check; it is not a pytest test. |
| Functional test | Checks an observable feature against its requirements. Useful to describe what a user/API consumer should receive. | `test_fixture_article_read_endpoints` checks persisted data returned through the read APIs; it is both functional and integration testing. |

The health test runs FastAPI and response serialization together in process. It
is grouped with the fast, database-free tests and often called a unit test in the
project docs; more precisely, it is a small API/component test with a smoke-test
purpose. That distinction matters less than knowing its dependencies and limits.

The API integration test covers an API-to-database slice, not a full browser,
server-deployment, collection, or AI journey. TestClient does not start Uvicorn.

### Types versus techniques

**Mocking** replaces a collaborator with controlled behavior. **Parametrization**
runs the same test logic with multiple inputs. **Boundary testing** examines
limits, such as draft attempts `0`, `1`, `2`, and `3`.

These are techniques, not test layers. An integration test can use a real database
while mocking a future Gemini call. A unit test can be parametrized or written
as separate functions.

### The testing pyramid, adjusted to your project

```text
             / Few complete journeys \     E2E: later, when the UI exists
            / Focused boundary checks \    Integration: real PostgreSQL
           / Many small behavior checks \  Unit/component: fast and controlled
```

The pyramid encourages quick feedback and a few well-chosen broader checks;
it is not a required percentage or a reason to delete database tests. PostgreSQL
constraints and migrations are central to this project, so substantial database
integration coverage is appropriate.

For now, keep pytest, FastAPI TestClient, your mocks, and the existing PostgreSQL
fixtures. Add API behavior cases before introducing browser automation. You do
not need a second database, a test-management service, distributed test runners,
or a new CI system to learn or improve this suite.

## 4. Read a test: Arrange, Act, Assert

The **Arrange–Act–Assert (AAA)** pattern gives a test a readable structure:

1. **Arrange:** create known inputs and control dependencies.
2. **Act:** perform the behavior being tested.
3. **Assert:** check the outcome.

This shortened, executable **suggested example**, adapted from
`tests/test_config.py`, illustrates the pattern. It is not an additional file:

```python
from app.core.config import Settings


def test_poll_interval_default(monkeypatch):
    # Arrange: remove exported settings and ignore the real .env file.
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)

    # Act.
    settings = Settings(_env_file=None)

    # Assert: this is the intended default, not a value copied from the result.
    assert settings.WORKER_POLL_INTERVAL_SECONDS == 10
```

`assert condition` raises `AssertionError` when the condition is false. pytest
shows the expression and relevant values. Use meaningful assertions:

```python
# Existing kinds of assertions in the suite:
assert response.status_code == 200
assert response.json() == {"status": "ok"}
assert db_session.scalar(select(func.count()).select_from(Source)) == 0
```

The last line is an excerpt, requiring the fixture/imports from
`test_persistence.py`. It checks that a rolled-back write did not remain stored.

`==` compares values. `is` compares identity: `first is not second` proves two
sessions are different objects; `get_engine() is engine` proves a cached engine
is reused. `is None` checks absence. Choose the comparison matching the requirement.

A weak assertion such as `assert response` does not check the expected JSON.
Similarly, calling a function without asserting anything usually proves only
that it did not raise an exception.

### A failure can be the expected result

This **suggested standalone example**, adapted from the existing settings tests,
passes because invalid input is rejected:

```python
import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_zero_poll_interval_is_rejected(monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WORKER_POLL_INTERVAL_SECONDS", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

If no exception occurs, pytest reports that the expected exception was not
raised. An unrelated exception also fails the test. `match="request failed"`
in the session tests additionally checks the message using a regular expression.
`as caught` captures exception information; `caught.value` is the exception object.

Put only the operation expected to fail inside `pytest.raises`. Too much code
inside that block can allow the wrong operation to satisfy the expectation.

## 5. How pytest finds tests and supplies their inputs

### Discovery and node IDs

This repository does not override pytest discovery. Its files use the default
`test_*.py` pattern and functions named `test_*`. pytest also supports `*_test.py`
and appropriately named `Test*` classes, but this suite uses free functions.

Run from the repository root. Imports such as `from app.main import app` work
through the installed project package: the uv build configuration maps package
`app` to `backend/app`. There is no pytest `pythonpath` setting here.

A **node ID** identifies a test:

```text
tests/test_config.py::test_defaults_without_env_file
```

Parametrized cases append a bracketed identifier. Use `--collect-only -q` to see
the actual IDs and quote IDs containing brackets in Zsh so the shell does not
interpret them as filename patterns. See the official
[pytest invocation guide](https://docs.pytest.org/en/stable/how-to/usage.html)
for selection syntax.

### Fixtures are reusable setup with a lifetime

A fixture supplies a value or prepares conditions a test needs. pytest looks up
fixtures by parameter name; you usually do not call them yourself:

```python
# Excerpt from tests/integration/test_migrations.py:
def test_empty_schema_upgrade(test_database):
    ...
```

pytest sees `test_database`, runs its fixture, and passes the result. That fixture
is defined in `tests/integration/conftest.py`, so it is available to tests in that
directory and its descendants without an explicit import.

There is **no root `tests/conftest.py`** today. A fixture defined directly inside
`test_config.py` applies there, not automatically to neighboring test modules.

Your fixtures all use the default **function scope**: setup is fresh for each
test case, including each parametrized case. Longer scopes (`class`, `module`,
`package`, `session`) reuse setup across more tests. Reuse can save time, but
shared mutable data can make one test affect another. Keep the database fixture
function-scoped for its current isolation guarantees.

Two fixture styles appear in the suite:

- `return value`: provide a value with no fixture-owned teardown after the return.
  `migrated_database` returns the `test_database` object, whose own fixture still
  handles cleanup.
- `yield value`: provide a value, then run cleanup when the test ends.
  `test_database` drops its schema; `db_session` exits its session context.

`autouse=True` means pytest applies a fixture automatically within its visibility
scope. `clear_settings_environment` and `isolate_database_configuration` use this
to enforce isolation even when tests do not name them explicitly. Consult the
[pytest fixture guide](https://docs.pytest.org/en/stable/how-to/fixtures.html)
when learning setup/teardown in more detail.

### Built-in fixtures you already use

| Fixture | What it supplies | Why it helps here |
| --- | --- | --- |
| `tmp_path` | A temporary directory as a `pathlib.Path`. | Settings tests write a temporary `.env`; health changes to an empty directory instead of loading your real `.env`. |
| `monkeypatch` | Temporary environment, attribute, and working-directory changes that pytest undoes. | Removes exported settings, supplies fake engine creation, and blocks network calls. |

Removing an environment variable does not disable `.env` loading. That is why
the settings tests also pass `_env_file=None`, or explicitly provide a temporary
file. Conversely, `_env_file=None` does not disable exported environment variables;
the environment-clearing fixture handles those.

### Parametrization: cases without repeated test bodies

Your configuration suite stacks two decorators:

```python
# Simplified excerpt; the actual list contains five setting names.
@pytest.mark.parametrize("name", ["COLLECTION_INTERVAL_MINUTES", "MAX_JOB_BACKLOG"])
@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_invalid_positive_limits(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

This excerpt relies on the existing autouse environment fixture. With the actual
five names, pytest runs **5 × 3 = 15 cases**. Stacking decorators forms a Cartesian
product: every name is paired with every value.

By contrast, parametrizing `(database_url, error_type, message)` with rows runs
one case per row, keeping each URL paired with its expected exception/message.

Use parametrization for the same behavior under different inputs. Separate tests
are often clearer when setup or the expected behavior changes substantially.

## 6. Mocks, monkeypatch, and isolation

### Replace the dependency, keep the behavior under test real

`get_engine()` eventually calls SQLAlchemy's `create_engine`. Its unit tests
replace that collaborator while executing the real validation/caching code:

```python
# Excerpt from tests/test_db_session.py; its autouse fixture supplies settings.
engine = object()
create_engine = Mock(return_value=engine)
monkeypatch.setattr(db_session, "create_engine", create_engine)

assert db_session.get_engine() is engine
assert db_session.get_engine() is engine
create_engine.assert_called_once()
```

`Mock` comes from Python's `unittest.mock`; using it does not require writing
unittest-style test classes. It can return a controlled value and record calls.
The suite uses:

- `return_value`: supply a known result.
- `side_effect`: raise an exception or execute a supplied callable.
- `assert_not_called()` / `assert_called_once_with(...)`: verify interactions.
- `call_args`: inspect the arguments passed to engine construction.

**Patch where the code looks up the name.** `session.py` imports `create_engine`
into its own module, so its tests patch `db_session.create_engine`. Patching
`sqlalchemy.create_engine` after that import would not replace the already-bound
name. The import-safety test patches SQLAlchemy before importing the session
module in a fresh interpreter, which is a different situation.

Mocks are useful for “reject this URL before attempting engine creation.” They
cannot prove that PostgreSQL rejects a duplicate row. That requires the real
database tests.

### Isolation prevents accidental dependencies between tests

An isolated test should produce the same outcome when run alone or with the
suite. Your project isolates several kinds of state:

| State that could leak | Existing isolation mechanism |
| --- | --- |
| Your shell's exported configuration | `monkeypatch.delenv` in settings/session setup. |
| Root `.env` contents | `_env_file=None`, a supplied temporary file, or changing to `tmp_path`. |
| Cached engine/session factory | `.cache_clear()` before and after session tests. |
| Database tables and Alembic revision state | A fresh `test_news_<uuid>` schema per integration case. |
| FastAPI dependency override | Save and restore `app.dependency_overrides` in `finally`. |
| Temporary replacements | pytest automatically undoes monkeypatch operations. |

An `lru_cache` survives between calls in the same Python process. Restoring an
environment variable does not invalidate cached settings. The current session
fixture replaces `get_settings` and clears its engine/factory caches; the settings
tests construct `Settings` directly, so they do not currently test the cached
`get_settings()` function.

No suite-wide network ban exists. The health test installs its own socket guards;
the other database-free tests rely on controlled dependencies and their current
code paths. For future network code, replace the HTTP/provider boundary explicitly
and assert the relevant request/timeout behavior. Do not put real Gemini calls,
publisher requests, or model downloads in ordinary unit tests.

## 7. Every existing database-free test

### `tests/test_health.py` — one API/component smoke test

Application dependency: `app.main.app`, whose `health_check()` returns
`{"status": "ok"}`. Test dependencies: FastAPI `TestClient`, `socket`, `monkeypatch`,
and `tmp_path`.

**`test_health_returns_ok_without_external_services`**:

1. Changes to an empty temporary directory, avoiding root `.env` loading.
2. Removes database/key/model environment variables listed in the test.
3. Replaces socket connection/DNS methods with `prohibit_network`, which raises
   `AssertionError` if called.
4. Uses `TestClient(app)` to request `/health`.
5. Checks HTTP `200` and exact JSON `{"status": "ok"}`.

It catches a missing/broken health route, a changed response contract, and network
access through those patched methods while the client/request runs. It supports
the requirement that liveness works without external service credentials.

**Important limitation:** the file imports `app` at module level before the
network guard and environment changes. The later import inside the test retrieves
the already-imported module. Therefore, the comment “Import after removing
settings and prohibiting networking” does not establish safe first-import behavior.
The session suite uses a fresh interpreter to test import behavior correctly.

This test also does not prove that no local model files are loaded, and it does
not check database readiness. Its empty docstring and duplicate import reduce
clarity; the over-indented `raise` is a formatting issue. The purpose is clear
from the test body even though the docstring provides no explanation.

### `tests/test_config.py` — settings unit tests, 22 cases

Application dependency: `Settings` in `backend/app/core/config.py`. Pydantic raises
`ValidationError`; pydantic-settings reads files and environment values. These
tests do not connect to a database or call an AI provider.

**Fixture `clear_settings_environment`** is function-scoped and autouse. It removes
every name in `Settings.model_fields` from the environment before each case.
monkeypatch restores the original environment afterward. This is essential:
otherwise your personal exported settings could change the expected defaults.

| Test function | Setup, action, and assertions | Bug it catches |
| --- | --- | --- |
| `test_defaults_without_env_file` | Constructs `Settings(_env_file=None)`; checks empty database URL, interval `30`, polling `10`, insertion/result limits `20`, backlog `5`, draft ceiling `2`. | Accidental changes to these intended defaults. It does not assert every field's default. |
| `test_env_file_loading` | Writes a temporary `.env` with polling `15` and interval `45`; passes its path to `Settings`; checks both integers. | Broken explicit file loading or value conversion. |
| `test_environment_overrides_env_file` | File says polling `15`, exported variable says `25`; checks `25`. | Reversed environment/file precedence. |
| `test_invalid_positive_limits` | Fifteen cases: five limit names × `0`, `-1`, `invalid`; expects `ValidationError` each time. | Accepting zero/negative limits or nonnumeric strings. |
| `test_invalid_graph_attempts` | Four cases: `0`, `-1`, `3`, `invalid`; expects `ValidationError`. | Losing the allowed draft-attempt range of 1–2, or accepting invalid text. |

The tests exercise real Pydantic behavior and your declared fields together.
They do not redundantly retest every Pydantic feature. Missing boundary coverage:
explicitly accepting each positive limit at `1` and graph attempts at both `1`
and `2`. The default test covers graph `2`, but not a configured `1`.

### `tests/test_db_session.py` — database-management unit tests, 14 cases

These tests check how the application manages database objects **without a real
connection**. Engine construction is mocked where invoked. Creating an engine
is normally lazy with respect to connecting; constructing a SQLAlchemy Session
also does not by itself execute a database query.

**Fixture `isolate_database_configuration`**:

- Saves references to the real cached `get_engine` and `get_session_factory`
  functions before tests can monkeypatch them.
- Clears both caches before the test.
- Replaces the module's `get_settings` with a `SimpleNamespace` containing a
  fictional TLS-enabled database URL, avoiding `.env`.
- After `yield`, clears the saved real caches again. Using the saved references
  works even if a test replaced one function with a mock.

`SimpleNamespace` is a small object whose attributes can stand in for the one
setting needed here; it is not a real `Settings` instance.

| Test function | Important behavior and assertions | Bug it catches / limit |
| --- | --- | --- |
| `test_import_does_not_load_settings_or_create_engine` | Starts `sys.executable -c` with a script that patches `app.core.config.get_settings` and `sqlalchemy.create_engine` to raise if called; imports `app.db.session`; checks subprocess return code `0`, showing stderr on failure. | Eager configuration/engine work at first import. A fresh process avoids Python's module cache hiding the bug. It does not prove all application imports are side-effect-free. |
| `test_invalid_configuration_rejected_before_engine_creation` | Six URL cases: empty, malformed, wrong driver, missing TLS mode, `prefer`, `disable`. Replaces `create_engine`, expects the matching error type/message, checks the mock was never called and credential substrings are absent from `str(error)`. | Wrong URL parsing, wrong driver/TLS acceptance, trying engine creation too early, or secrets in the top-level message. It does not inspect every possible traceback/log output. |
| `test_engine_configuration_and_cache` | Three accepted TLS modes: `require`, `verify-ca`, `verify-full`. Mock returns one sentinel object; two calls return that same object and engine creation happens once. Inspects parsed driver/TLS and exact pool/timeout/UTC options. | Rejecting permitted modes, losing caching, or changing the intended pool/timeouts. It does not establish a TLS handshake or working connection. |
| `test_factory_is_cached_but_sessions_are_separate` | Mock engine; checks factory identity and one engine lookup. Calls the real `sessionmaker` twice, checks distinct sessions bound to the same engine and `expire_on_commit=False`. | Sharing one mutable Session across requests, rebuilding the factory unnecessarily, or losing the selected session option. No queries are executed. |
| `test_dependency_closes_session` | Three paths: normal exhaustion, injected `RuntimeError`, explicit generator close. A mock factory returns a context manager that yields a mock session and closes it in `finally`. Checks lazy factory call, yielded identity, exactly one close, and no commit. | Failing to exit the dependency's session context, premature close, eager session creation, swallowing the injected error, or unintended commits. “cancelled” simulates generator closure; it is not a full ASGI request-cancellation test. |

For the last test, `get_db()` returns a generator. Calling it does not yet execute
its body. `next(dependency)` runs to `yield`; a second `next` finishes normally
and raises `StopIteration`. `.throw(...)` raises inside the generator;
`.close()` ends it early. The context manager must exit in all three paths.

The fake context manager deliberately implements `session.close()` itself.
Thus the test proves your dependency exits its context; it does not independently
verify SQLAlchemy's implementation of session cleanup. That is a useful but
narrower claim than “every real request cancellation is proven safe.”

## 8. How the PostgreSQL integration fixtures work

All four integration test modules set:

```python
pytestmark = pytest.mark.integration
```

This marks every test in that module. The registered marker allows you to select
or exclude them with `-m`. **A marker does not make a test safe, skip it
automatically, or supply credentials.** Safety comes from the fixtures.

### `tests/integration/conftest.py` — setup and safety helpers

This file contains shared fixtures/helpers, not collected `test_*` functions.
It depends on pytest, SQLAlchemy/psycopg, Alembic, and a configured development
PostgreSQL database with permission to create/drop schemas.

The dependency chain is:

```text
test_database                 creates a fresh empty schema + connection
    └── migrated_database     applies committed migrations to head
            └── db_session    binds Session to that same connection
                    ├── api_article       fictional API fixture
                    └── saved_article     local fixture in test_persistence.py
```

| Name | Responsibility | Why it exists |
| --- | --- | --- |
| `ROOT` | Finds the repository root from the fixture file's location. | Resolves the committed Alembic files without assuming a temporary working directory. |
| `TEST_SCHEMA_PATTERN` | Matches `test_news_` followed by 32 lowercase hexadecimal characters. | Restricts helper operations to the generated schema naming convention. |
| `require_test_schema(name)` | Uses regex `fullmatch`; rejects any name outside that pattern with `ValueError`. | Prevents helpers from accepting `public` or arbitrary schema names. The regex checks shape, not cryptographic proof of ownership. |
| `TestDatabase` | Frozen dataclass holding the fixture-owned connection and schema name. | Makes the migration helper use explicit fixture state. Tests must not close that connection themselves. |
| `TestDatabase.migrate(direction, revision)` | Validates schema name and direction; checks `current_schema()` equals the owned name; supplies the connection and version-table schema to Alembic inside a transaction. | Refuses migration outside the intended schema and keeps application tables/version tracking together. |
| `test_database` | Generates a UUID name; creates a separate `NullPool` engine from validated application URL; creates the schema; sets search path to only that schema; yields its connection; rolls back unfinished transactions; drops its schema with a fresh connection; disposes its test engine. | Isolates every case and attempts cleanup even after a failure. It does not dispose the cached application engine used to obtain the URL. |
| `migrated_database` | Calls `migrate("upgrade", "head")` and returns the same object. | Gives most tests the actual committed schema. Its docstring says “initial migration,” but it applies all revisions through current head `0002`. |
| `db_session` | Yields a real Session bound to the migration connection, with `expire_on_commit=False`. | Keeps ORM queries on the same search path as migration operations and closes the Session afterward. |
| `api_article` | Commits an active fictional source and a pending article without a summary. Uses `flush()` to obtain the source ID before building the article. | Supplies known data for read API checks without fetching a publisher or running AI. |

`backend/alembic/env.py` recognizes the supplied connection and
`version_table_schema` attributes. It uses that connection instead of opening an
application migration connection. Setting the search path to **only** the owned
schema prevents a missing test table from falling back to `public`.

### Temporary schema, not temporary server

The fixtures do not start a local database, provision a new Supabase project, or
use SQLite. They create a temporary **schema inside the configured PostgreSQL
database**. A schema is a namespace for tables. Every case creates/drops its own
namespace, including its own `alembic_version` table.

This is necessary because the project uses PostgreSQL-specific behavior such as
JSONB checks, `TIMESTAMPTZ`, and PostgreSQL upserts. SQLite would give different
answers and would not verify the deployed database behavior.

Tests really commit data in the disposable schema. They are isolated by schema
cleanup, not by one outer rollback that encloses all tests. `session.begin()`
commits on success and rolls back on an exception. `flush()` sends pending SQL
without committing. `expire_all()` makes later access reload database state
rather than trust only objects already held in memory.

SQLAlchemy inspection/SELECT operations can start a transaction automatically.
The migration tests call `connection.rollback()` after inspection before opening
the next explicit migration transaction. Removing that step can cause an
“already initialized a Transaction” error.

### Avoid application and production side effects

Use a **development** database for integration tests. The fixture uses the normal
`DATABASE_URL`; there is no separate test-URL setting or automatic production
environment rejection. Its schema guards are useful safeguards, but they do not
choose the correct database for you.

Run destructive migration checks only through `TestDatabase.migrate`. A standalone
`alembic downgrade base` does not use these test guards and can remove application
tables. Likewise, `python -m app.seed_sources` writes to the configured application
schema; the integration seeding test calls the function with its isolated session.

No integration fixture calls `pytest.skip` when credentials are missing. Missing
configuration or connectivity is generally a setup **error**, not a successful
skip. A killed process or failed cleanup connection may leave a generated schema
behind; `finally` blocks cannot guarantee cleanup after process termination.

## 9. Every existing PostgreSQL integration test

### `tests/integration/test_migrations.py` — four migration integration cases

These check committed Alembic revisions, not just ORM declarations. A model can
be correct while a migration creates the wrong database structure.

**Helper `assert_head(database)`** uses a fresh SQLAlchemy inspector so results
are not cached across schema changes. It checks the exact table set:
`sources`, `articles`, `summaries`, `ingestion_jobs`, and `alembic_version`.
It checks revision `0002` and rolls back the inspection transaction.
`APPLICATION_TABLES` supplies the application-table set.

| Test function | Fixtures, actions, assertions | Bug it catches |
| --- | --- | --- |
| `test_empty_schema_upgrade` | Uses `test_database`; checks the schema starts empty, upgrades to head, calls `assert_head`. | A migration cannot create the expected fresh schema, omits a table, or does not reach the expected revision. |
| `test_repeated_upgrade_preserves_existing_data` | Uses `migrated_database`; inserts/commits a fictional source using bound SQL parameters, upgrades again, checks head and the original name by its returned ID. | A repeated upgrade unexpectedly recreates/deletes data or fails to be a no-op at head. |
| `test_downgrade_and_reupgrade` | Uses `migrated_database`; downgrades the owned schema to base, checks application tables are absent and revision rows empty, then upgrades and checks head. | Incorrect drop ordering, incomplete downgrade, or inability to recreate the schema afterward. It does not assert that no unrelated tables remain. |
| `test_summary_model_column_rename_preserves_data` | Starts at `0001`; commits parent rows and a summary using old `model_name`; upgrades to head, downgrades to `0001`, upgrades again. At each step checks the desired column exists, the alternate name is absent, and `fixture-model` survives. | A rename accidentally drops/replaces the column, loses values, or fails to reverse. |

The rename case is a strong regression guard: checking only the new column name
would miss data loss. The interpolated column name in its SELECT comes from its
fixed local list; row IDs are bound parameters.

`assert_head` hardcodes `0002`. When adding a legitimate new revision or table,
update that expectation intentionally. The test's strictness is useful; blindly
changing it simply to silence a failure is not.

### `tests/integration/test_persistence.py` — 25 persistence integration cases

These test the schema created by migrations together with the ORM models. They
use `db_session`; most also use the module-local **`saved_article`** fixture.
That fixture commits a source and article with fictional URLs and a Vietnamese
title. Adding the article persists its associated source through the ORM
relationship.

Two important helpers:

- **`make_summary(article_id)`** returns a valid, unsaved Summary with fixed
  category, keywords, and fictional model names. It avoids unrelated missing
  fields causing the failure a test is trying to provoke. It does not call AI.
- **`assert_constraint(error, expected_name)`** checks
  `error.value.orig.diag.constraint_name`. That is the real PostgreSQL driver's
  reported constraint name, not merely an ORM error message.

| Test function | Cases and assertions | Bug it catches |
| --- | --- | --- |
| `test_database_defaults_and_relationships` | Saves a summary and manual job, expires ORM state, reloads the article. Checks active source, bidirectional source/article and article/summary relationships, source/job relationship, pending article/job states, nullable origin/date, timezone-aware creation/update times, unapproved summary, draft count `1`, truncation `False`, and all six job counters `0`. | Missing/wrong server defaults or broken mappings that only become apparent when reloading persisted rows. This broad test stops at its first failed assertion. |
| `test_duplicate_canonical_url` | Attempts a second article with the existing canonical URL; expects `IntegrityError` from `uq_articles_canonical_url`; checks only one article remains. | Duplicate article acceptance or a failed transaction leaving a partial insert. |
| `test_duplicate_rss_url` | Attempts another source with the same RSS URL; expects `uq_sources_rss_url`. | Duplicate source configurations. |
| `test_one_summary_per_article` | Saves one summary, then attempts another for the same article; expects `uq_summaries_article_id`. | More than one persisted summary for an article. |
| `test_missing_parent_foreign_key` | Three cases: article referencing missing source, summary referencing missing article, job referencing missing source. Expects each specific FK constraint. | Orphan rows caused by missing/misconfigured foreign keys. The missing ID `999999` relies on the fresh empty schema. |
| `test_database_checks` | Ten cases, detailed below. Creates valid parent/summary/job rows, then writes an invalid value using raw SQL; checks the specific PostgreSQL CHECK constraint. | Missing database rules that ORM validation alone could conceal. |
| `test_keywords_must_be_json_array` | Replaces keywords with a JSON object through SQL; expects `ck_summaries_keywords_array`. | Allowing a JSON object where the database contract requires an array. It does not check the types of every array element. |
| `test_timezone_round_trip` | Saves a timestamp with UTC+7 and `ContentOrigin.RSS_EXCERPT`; expires/reloads; checks timezone awareness, equality with the same instant in UTC, and enum round trip. | A timestamp treated as local naive time, shifted to a different instant, or an origin value stored/read incorrectly. |
| `test_transaction_rollback_removes_partial_write` | Flushes a Source INSERT, raises a controlled `RuntimeError`, expects that message, then counts sources and checks `0`. | A transaction fails to roll back an already-issued write. Without `flush`, the test could pass without proving an INSERT was undone. |
| `test_source_deletion_restricted` | Deletes the source via raw SQL while its article exists; expects `fk_articles_source_id_sources`. | Deleting a referenced source instead of enforcing RESTRICT. It does not separately check restriction by a job reference. |
| `test_article_deletion_cascades_to_summary` | Saves a summary, deletes its article via raw SQL; checks zero summaries but one source. | Orphan summaries, missing database CASCADE, or excessive deletion of the source. Raw SQL ensures the database rule is tested rather than only ORM cascading. |
| `test_negative_outcome_counters` | Three cases: summarized, failed, needs-review counters. Sets each chosen counter and processed count to `-1`, preserving the total equality; expects the nonnegative-counter constraint. | A missing nonnegative check on an outcome counter. Preserving the other rule avoids a failure for the wrong reason. |

The ten `test_database_checks` cases are:

| Table/column | Invalid value(s) | Expected constraint |
| --- | --- | --- |
| `articles.processing_status` | `"invalid"` | `ck_articles_processing_status` |
| `articles.content_origin` | `"invalid"` | `ck_articles_content_origin` |
| `summaries.category` | `"invalid"` | `ck_summaries_category` |
| `summaries.draft_attempts` | `0`, `3` | `ck_summaries_draft_attempts` |
| `ingestion_jobs.status` | `"invalid"` | `ck_ingestion_jobs_status` |
| `ingestion_jobs.trigger` | `"invalid"` | `ck_ingestion_jobs_trigger` |
| `ingestion_jobs.articles_processed` | `1` while all outcome counts are `0` | `ck_ingestion_jobs_processed_counter_total` |
| `ingestion_jobs.attempts`, `articles_created` | `-1`, separately | `ck_ingestion_jobs_nonnegative_counters` |

The enum helper `string_enum()` sets `validate_strings=True`, so a bad value sent
through the ORM might be rejected before PostgreSQL sees it. Raw UPDATE statements
bypass that layer. This distinction is why both application validation tests and
database enforcement tests can be valuable without being redundant.

In `with pytest.raises(IntegrityError) as error, db_session.begin():`, context
managers exit in reverse order. The transaction rolls back first, then
`pytest.raises` recognizes the expected exception. The Session can subsequently
be used to query and assert that valid data remains.

### `tests/integration/test_api.py` — 14 functional/API integration cases

**`test_fixture_article_read_endpoints`** uses `db_session` and `api_article`.
It checks three endpoints against the same real persisted fixture:

| Request | Assertions | Bug it catches |
| --- | --- | --- |
| `GET /api/v1/sources` | `200`, exactly one source, correct source ID and fictional name. | Missing router, wrong active-source response, or source serialization failure for this fixture. It does not prove inactive sources are excluded because none is inserted. |
| `GET /api/v1/articles` | `200`, total `1`, page `1`, size `20`, one card, matching article ID/title/source, null publication date, serialized creation time equals saved time. | Broken basic list query, response shape, defaults, nesting, or timestamp serialization. |
| `GET /api/v1/articles/{id}` | `200`; all card fields agree with detail; status pending; summary absent; `ai_generated=False`; category, preview, and truncation absent. | Basic detail lookup/serialization or unexpected summary fields for a pending article with no summary. |

FastAPI routes declare `Depends(get_db)`. The test defines
**`override_get_db()`**, a local generator yielding its isolated fixture Session,
and sets:

```python
app.dependency_overrides[get_db] = override_get_db
```

This replaces the dependency by its function object. It directs requests into
the test schema and prevents the route from opening an application session.
The test saves previous overrides and restores them in `finally`, preventing
state leakage even when an assertion fails.

`TestClient` sends requests directly to the ASGI app in process, runs relevant
application lifecycle handling through its context manager, and returns response
objects supporting `.status_code` and `.json()`. It needs httpx, declared in the
project dependencies. It does not make a localhost HTTP request to Uvicorn.
The **database connection still uses real networking**.

The module also creates a multi-row fictional dataset and verifies active-source
ordering, literal wildcard search, combined filters and totals, timestamp/ID
pagination, approved summary output, rejected/not-ready suppression, the
240-character preview cap, standard 422 validation, structured 404 responses,
and a redacted 503 response for a controlled SQLAlchemy connection failure.

### `tests/integration/test_seed_sources.py` — one upsert integration case

**`test_seed_sources_upsert_preserves_identity_and_fetch_time`** calls the real
`seed_sources()` with `db_session` and a fictional source dictionary.

It commits the first seed, remembers the generated ID, and assigns a fixed UTC
`last_fetched_at`. It seeds the same row again, then seeds the same RSS URL with
an updated name and active flag. After `expire_all()`, it queries the database
and checks:

- Exactly one source exists.
- Its ID is unchanged.
- Its name and active flag were updated.
- Its fetch timestamp survived.

This catches duplicate inserts, replacement of row identity, failure to update
configuration fields, or accidental overwriting of fetch history. The fixed date
is test data, not an assertion about the current clock. The function uses
PostgreSQL `ON CONFLICT DO UPDATE` and lets the caller own transactions.
The test neither runs the seed CLI nor fetches the seed URL.

## 10. What the existing coverage tells us—and what it misses

### Remaining useful additions

The former high-priority API gaps are now covered. These are additional ideas:

| Priority | Coverage to add | Reason |
| --- | --- | --- |
| High | Database fixture guards: invalid schema names, invalid migration direction, and mismatched `current_schema()`. | These protect destructive migration operations but currently have no dedicated tests. Prefer controlled fakes for rejection branches, so testing refusal itself does not risk a database. |
| Next | `get_settings()` caching and default root-relative `.env` behavior. | Current settings tests use direct `Settings` construction. The exercise below covers this gap. |
| Next | `probe_database()` success/failure exit codes, redacted stderr/stdout, disposal after failures. | The probe has no pytest coverage. Mock engine/connection boundaries; do not connect in its unit tests. |
| Next | ORM timestamp update behavior; key migration columns/constraints/indexes not already behaviorally covered. | Migration tests check tables/revision and the rename, not every schema detail. Assert only important contracts. |
| Next | Seed empty input and rollback when one seed in a batch is invalid. | Current upsert coverage establishes repeatability, not all caller transaction behavior. |

The application now converts SQLAlchemy `OperationalError` into a stable 503
payload. Its test injects SQL and a credential-shaped secret into the simulated
exception and asserts neither appears in the response.

### Fragile, overlapping, and low-value aspects

- **Health import timing:** the duplicate early import weakens the intended
  first-import safety check. Improve it in a later test-maintenance change; do
  not claim the current guard protects collection-time imports.
- **Exact engine-option dictionary:** useful when pool/timeout values are an
  intentional operational contract; brittle if every harmless tuning change
  forces a test rewrite. Keep strict assertions for options you actually rely on.
- **Unrestricted mocks:** plain `Mock()` permits attributes that a real object
  might not have. Where interaction mistakes become a problem, use an appropriate
  spec/autospec or a small realistic fake. More mocking is not automatically better.
- **Broad combined tests:** defaults/relationships and the three-endpoint API
  test cover several related expectations, but stop at the first failure. Split
  by meaningful behavior as they grow, not into one test per field mechanically.
- **Constraint names:** matching the exact name prevents a wrong constraint
  from satisfying a negative test. This intentionally depends on your naming
  convention and psycopg diagnostics; update deliberately if that contract changes.
- **Nonnegative-counter cases:** the negative-outcome test also makes
  `articles_processed` negative. It confirms the shared nonnegative rule, but
  cannot prove each individual outcome predicate is present independently of
  the processed predicate. This overlap is a limitation, not a reason to throw
  away the entire constraint suite. Targeted schema-expression inspection can
  be considered if independently preserving each predicate becomes necessary.
- **No proven duplicate test bodies:** stacked invalid-limit cases cover
  distinct settings, and unit URL tests versus real persistence tests protect
  different layers. There is no clear whole test function that should simply
  be deleted as useless. Empty docstrings and repeated import/setup details
  provide little explanatory value, but are not themselves separate tests.

Every collected test's purpose is discernible from its code. That does not mean
all intended guarantees are fully established. Do not infer untested concurrency,
publisher connectivity, AI quality, or deployment behavior from passing database
or mocked unit tests.

## 11. Your configuration and exact development commands

### What `pyproject.toml` currently configures

| Section | Current meaning |
| --- | --- |
| `[project]` | Declares Python `>=3.12` and runtime dependencies. `.python-version` selects `3.12` for normal local development. |
| `[dependency-groups].dev` | Declares pytest `>=8,<10`, Ruff `>=0.9,<1`, and httpx `>=0.28,<1`. httpx is also declared among runtime dependencies. |
| `[build-system]` and `[tool.uv.build-backend]` | Uses `uv_build`, package name `app`, module root `backend`. This is why tests import `app`, not `backend.app`. |
| `[tool.pytest.ini_options]` | Registers only `integration: tests that require a real PostgreSQL database`. |
| `[tool.alembic]` | Points root Alembic commands to `backend/alembic` and prepends `backend` for imports. This is migration configuration, not a pytest fixture. |

There are no configured pytest `testpaths`, `addopts`, custom discovery patterns,
coverage thresholds, or automatic integration exclusion. There is no separate
`pytest.ini`, `tox.ini`, Ruff configuration file, or dedicated type-checker
configuration in the repository. Planned `model` and `live` markers in the
implementation docs are **not registered today**.

There is **no `[tool.ruff]` section**. The 100-character line-length preference
comes from repository instructions and explicit command flags. Without that
flag, the inspected Ruff settings use line length `88`; the Python target is
inferred as 3.12. `--line-length 100` does not by itself enable a maximum-line-length
lint rule, and formatting cannot wrap every long string automatically.

The lockfile records pytest **9.1.1** and Ruff **0.17.0**. The installed Ruff binary
also reports 0.17.0. Its inspected default rule set includes unused imports,
import sorting, modernization, executable-file, and other checks. Do not assume
a different Ruff version's default rules match this one. For configuration
resolution, see the official
[Ruff configuration reference](https://docs.astral.sh/ruff/configuration/).

`uv.lock` records resolved versions, while `pyproject.toml` declares allowed
ranges. `--locked` requires a matching lockfile. Normal `uv run --locked` may
still synchronize/install the environment; it is not a promise of zero filesystem
changes. With an already-installed environment, `uv run --locked --no-sync ...`
avoids synchronization. These distinctions are documented in the
[uv CLI reference](https://docs.astral.sh/uv/reference/cli/).

### Commands for everyday development

Run these from the repository root in an already-prepared development environment.
No package installation is needed just to follow the concepts in this guide.

```sh
# Lint without applying fixes.
uv run --locked ruff check --line-length 100 backend tests

# Check formatting without rewriting source files.
uv run --locked ruff format --check --line-length 100 backend tests

# Run the 37 database-free cases.
uv run --locked pytest -m "not integration" -q

# Run one existing file.
uv run --locked pytest tests/test_config.py -q

# Run one existing function.
uv run --locked pytest tests/test_config.py::test_defaults_without_env_file -q

# Show individual case names and more detail.
uv run --locked pytest -m "not integration" -vv

# List cases without running test bodies or fixture setup.
uv run --locked pytest --collect-only -q tests

# Select names containing a keyword.
uv run --locked pytest tests/test_db_session.py -k "cache" -vv
```

**Database commands below execute real integration tests.** First configure
`DATABASE_URL` for a development database with schema creation/deletion privileges.
Settings can read root `.env`; `--env-file .env` additionally exports its values
for the command. Be aware of which database those values select.

```sh
# All current tests, including PostgreSQL integration cases.
uv run --locked --env-file .env pytest tests -q

# Only the 50 cases selected by the integration marker.
uv run --locked --env-file .env pytest -m integration tests/integration -q

# One database test file.
uv run --locked --env-file .env pytest tests/integration/test_migrations.py -vv
```

`uv run --locked pytest -q` also discovers all current tests by default; it does
not exclude integration tests. Use the explicit database-free command while
learning and coding without live database access.

The commands can write ignored pytest/Ruff/bytecode caches even when source files
are unchanged. During this documentation inspection, collection and Ruff checks
used the already-installed binaries with caching disabled:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest --collect-only -q -p no:cacheprovider tests
.venv/bin/ruff check --no-cache --line-length 100 backend tests
.venv/bin/ruff format --check --no-cache --line-length 100 backend tests
```

Those inspection commands did not run test bodies, synchronize packages, or apply
fixes. For future development, `ruff format` without `--check` rewrites files,
and `ruff check --fix` applies available fixes; neither was used for this task.

### Current Ruff findings

The read-only lint check reported **45 diagnostics**; the format check reported
**11 files would be reformatted, 16 already formatted**. These are findings about
the existing code, not changes introduced by this document.

Examples make the distinction between check types concrete:

| Diagnostic | Actual example | Interpretation |
| --- | --- | --- |
| `F401` | Unused `typing.Annotated` in `backend/app/core/config.py`; early unused `app` import in `tests/test_health.py`. | Remove or use an import when performing a later cleanup. |
| `F811` | The inner health-test `app` import redefines the unused module-level import. | Also signals the import-timing issue discussed above. |
| `I001` | Several import blocks are unsorted. | A lint rule about import organization. |
| `D419` | Empty health-test docstring. | Gives the reader no useful explanation. |
| `UP007` / `UP035` | Older annotation/import forms in generated migration `0001`. | Modernization rules, not evidence that the migration fails. |
| `EXE002` | Python files are marked executable without shebangs in this checkout. | File-permission/shebang issue; depends on checkout permissions. It does not mean every imported Python module should acquire a shebang. |

Formatting checks show layout differences, including the health helper's
indentation and generated migration formatting. A lint or formatting failure
does not establish a behavioral test failure, and passing pytest does not
establish Ruff success.

### Interpreting and debugging pytest output

| Outcome | What it means | First action |
| --- | --- | --- |
| `PASSED` / `.` | Assertions completed successfully for this case. | Check that the case asserts meaningful behavior. |
| `FAILED` / `F` | The test body did not meet its expectation. | Read the first failing assertion and compare expected/actual values. |
| `ERROR` / `E` | Collection, setup, or teardown failed. | Inspect import/fixture/cleanup errors before blaming the function under test. |
| `SKIPPED` / `s` | The case did not execute. | Record missing verification separately; this is not a pass. |
| `deselected` | Your marker/name selection excluded the case. | Expected when using `-m "not integration"`; not a failure or skip. |

Useful existing-suite commands:

```sh
# Stop at the first failure and show local values.
uv run --locked pytest tests/test_config.py -x -vv --showlocals

# Print output rather than capturing it.
uv run --locked pytest tests/test_config.py -s -vv

# Enter Python's debugger when a test fails.
uv run --locked pytest tests/test_config.py -x --pdb

# Show detailed reasons for outcomes such as skips/errors.
uv run --locked pytest -m "not integration" -ra
```

In the debugger, `p variable` prints a value, `where` shows the stack, and `q`
quits. Avoid sharing logs/local-variable dumps containing real credentials;
use the fictional settings and isolated fixtures when debugging.

For an assertion failure, ask: is the expectation wrong, is the implementation
wrong, or did uncontrolled setup change the input? Do not weaken the assertion
until it passes. For a database fixture error, check URL/driver/TLS, connectivity,
privileges, and migration setup. Unit test success cannot diagnose all of those.

### A simple rhythm while developing

1. Read the requirement and identify one observable behavior.
2. Write or run the focused test while implementing it.
3. Run the affected test file after changes.
4. Run Ruff lint and formatting checks before considering the change ready.
5. Run the database-free suite; run relevant integration cases when changing
   SQL queries, constraints, relationships, seeds, or migrations.

Database tests are especially important for API changes involving filters or
ordering. Fake SQLAlchemy calls cannot prove real PostgreSQL query results.

## 12. Practical exercise: test the real `get_settings()` function

This exercise is **not implemented by this documentation task**. The suggested
practice file is `tests/test_settings_cache.py`; it does not currently exist.
Complete the exercise later in a practice copy or when you intentionally choose
to add this coverage.

We choose `get_settings()` in `backend/app/core/config.py` because it is short
but meaningful. Its current implementation is:

```python
@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`Settings()` uses the declared `.env` configuration and exported variables. The
decorator caches the successful result. Repeated calls return the same settings
object until `.cache_clear()` is called. A long-running application therefore
does not automatically pick up environment changes; restarting normally creates
a new process/cache.

### Step 1: describe behavior before writing assertions

| Case | Known input | Expected outcome |
| --- | --- | --- |
| Normal | Temporary `.env` says polling interval `15`. | `get_settings()` reads it and returns polling `15`. |
| Edge | First call uses allowed minimum polling `1`; environment changes to `25`. | Second call returns the same cached object with `1`; after explicit cache clearing a new object uses `25`. |
| Failure | Environment sets graph draft attempts to `0`. | `ValidationError`; correcting it to `1` permits a later call because failed calls are not cached. |

The expected values come from declared defaults/bounds and the intended caching
contract. They are not computed by calling the function twice and assuming the
two results must be correct.

### Step 2: make setup safe and repeatable

Your existing `clear_settings_environment` fixture lives inside
`test_config.py`, so it will **not** automatically apply to the suggested new
file. The exercise needs its own setup to clear environment variables, avoid
your real `.env`, and clear the settings cache before and after every case.

The complete proposed file below is executable in the prepared project
environment. The temporary `.env` is written only inside `tmp_path`.

```python
import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_get_settings_reads_default_env_file(tmp_path):
    # Arrange: Settings' default .env is in the isolated working directory.
    (tmp_path / ".env").write_text(
        "WORKER_POLL_INTERVAL_SECONDS=15\n", encoding="utf-8"
    )

    # Act.
    settings = get_settings()

    # Assert.
    assert settings.WORKER_POLL_INTERVAL_SECONDS == 15


def test_get_settings_caches_until_cleared(monkeypatch):
    # Arrange: 1 is the smallest valid positive polling interval.
    monkeypatch.setenv("WORKER_POLL_INTERVAL_SECONDS", "1")
    first = get_settings()
    monkeypatch.setenv("WORKER_POLL_INTERVAL_SECONDS", "25")

    # Act: a second call should still use the cache.
    second = get_settings()

    # Assert: same object and unchanged value.
    assert second is first
    assert second.WORKER_POLL_INTERVAL_SECONDS == 1

    # A second small experiment verifies deliberate invalidation.
    get_settings.cache_clear()
    refreshed = get_settings()
    assert refreshed is not first
    assert refreshed.WORKER_POLL_INTERVAL_SECONDS == 25


def test_get_settings_rejects_invalid_attempts_then_recovers(monkeypatch):
    # Arrange.
    monkeypatch.setenv("MAX_GRAPH_DRAFT_ATTEMPTS", "0")

    # Act + Assert: rejection is the required outcome.
    with pytest.raises(ValidationError):
        get_settings()

    # Failed calls should not poison later valid calls.
    monkeypatch.setenv("MAX_GRAPH_DRAFT_ATTEMPTS", "1")
    assert get_settings().MAX_GRAPH_DRAFT_ATTEMPTS == 1
```

There are no network/database dependencies. The failure case is not a failing
test: it passes when the invalid setting is rejected. The cache-clear teardown
is necessary because monkeypatch restores variables but cannot restore the
contents of `lru_cache` automatically.

### Step 3: run the smallest test, then the file

These commands apply **after you create the suggested practice file**:

```sh
uv run --locked pytest tests/test_settings_cache.py::test_get_settings_reads_default_env_file -vv
uv run --locked pytest tests/test_settings_cache.py -vv
```

With the current correct implementation, the expected result is **3 passed**.
This is an expected result derived from the code, not an execution result claimed
for this documentation task.

### Step 4: understand a failing test with a hypothetical regression

For a red/green demonstration, imagine that `get_settings()` accidentally changed
to this version. **This is deliberately wrong example code; it has not been
applied to the repository.** If experimenting, use a practice copy and restore it.

```python
@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=None)  # Hypothetical bug: ignores the default .env.
```

The normal-case test then expects `15` but gets the default `10`. Representative
failure excerpt, **illustrative rather than captured output**:

```text
FAILED test_get_settings_reads_default_env_file
assert settings.WORKER_POLL_INTERVAL_SECONDS == 15
E assert 10 == 15
```

The test found a meaningful regression: your application would ignore a user's
root `.env` settings. The fixture also rules out another explanation, such as an
exported variable overriding the file.

The required fix is one line, restoring the actual current implementation:

```diff
 @lru_cache
 def get_settings() -> Settings:
-    return Settings(_env_file=None)
+    return Settings()
```

Rerunning the proposed three-test file should now give **3 passed**. That is the
**red → green** cycle: demonstrate a specific incorrect behavior, correct the
implementation, confirm the expectation. You do not need to break working code
in the real project to benefit from this explanation.

### Step 5: debug rather than guess

For the proposed file, use:

```sh
uv run --locked pytest tests/test_settings_cache.py::test_get_settings_reads_default_env_file -x -vv --showlocals
uv run --locked pytest tests/test_settings_cache.py::test_get_settings_reads_default_env_file -x --pdb
```

At a failure, inspect `settings.WORKER_POLL_INTERVAL_SECONDS`, the temporary
working directory, the temporary `.env`, and whether a cache was left populated.
These checks follow the dependency chain instead of randomly editing assertions.

After the focused checks, run the database-free suite. A good new test should
pass alone and alongside the existing tests.

## 13. A maintainable testing strategy for this repository

### Keep the current structure

The current flat database-free files plus `tests/integration/` are sufficient.
Do not reorganize everything into more layers just to resemble a larger project.

A modest structure that reflects the implemented D3 coverage and shows only truly
future additions is:

```text
tests/
├── test_health.py
├── test_config.py
├── test_db_session.py
├── test_source_config.py
├── test_url_normalization.py
├── test_collector.py
├── test_settings_cache.py     # suggested exercise/coverage, not present
├── test_db_probe.py           # suggested, not present
├── fixtures/rss/              # implemented fixed feed sample
├── fixtures/html/             # future extraction samples
└── integration/
    ├── conftest.py
    ├── test_migrations.py
    ├── test_persistence.py
    ├── test_api.py
    ├── test_seed_sources.py
    └── test_ingestion.py
```

Keep PostgreSQL fixtures in their existing directory. If several API tests need
the same override/client setup, add a fixture there that always restores overrides.
If multiple database-free test files genuinely share settings isolation, consider
a root `tests/conftest.py`; it is a suggestion, not a file that exists today.
Be careful that root autouse fixtures would also affect integration descendants.

### What to keep and what to add first

Keep the existing settings validation, lazy initialization/cache/session cleanup,
migration lifecycle/rename, constraint/rollback, basic API slice, and seed upsert
tests. They protect concrete failure modes at the correct boundaries.

Add guard/helper tests because the integration fixture itself is safety-critical.
The small settings exercise is another useful contribution.

Continue using the pattern established by D3 as extraction and AI code arrive:

- D3 already uses saved RSS, controlled HTTP responses for retries/timeouts and
  real PostgreSQL for repeat/concurrent deduplication. Add saved HTML for extraction.
- Fake model/provider results for workflow decisions and bounded retries.
- A small separately selected real-model smoke check once local weights exist.
- Deliberate opt-in live provider/feed checks when actually verifying access.

Register any new markers before using them and keep costly/live checks outside
the default fast selection. The current repository registers only `integration`.
Do not assert an exact generated AI paragraph as though it were a stable function
output; check deterministic workflow contracts and assess actual summary quality
with an appropriate separate evaluation when that feature exists.

### What is unnecessary now

You do not need browser E2E infrastructure before a frontend exists, a parallel
test farm, a new Docker/PostgreSQL stack just for testing, or comprehensive load
testing for a small unfinished reader. The existing development PostgreSQL schema
fixture already provides the needed database boundary.

Avoid tests that only reproduce assignments with no meaningful requirement,
snapshot every response field indiscriminately, or mock a whole handler and then
assert that the mock returns its own configured result. Test observable behavior
and failure handling rather than every private implementation step.

No coverage plugin is configured. A coverage report can later help locate
unexecuted branches, but a high percentage does not establish good assertions.
There is no need to install one before you understand the existing tests.

### Checklist for a new feature

- [ ] State the observable behavior and the bug a test should catch.
- [ ] Choose the smallest useful scope; use real PostgreSQL when its behavior matters.
- [ ] Cover a normal case, a relevant boundary/empty case, and a failure case.
- [ ] Control environment, cached state, network calls, and clock assumptions as needed.
- [ ] Use fictional data and the existing isolated database fixture.
- [ ] Assert the result or important side effect, including absence of unintended writes/output.
- [ ] Ensure cleanup runs after failures; restore dependency overrides.
- [ ] Run the focused test, relevant suite, and Ruff checks.
- [ ] Report database/live checks not run separately from passing unit checks.

### Use generated tests as code you review

Ask your coding assistant for a small, explainable change with explicit boundaries.
For example, this **suggested request** targets existing behavior:

> Add integration tests for article summary visibility using the existing
> `db_session` fixture and an API dependency override. Cover ready/approved,
> ready/unapproved, and pending with a persisted summary. Explain the expectation
> and bug caught by each test. Use fictional data, restore overrides, and do not
> call publishers, Gemini, or models. Do not change the visibility rule merely
> to make a test pass.

Before accepting generated tests, answer:

1. Which requirement determines the expected result?
2. What actual code runs, and what is replaced by a mock?
3. Could the test pass while the feature is wrong?
4. Is a negative test failing for the intended reason?
5. What state does setup change, and how is it restored?
6. What plausible broken implementation would make this test fail?

You already have a useful review example: the health test's comment sounds
reasonable, but inspecting its early import reveals a weaker guarantee. Comments
and impressive test names are not substitutes for checking execution order.

## 14. Recommended learning order

1. Read `health_check()` and the health test's two final assertions. Learn what
   an observable result is, then read the guard's limitations.
2. Read `Settings` and `test_defaults_without_env_file`. Learn AAA and assertions.
3. Read the `.env` tests and environment fixture. Learn isolation and `tmp_path`.
4. Read the invalid-limit tests. Learn expected exceptions and parametrization.
5. Work through the `get_settings()` exercise. Write expectations before code.
6. Read the session tests. Learn dependency boundaries, mocks, caching, generators,
   and why a fake cannot establish live database behavior.
7. Trace the integration fixture chain, then rollback/uniqueness tests. Learn
   commits, flushes, schemas, and cleanup before running database cases.
8. Read migration and API integration tests. Then add one small API behavior case,
   such as hiding a saved unapproved summary.

Use Ruff throughout this sequence, while remembering that readable source and
correct behavior answer different questions.

## Glossary

| Term | Practical meaning here |
| --- | --- |
| Assertion | A condition a test requires, such as a response status or row count. |
| Arrange–Act–Assert | Prepare controlled conditions, execute behavior, verify the outcome. |
| Test case | One execution with particular inputs; parametrization can create several from one function. |
| Test suite | A group of tests, such as all files under `tests/`. |
| Discovery / collection | Finding and importing tests and expanding their cases, before test execution. |
| Node ID | pytest's selectable file/function/case identifier. |
| Fixture | Reusable setup/value with a defined lifetime and optional cleanup. |
| Fixture data | Known sample data; distinct from pytest's setup mechanism, though a fixture may create it. |
| Scope | How long a fixture is reused; your fixtures use one test case by default. |
| Autouse | A fixture applied automatically within its visibility scope. |
| `conftest.py` | pytest's automatically discovered place for shared fixtures/hooks. |
| Mock | A controlled replacement that can supply results and record calls. |
| Fake | A small working substitute, such as the session context manager used in a unit test. |
| Monkeypatch | Temporary replacement of attributes/environment/working directory, automatically undone by pytest. |
| Parametrization | Run one test body against a defined set of inputs. |
| Boundary / edge case | A limit or unusual condition, such as polling `1`, draft attempts `3`, or an empty page. |
| Test isolation | Preventing other tests or personal configuration from changing a case's result. |
| Dependency override | FastAPI's replacement of a declared dependency, here routing requests to the isolated Session. |
| Unit / integration / E2E | Increasingly broad scopes: controlled small behavior, cooperating components, complete system journey. |
| Regression | Previously correct behavior becomes wrong after a change. |
| Smoke test | A small check that a core capability starts or responds. |
| Functional test | A test of required observable feature behavior. |
| Flaky test | Passes/fails without a relevant code change because conditions are uncontrolled. |
| False confidence | A passing check is mistaken for proof of behavior it never exercised. |
| Transaction | Database operations committed together or undone by rollback. |
| Flush / commit / rollback | Send pending SQL / finalize a transaction / undo its changes. |
| Schema | A PostgreSQL namespace; integration tests create their own temporary one. |
| Migration | A versioned change to the actual database structure. |
| Constraint | A database-enforced rule such as uniqueness, a foreign key, or a CHECK expression. |
| Idempotent | Repeating an operation has the same intended effect as doing it once; source seeding should not duplicate rows. |
| Cache | Reused results held in memory; clear deliberately when tests need fresh configuration. |
| Lint / format / type check | Inspect suspicious code / standardize layout / check annotated type consistency. |
| Red → green | Show a test fails for a specific bug, fix the implementation, then confirm it passes. |
