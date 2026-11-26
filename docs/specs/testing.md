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
uv run --locked --env-file .env pytest -m live tests/live -q
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

## Acceptance gates

The remaining end-to-end gates are tracked in [todos](../todos.md#acceptance-gates). The original A1–A12 command table is in the [archived 14-day plan](../archived/14-day-plan-2026-11-08.md#exact-acceptance-checks).
