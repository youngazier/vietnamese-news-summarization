# Day 3 — RSS collection and deduplication

**Date:** 2026-10-14 · **Branch/commits:** `8084aff` (2026-10-15, bundles Days 3–7) · **Specs touched:** [ingestion](../specs/ingestion.md), [source evidence](../specs/source-evidence.md)

## Goal
Collect reviewed publisher RSS feeds and store new articles once, with no duplicates on replay.

## What changed
- `config/sources.json` holds reviewed sources and access policy; `seed_sources.py` validates and upserts them by RSS URL. VnExpress and Tuổi Trẻ active; Thanh Niên inactive.
- `services/rss_collector.py`: httpx fetch (15 s timeout, ≤ 3 attempts, 2 MiB cap) and feedparser parsing; entries without title/link skipped; unknown dates stored as NULL.
- URL normalization (fragments, host case, default ports, tracking parameters).
- Inserts use `ON CONFLICT DO NOTHING RETURNING id` on `canonical_url`, capped at `JOB_MAX_ARTICLE_INSERTIONS` (20); duplicates do not use capacity.
- Manual CLI with `--verify-repeat` (now `app.cli.ingest`).
- Tests: `tests/test_collector.py`, `tests/test_url_normalization.py`, `tests/test_source_config.py`, `tests/integration/test_ingestion.py`, `tests/integration/test_seed_sources.py`, fixture `tests/fixtures/rss/valid.xml`.

## Verification
Recorded in the [archived 14-day plan](../archived/14-day-plan-2026-11-08.md) and the old README:
- Source config unit tests 7 passed; hosted seed tests 2 passed.
- Five isolated-schema PostgreSQL ingestion tests passed (concurrent sessions, duplicates, batch limit, rollback). Full unit + hosted suite: 127 passed (50 integration).
- Live VnExpress: 51 usable entries, 20 inserted, replay inserted 0 and counted 20 duplicates. Loopback REST source/list/detail returned HTTP 200 (source total 20, article 1 pending without a summary).
- Focused Ruff checks passed with the `EXE002` filesystem exception.

## Follow-ups
- D3.1: Thanh Niên reuse terms still unresolved (see [todos](../todos.md)).
