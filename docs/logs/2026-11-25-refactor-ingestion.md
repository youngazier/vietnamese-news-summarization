# Ingestion Refactor Plan

Goal: make the backend ingestion pipeline easier to read and understand. **No behavior changes**: same SQL guards, same transaction boundaries (no open DB transaction during HTTP/model calls), same error messages and return values.

- Branch: `refactor/ingestion` (created from `backend`)
- Worktree: `../vns-refactor-ingestion` (main checkout stays on `backend`)
- Merge path: `refactor/ingestion` → `backend` → `master`
- Implementer: Gemini (Antigravity). Reviewer: Claude.

## Rules for every phase

- Follow `AGENTS.md`. Never read `.env`.
- Do not edit `AGENTS.md`, `CLAUDE.md`, `backend/alembic/`, or `frontend/`.
- Move code verbatim unless the phase says otherwise; update imports and test patch targets (`monkeypatch.setattr("app.services.X.name", ...)`) to the module that looks up the name.
- Run `ruff format` only on files changed in the phase. Ignore pre-existing `EXE002` errors (the drive reports every file as executable).
- The implementer does not commit; the reviewer checks the diff, then the user commits.

## Checks after each phase

```sh
uv run --locked pytest -m "not integration" -q          # baseline: 273 passed, 4 skipped
uv run --locked ruff check --line-length 100 --ignore EXE002 <changed files>
uv run --locked ruff format --check --line-length 100 <changed files>
uv run --locked --env-file .env pytest -m integration tests/integration -q --tb=no
```

Integration tests are required after Phase 2 and Phase 3, and before any merge.

What to look for in each diff:
- Every `.where(...)` guard on the UPDATE statements is unchanged.
- No `with factory() as session` block wraps `extractor.extract`, `collector.collect` or `graph.invoke`.
- Test patch targets point to real, current module paths.

## Phases

### Phase 1: one source-eligibility check (done)
Added `RSS_READER_SUPPORTED` and `SourceConfig.is_usable` in `backend/app/seed_sources.py`; replaced 6 duplicated `is_active and review_status == "rss_reader_supported"` checks.
- Commits: `a22c4af` (logic), `c4e6838` (style: ruff format on 8 files that had never been formatted; the migration was deliberately left out).

### Phase 2: split `services/ingestion.py` (done, commit `1c2b4b2`)
| New module | Contents |
| --- | --- |
| `services/feed_ingestion.py` | `IngestionResult`, `insert_article`, `ingest_entries` |
| `services/text_preparation.py` | `TextPreparationResult`, `prepare_pending_articles`, `recover_review_articles` |
| `services/article_processing.py` | `NewsProcessor`, `process_article` |
| `services/source_guard.py` | `require_active_source` |
| `cli/ingest.py` | `main()` (run with `python -m app.cli.ingest`) |

The old `ingestion.py` was deleted. Review results:
- The AST comparison of all 10 moved definitions is identical to the old file.
- No `services.ingestion` references remain in `backend/` or `tests/`.
- Unit tests: 273 passed, 4 skipped. Lint: no new errors (6 errors in `tests/` were already there). CLI `--help` works.
- Integration tests (after all 5 phases, 2026-11-25): every file passes. In one full run, 67 passed and 47 errored during setup from Supabase connection drops; all 47 passed on rerun (`test_persistence` 25/25; migrations, review migration, seed sources and summary persistence 28/28). If a long run errors during setup, rerun the files in smaller groups.

Follow-up (updated, uncommitted): stale references in `docs/architecture.md`, `docs/day-4-extraction.md`, `docs/day-6-review.md`, `docs/TESTING_GUIDE.md`, `docs/notes.md`, `docs/todos.md`, and `README.md` now point to `python -m app.cli.ingest` and the new service modules.

### Phase 3: remove the duplicated extraction loop (done, commit `266b536`)
In `services/text_preparation.py`, `prepare_pending_articles` and `recover_review_articles` share the same loop: check `should_stop`, call `extractor.extract`, run a guarded UPDATE in a short transaction with `require_active_source`, then count prepared/pending/ needs_review/skipped. Extract a private helper that runs this loop and takes a callback that builds the guarded UPDATE for one row and its result. Keep every WHERE guard exactly as it is. Only `prepare_pending_articles` passes `job_id` and calls `record_article_result`.

### Phase 4: shared pipeline wiring and a clearer worker (done, commit `5242fb0`)
1. `services/pipeline.py`: a context manager `open_pipeline(settings)` that yields `(graph, summarize_model_name, agent_model_name)` and closes the provider. Use it in `cli/ingest.py` and `worker.serve()`. Keep the lazy imports so the API never loads model libraries.
2. `worker.py`: replace the `remaining()` tuple with a frozen dataclass `JobBudget(insertions: int, results: int)`.
3. Split `Worker.process_pending` into `_recover_excerpts`, `_prepare_text` (returns ids), and `_summarize(ids)`. Keep the stop checks and the budget re-read between preparation and summarization.

### Phase 5 (optional): article API duplication (done, commit `2a59e0b`)
In `api/articles.py`, extract `_is_visible(article)` and `_to_card(article) -> ArticleCard`, and build `ArticleDetail` from the card. The response JSON must stay identical.

## Later (outside this refactor)
- A separate `style:` commit to fix the remaining ruff issues (import order, `Union` → `|`, unused import in `tests/test_health.py`) and add `EXE002` to the ruff ignore list.
- Move `seed_sources.py` and `backfill_article_images.py` into `app/cli/`; move `SourceConfig` to `core/`.

## Merge
```sh
# in the worktree
git merge backend            # pick up other branches' changes; re-run all tests
git push -u origin refactor/ingestion
# in the main checkout
git switch backend && git merge --no-ff refactor/ingestion
git switch master  && git merge --no-ff backend
git push origin backend master
git worktree remove ../vns-refactor-ingestion && git branch -d refactor/ingestion
```
