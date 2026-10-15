

# 12/10

`@lru_cache`
Example:
```python
from functools import lru_cache

@lru_cache
def get_engine() -> Engine
```
- `lru_cache` remembers a function's return value. When you call that function again with the same arguments, Python returns the saved value instead of executing the function again.

---

`factory`
Example:
```python
@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
    )

factory = get_session_factory()
session = factory()
```
- A factory is an object you can call to create another object  
- Cache the factory, because its configuration is reusable. Each call to `factory()` creates a new session
- `expire_on_commit=False` keeps already-loaded attribute values available after committing, rather than expiring them for a later reload

---




# Supabase
## Project initialization
- Enable automatic RLS (Row Level Security): ordinary API users cannot read or modify their rows
    - React calls FastAPI, and FastAPI connects through SQLAlchemy using the Supabase `postgres` database account. That privileged account bypasses RLS, so this setting should not block your database probe or backend operations.

## Connect to your project
- Direct
    - Connection method: **Session pooler**
    - Type: **URI**


## Day 2 migration progress — 2026-10-12

- D2.3: lazy engine/session factory implemented; 14 session tests. Full foundation suite previously passed 37 tests.
- D2.4: Alembic reads DATABASE_URL from settings rather than the generated `driver://` INI placeholder. Model metadata comes from the shared Base.
- D2.5: revision 0001 generated and reviewed. Autogeneration produced repeated enum CHECKs; fixed using VARCHAR(20) plus one explicit CHECK per enum in the migration. The ORM keeps its enum helper.
- Offline SQL matches all model constraint names and indexes. The developer reports the corrected upgrade working. Hosted enforcement tests were subsequently implemented and reported passing on 2026-10-14.
- The next task at this point was D2.6–D2.7; these are now complete as recorded below.


## Day 2 progress — 2026-10-14

- D2.1–D2.7 complete in the checklist. Hosted D2.7 success is developer-reported; no new hosted run was performed during the documentation update.
- `tests/integration/conftest.py` creates one generated disposable schema per test, supplies the migration connection/version-table schema, binds sessions to that connection, and cleans up its owned schema.
- 28 collected cases cover migration lifecycle, uniqueness, foreign keys, enum/check constraints, defaults/relationships, timestamp round trips, transaction rollback and deletion rules.
- Moved migration files to `backend/alembic/` and configuration to `backend/alembic.ini`. Root `[tool.alembic]` in `pyproject.toml` keeps `uv run --locked alembic ...` working from the repository root; integration fixture paths were updated.
- Verified root/default migration discovery and offline migration SQL. Current head is `0002`; it renames `model_name` to `summarize_model_name` and has data-preservation lifecycle coverage.
- Dependencies remain managed by root `pyproject.toml`/`uv.lock`: clone and run `uv sync --locked`. The temporary requirements export/helper were removed.
- D2.8–D2.9: response schemas and registered source/list/detail routes are implemented, including literal title search, filters, stable ordering, pagination, matching counts, and approved-summary visibility rules.
- D2.10: repeatable inactive source configuration seeding and a fictional PostgreSQL API fixture are implemented. The focused hosted run passed 2 tests; health/session regression passed 15 tests.
- D2.11–D2.12 complete: 14 API cases cover 404/422/503, redaction, filter/page ordering, literal wildcard search, preview limits, and approved/rejected/not-ready summary visibility. README records the final setup. Unit suite: 37 passed; complete hosted PostgreSQL suite: 44 passed.


## Day 3 progress — 2026-10-14

- D3.2–D3.9 are implemented. D3.1 remains open because Thanh Niên reuse is unresolved; its source stays inactive.
- `config/sources.json` records dated official-feed evidence, exact host allowlists, attribution and separate RSS-reader/extraction/AI decisions. VnExpress and Tuổi Trẻ are active only for the reviewed RSS-reader scope.
- `rss_collector.py` uses an explicit user agent, a 15-second HTTP timeout, a shared three-request retry/redirect budget, bounded backoff, a 2 MiB decoded-body limit and exact-host redirect validation.
- Feed parsing produces cleaned title/link/optional date/RSS description records. Invalid entries are skipped, malformed feeds fail explicitly and valid empty feeds succeed.
- URL normalization removes fragments, default ports and known tracking parameters while preserving path/query distinctions that may identify different articles.
- `ingestion.py` uses PostgreSQL `ON CONFLICT DO NOTHING RETURNING id`; duplicates preserve existing rows and do not consume the 20-new-article cap. Network work occurs outside the write transaction.
- Five hosted ingestion tests cover repeat ingestion, REST visibility, preservation of an existing processed row, insertion-cap behavior, rollback and a two-session race. The complete suite passed 127 tests.
- Live VnExpress verification parsed 51 usable entries, inserted 20, replayed those 20 with zero new rows, and returned the pending article through source/list/detail REST calls.
- D4 is next: evaluate permitted extraction or RSS fallback, persist source-text provenance and reject inadequate text without an AI call.
