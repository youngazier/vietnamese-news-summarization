# Testing spec

← Back to [architecture](../architecture.md)

## Test layers

| Marker | Location | Uses | Runs by default |
| --- | --- | --- | --- |
| (none) — unit | `tests/test_*.py` | Fixtures and fakes; no network, DB, model or Gemini | yes |
| `integration` | `tests/integration/` | Real PostgreSQL in a disposable schema | no |
| `model` | `tests/model/` | Real local ViT5 weights, sockets blocked | no |
| `live` | `tests/live/` | Real Gemini / publishers | no |

A skipped or fake-only result is **not** proof of live behavior. Report skipped checks separately.

## Integration test rules

- Each test owns a generated `test_news_<uuid>` schema, runs migrations and sessions on the same connection, and drops only that schema (`tests/integration/conftest.py`).
- PostgreSQL only — never SQLite. Never downgrade `public` or application tables.
- When changing DB behavior, cover upgrade → repeated upgrade → downgrade → re-upgrade, constraints, uniqueness, FKs and rollback.
- Use `--tb=no` with real credentials; never `--showlocals`.
- Supabase may drop connections in long runs; rerun failing files in smaller groups.

## Commands

```sh
uv run --locked pytest -m "not integration" -q
uv run --locked --env-file .env pytest -m integration tests/integration -q --tb=no
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked --env-file .env pytest -m model tests/model -q
uv run --locked --env-file .env pytest -m live tests/live -q --tb=no
uv run --locked ruff check backend tests
uv run --locked ruff format --check backend tests
npm --prefix frontend run lint
npm --prefix frontend run build
```

GitHub Actions runs locked backend lint, format and unit checks and frontend lockfile install, lint and build on pushes and pull requests. PostgreSQL integration, local model and live provider tests run separately. Ruff reads the 100-character line length and the `EXE002` ignore from `pyproject.toml`.

## Coverage matrix

| Area | Essential cases |
| --- | --- |
| Health/config | Health without DB/key/model; env overrides; invalid limits |
| DB/migrations | Upgrade lifecycle; unique URLs/summary; FK/status/UTC; rollback |
| Collection | Valid/bad/empty feed; missing fields; timeout/rate limit; replay; insert race |
| Extraction | Permitted HTML; fallback; blocked redirect; short text; size cap; log redaction |
| Model | Real load/generation offline; one preload; truncation; missing/corrupt files |
| Gemini/graph | Invalid schema; provider failure; approve/retry/exhaust; exact draft count; ≤ 3 wire requests |
| Persistence | Atomic summary/status/counters; hidden unapproved output; replay safe |
| Worker/jobs | 202 only enqueues; one claim winner; crash points; partial/all-feed failure; recovery |
| Scheduler | Interval/coalescing; separate sessions; no overlap; shutdown |
| REST | Combined filters; literal search; ordering; pagination; 404/422/429/503 |
| Frontend | Lint/build; loading/empty/error; mobile; time labels |
| Packaging | Compose services on loopback; network-none generation; missing-model failure |

## Priority 1 evaluation

The [ViT5 repository](https://github.com/vietai/ViT5) supplies the pinned VietNews test TSV. The CLI verifies its SHA-256 and deterministically samples by original row index. The default is 20 benchmark articles and up to ten reference summaries from each corpus for synthetic review. The benchmark and stored publisher corpus stay in the gitignored `.evaluation/` directory.

```sh
mkdir -p .evaluation
curl --fail --location "$(uv run --locked python -m app.cli.eval vietnews-url)" -o .evaluation/vietnews-test.tsv
uv run --locked python -m app.cli.eval freeze
uv run --locked python -m app.cli.eval prepare-labels --output .evaluation/calibration-for-labeling.json
```

`freeze` reads stored rows from active, AI-permitted, configured feeds. It interleaves feeds and includes approved and unapproved strata where available. `--legacy-schema` can take a provisional read-only snapshot before migration `0005`, with publisher metadata missing. To complete calibration, freeze roughly 50 rows across both active publishers, including extraction failures or stubs and examples with accepted summaries. `prepare-labels` attaches the first ViT5 draft and its exact tokenizer-retained context.

A human reviewer compares each stored body to the original publisher page and labels `extraction_valid` for completeness and relevance. For valid full text, the reviewer labels `summary_faithful` based on the source evidence and flags `real_paraphrase` for faithful drafts that use substantively different wording. Leave a field null if it could not be evaluated. Save the reviewed dataset as a new file, then protect matching database rows after migrating through `0006`.

```sh
uv run --locked python -m app.cli.eval protect --calibration .evaluation/calibration-labeled.json
uv run --locked python -m app.cli.eval synthetic --calibration .evaluation/calibration-labeled.json --output .evaluation/synthetic.json
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked python -m app.cli.eval --calibration .evaluation/calibration-labeled.json --output .evaluation/report.md
```

`protect` uses one transaction and refuses stale or missing rows. `synthetic` writes the sentence-labeled variants to a new local file. The evaluation run sends eligible text to Gemini and writes an aggregate report. With `--local-only` it runs ViT5 and deterministic gate metrics without Gemini. When a Gemini call fails, the report includes the completed measurements and the failing stage, and the CLI exits nonzero. If Gemini asks for more than 30 seconds before retrying, the evaluator records the HTTP status and defers the retry. Online evaluation spaces Gemini wire requests, including retries, by at least six seconds by default. Set `--request-delay` to another interval in seconds.

Use `--stage graph`, `--stage calibration`, `--stage stability` or `--stage synthetic` to run an individual online measurement with its own output path. Completed reports can be kept while retrying another stage. The calibration stage audits extraction and compares one review per labeled candidate. The stability stage sends two identical independent reviews. Only the graph stage runs fresh online-stage ViT5 inference.

```sh
uv run --locked python -m app.cli.eval --stage calibration --request-delay 6 --calibration .evaluation/calibration-labeled.json --output .evaluation/calibration-report.md
```

## Acceptance gates

The remaining end-to-end gates are tracked in [todos](../todos.md#acceptance-gates). The original A1–A12 command table is in the [archived 14-day plan](../archived/14-day-plan-2026-11-08.md#exact-acceptance-checks).
