# Day 7: durable jobs, worker and scheduling

Implemented on 2026-10-15. The API now submits and polls durable PostgreSQL jobs.
A standalone worker resumes pending articles, collects reviewed RSS feeds, prepares
text and runs the existing Day 6 graph where the source permits AI processing.
APScheduler `>=3.11,<4` was already declared and locked; no dependency or schema
migration was needed.

## Run the API and worker

Configure the root `.env` with the development database, Gemini credentials/model
and complete local ViT5 artifacts as described in the earlier setup guides. Run
from the repository root, in separate terminals:

```sh
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked --env-file .env python -m app.worker
```

The worker accepts `--config /path/to/reviewed-sources.json`. The default remains
`config/sources.json`. It loads ViT5 once, builds one reusable graph/provider,
recovers abandoned work and starts polling without contacting the API. API startup
and job submission do not import Torch, Transformers, Gemini or APScheduler.

Run only one worker process. Startup recovery assumes the previous worker has
stopped. It fails abandoned running jobs, resets processing articles to pending,
and preserves ready/rejected/failed articles, summaries and committed counters.
Failed jobs are not retried automatically; submit another job to resume pending
articles. Stop the current worker before starting its replacement.

Submit a source-specific job, or use `{"source_id":null}` / `{}` for all active
sources:

```sh
curl --fail-with-body -i -X POST http://127.0.0.1:8000/api/v1/ingestion-jobs \
  -H 'Content-Type: application/json' -d '{"source_id":1}'
# Replace JOB_ID with the returned integer:
curl --fail http://127.0.0.1:8000/api/v1/ingestion-jobs/JOB_ID
```

POST returns `202` with `job_id` and `status:"pending"`. GET returns scope, trigger,
status, attempts, all five article counters, timestamps and a nullable redacted
error message. Unknown sources/jobs return 404, inactive/empty scope returns 422,
and a full pending/running backlog returns 429. Invalid parameters retain FastAPI
422 validation responses; database outages return the existing redacted 503.

## Transactions and limits

API submission and scheduled ticks share a PostgreSQL transaction advisory lock.
Inside this short transaction they recheck active scope, the backlog cap (default
five), and scheduled duplication before insertion. Claiming selects the oldest
pending job with `FOR UPDATE SKIP LOCKED`, sets running/attempts/started_at, then
commits before publisher, model or provider work. Idle polling defaults to ten
seconds; busy jobs run sequentially.

A cycle resumes the oldest pending articles within each eligible source before
collecting new feed entries. Prepared older articles retain their place ahead of
new unprepared text. Source-scoped jobs touch only their source. Insertion and
terminal-result budgets are independent and global across the job: defaults are
20 new articles and 20 ready/needs_review/failed transitions. Once the result
budget is exhausted, remaining new rows stay pending for another job. Successful
feeds are still checked when insertion capacity is exhausted.

Each insertion increments `articles_created` in its insertion transaction. Summary,
article terminal status and the matching result counter commit together. Short
text and isolated AI failures use the same atomic counter boundary. Replays skip
existing URLs and terminal articles without incrementing counters. PostgreSQL's
existing processed-counter equality remains enforced.

A valid empty or duplicate-only feed is successful. One successful feed allows a
completed job with fixed partial-failure detail; no successful feeds fails the
job. Individual AI failures mark only that article failed and allow other work to
continue. A fatal database/pipeline failure fails the job where possible and stops
the worker, so startup recovery can release any processing claim. If PostgreSQL is
unavailable even for finalization, the job remains running until recovery.

The worker adds no HTTP or model retry loop. Existing collectors/extractors retain
their three-request limits, and Gemini retains the tested three-wire-request
limit per operation and graph ceiling of two drafts.

## Timer and shutdown

One in-memory `BackgroundScheduler` runs a UTC interval of 30 minutes by default,
with `coalesce=True` and `max_instances=1`. Its callback only enqueues, using its
own Session. A pending/running scheduled job suppresses another scheduled tick;
manual jobs remain subject to the shared total backlog cap. PostgreSQL retains
work across restarts; the timer itself starts a fresh interval on worker startup.
This follows the [APScheduler 3.x scheduling guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html).
Atomic claims use SQLAlchemy's [PostgreSQL row-lock options](https://docs.sqlalchemy.org/en/21/core/selectable.html#sqlalchemy.sql.expression.Select.with_for_update).

SIGTERM/SIGINT sets a stop event, prevents subsequent claims/ticks and stops between
article/feed operations. An operation already in progress may commit its result;
an interrupted job remains running for startup recovery. Idle waits are
interruptible. Scheduler shutdown joins callbacks and closes provider/HTTP/database
resources. No timeout-based inference reclamation is used.

## Source permission behavior

The committed configuration still allows RSS reading for VnExpress and Tuổi Trẻ,
keeps Thanh Niên inactive, and disables publisher HTML extraction and AI processing.
Usable RSS text therefore remains pending until an eligible AI policy is supplied;
inadequate text becomes needs_review without inference. An active database source
missing from the selected reviewed configuration is skipped and reported as a
source failure. The one-article Day 6 permission does not enable ongoing AI work.

## Verification

```sh
uv run --locked pytest -m 'not integration' -q
uv run --locked pytest tests/test_worker.py tests/test_scheduler.py tests/test_ingestion_jobs.py -q
uv run --locked --env-file .env pytest -m integration tests/integration -q
uv build
uv pip check
```

The full unit regression passed **249 tests** with **four opt-in model/live tests
skipped**. Worker/scheduler and job-outage checks account for 16 of those tests.
The full hosted regression passed **104 tests**; the final **25 job tests** also
passed, adding the fatal-write recovery case and bringing distinct verified
PostgreSQL cases to **105**. All integration checks used migrated, generated
`test_news_<uuid>` schemas, including migration upgrade/repeated-upgrade/downgrade/
re-upgrade, constraints and existing summary/read behavior. Concurrent tests use
additional independent connections restricted to the fixture's owned schema.

Coverage includes concurrent claimers and submission backlog races, oldest-first
claim rollback, scope, independent batch caps, backlog ordering, empty/duplicate/
partial/all-failed feeds, atomic insertion/result rollback, terminal replay,
article failure isolation, fatal-write recovery and abandoned-work recovery.
Injected ticks verify the 30-minute UTC interval, coalescing, single-instance
configuration, separate Sessions, scheduled deduplication while pending/running,
and shutdown. No 30-minute wall-clock cycle was awaited; A8 retains that later
observation separately.

The sandbox cannot resolve Supabase and its TestClient can stall. Successful
hosted/HTTP regression checks ran outside the sandbox with the configured
development connection. No SQLite replacement or mocked connectivity was used.

`uv build` and `uv pip check` pass (90 compatible installed packages). Focused
Ruff lint/format checks pass, ignoring only EXE002 for the existing executable
filesystem modes. Repository-wide checks still report 75 existing/mode diagnostics
and ten older files requiring formatting; unrelated files were left as-is.

## Live API-independent worker check

With the real local ViT5 loaded at worker startup and the default committed source
configuration, POST submitted source **1** (VnExpress) as job **1**. It returned
**202/pending in 0.88 seconds**. The verification then stopped its API process
before the worker's next idle poll. The worker independently claimed and completed
the job against hosted PostgreSQL and the live RSS feed.

After API restart, GET returned HTTP 200 with these persisted values:

| Field | Value |
| --- | --- |
| status / attempts | completed / 1 |
| articles_created | 20 |
| articles_processed | 20 |
| articles_needs_review | 20 |
| articles_summarized / articles_failed | 0 / 0 |
| started_at | 2026-10-15T15:04:59.850091Z |
| finished_at | 2026-10-15T15:05:08.941096Z |
| error_message | null |

These excerpts were inadequate under the existing text threshold. Publisher AI
and HTML extraction remained disabled, so this cycle made no Gemini or article
HTML calls. The already approved article **41** retained its summary ID, text and
updated_at. The genuine approved-AI milestone remains the Day 6 result. The
verification worker then accepted SIGTERM and shut its scheduler down cleanly;
its temporary API and worker processes were stopped. Existing user API processes
were left running.
