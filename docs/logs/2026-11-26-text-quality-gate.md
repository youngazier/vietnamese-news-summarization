# Paragraph-preserving extraction and quality gate

**Date:** 2026-11-26 · **Branch:** `feat/text-quality-gate` · **Specs:** [ingestion](../specs/ingestion.md), [database](../specs/database.md), [summarization](../specs/summarization.md)

## Goal

Keep paragraphs and publisher metadata from the fetched article page and reject weak or excerpt-only inputs before either model runs.

## What changed

- Extract body text with paragraph breaks from the reviewed article container after removing figures, captions, related links, share controls and comment UI. Read image and publisher metadata from the same BeautifulSoup document. Revision `0005` adds nullable `articles.publisher_meta`, preserving repeated values.
- Evaluate text provenance, words, sentences, RSS overlap, teaser duplication, duplicate lines, boilerplate, media URLs and publisher hints. Save fixed reason codes and count the `needs_review` transition once. The worker also checks already-prepared pending rows before invoking the graph.
- Prepared full text stays associated with its original publisher and provenance. Previous terminal outcomes are preserved. Recovery of rows previously rejected when extraction was disabled uses the same gate.

## Verification

- `uv run --locked ruff check backend tests` and `uv run --locked ruff format --check backend tests` passed.
- `uv run --locked pytest -m "not integration" -q --tb=no` passed with 295 tests and four opt-in tests skipped. Extraction and provider unit tests use fixtures and fakes.
- `uv run --locked pytest -m integration tests/integration -q --tb=no` passed with 117 tests on isolated TLS-enabled PostgreSQL 16. Checks included metadata persistence, the migration lifecycle, job counters and rejection of a legacy pending RSS excerpt before graph invocation.

## Follow-up

Thresholds remain provisional until P1.2 has paired human and Gemini extraction labels. See [todos](../todos.md#p12-evaluation-harness-synthetic-error-set--50-article-calibration-upgraded-r3).
