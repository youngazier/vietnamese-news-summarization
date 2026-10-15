# Day 4: source text and quality labeling

Implemented on 2026-10-15. Collection, text preparation and future AI processing
are separate steps. No model or Gemini request is part of Day 4.

## Run

Use the existing environment, migrations and seeded sources described in the
[README](../README.md). From the repository root:

```sh
# Collect a reviewed active feed, persist it, then prepare the oldest pending text.
uv run --locked --env-file .env python -m app.services.ingestion --source-id 1 --verify-repeat

# Resume existing pending rows without collecting more articles.
uv run --locked --env-file .env python -m app.services.ingestion --source-id 1 --prepare-only
```

Insertion uses `JOB_MAX_ARTICLE_INSERTIONS`; text preparation separately uses
`JOB_MAX_ARTICLE_RESULTS` (both default to 20). Preparation includes old pending
rows absent from the current feed. Repeat `--prepare-only` to drain a larger
unprepared backlog. Already prepared pending articles, ready articles, and other
non-pending statuses are preserved. A replay after draining the backlog reports
`prepared_ids: []`.

Output includes `prepared_ids`, `text_pending`, `text_needs_review` and
`text_skipped` (a row changed while preparation ran). Existing insertion/replay
counters retain their D3 meanings. `--verify-repeat` verifies insertion replay;
`--prepare-only` exercises resumable text preparation. Neither invokes AI.

## Text contract

`ArticleExtractor.extract()` returns immutable `ExtractionResult` values:

| Field | Behavior |
| --- | --- |
| `text` | Cleaned plain text, at most 20,000 Unicode characters; `None` when absent |
| `content_origin` | `extracted`, `rss_excerpt`, or `None` for no text |
| `usable` | Provisional length check: at least 200 cleaned characters |
| `failure_reason` | Fixed redacted codes describing fallback/inadequacy; no URLs or payloads |

Scripts, navigation, forms, hidden content, adverts, related content and markup
are removed. HTML uses only the configured content container; a missing selector
never falls back to the entire page. Short extracted text falls back to RSS when
available; otherwise it retains extracted provenance and requires review.

Text and provenance are persisted together. Usable text remains `pending`; short
or absent text becomes `needs_review` immediately. `processing_error` records
fallback/quality codes, including for usable RSS fallback. For example,
`extraction_disabled; insufficient_text` explains a short permitted excerpt.

Snapshots are read in a short transaction that closes before robots/article IO.
Each result then commits in its own short transaction after rechecking source
activation and RSS identity. Conditional updates require the same unprepared
pending row and source metadata, preserving concurrent changes. An interruption
keeps committed progress; the next invocation resumes remaining rows.

Logs carry source/article/job IDs and fixed failure classes. The manual command
suppresses HTTPX INFO request lines because they include full URLs. It never logs
article bodies, excerpts, credentials or exception payloads.

## Access boundaries

The committed [source configuration](../config/sources.json) still disables
article extraction and AI processing for every publisher. The two reviewed active
sources use RSS fallback without any article-page request. Inactive or unreviewed
sources provide no fallback text. Thanh Niên remains inactive.

Future article extraction requires an active reviewed source, explicitly setting
`article_extraction_allowed=true`, and an `article_extraction` object containing
reviewed `public_path_prefixes`, `content_selector`, and a `review_note`. Record
permission evidence and verify the selector against permitted saved HTML before
enabling a real publisher. This flag does not authorize AI processing.

Every article URL and redirect must use HTTPS, the default port, an exact reviewed
hostname, and a reviewed public path on the robots origin. Encoded path traversal
and credentials are rejected. Current robots rules for the application user agent
are checked before article requests, including redirect destinations. Robots
failure blocks article fetching. Access-denied responses are not retried; no
authentication or paywall bypass is implemented.

Each robots/article fetch has at most three total HTTP requests, sharing the budget
between redirects and retries. Requests use a 15-second timeout, a one-second delay,
and bounded retry backoff. Decoded response limits are 2 MiB for HTML and 256 KiB
for robots, including missing/misleading Content-Length and compressed bodies.

## Verification and limits

```sh
uv run --locked pytest tests/test_extractor.py tests/test_collector.py tests/test_source_config.py -q
uv run --locked --env-file .env pytest -m integration tests/integration/test_ingestion.py -q
uv run --locked --env-file .env pytest -q
```

Unit fixtures are [authored fictional HTML](../tests/fixtures/html/README.md).
They verify permitted extraction, cleanup, text bounds, fallback, HTTP/robots
failures, redirect rejection and log redaction. They do not establish compatibility
with any real publisher's HTML. PostgreSQL tests use only generated disposable
`test_news_<uuid>` schemas and verify persistence, status/provenance, limits,
replay, crash recovery, transaction boundaries and concurrent changes.

Final regression on 2026-10-15: **184 tests passed**, including **60 hosted
PostgreSQL integration cases** (15 ingestion cases). Package sdist/wheel build
passed. All six changed Python files pass formatting and focused Ruff checks with
`EXE002` ignored for the existing filesystem executable-bit limitation. Repository-wide
Ruff checks still report existing import/style/docstring issues and 12 unformatted
files outside this change. The initial sandbox run stalled in the existing health
test; the completed suite ran outside the sandbox with database network access.

The 2026-10-15 live check fetched only the two permitted RSS feeds and evaluated
their cleaned descriptions with article extraction disabled:

| Source | Entries | Min / median / max characters | At least 200 | Needs review |
| --- | ---: | --- | ---: | ---: |
| VnExpress | 51 | 81 / 139 / 223 | 2 | 49 |
| Tuổi Trẻ | 50 | 77 / 153 / 609 | 6 | 44 |

This confirms that most current excerpts are too short under the provisional
threshold. It does not validate summary quality or completeness: even a longer
RSS excerpt remains an excerpt, and AI processing requires separate clearance.
Counts change as feeds update. No article HTML was downloaded during this check.

The existing 20 VnExpress development articles were prepared from their stored
RSS descriptions: 1 remained pending and 19 became needs review, all with
`rss_excerpt` provenance. A second `--prepare-only` invocation changed zero rows.
No database revision or dependency change was needed: the required columns and
BeautifulSoup dependency already existed.
