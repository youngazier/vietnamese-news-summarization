# Restore the review publication gate

**Date** 2026-11-26 · **Branch** `fix/review-gate` · [Summarization](../specs/summarization.md) · [Backend](../specs/backend.md) · [Database](../specs/database.md)

## Goal

Publish a summary only when the graph approves it and preserve the rejected draft for diagnostics.

## What changed

- Rejected drafts now persist with `approved=False` and article status `needs_review`. The matching job counter commits with the draft and article status.
- Article lists exclude rejected drafts from results and counts. Article detail returns 404 for graph-rejected articles.
- The planned removal of unused `human_review_*` columns remains in P2.2.

## Verification

- The full combined non-integration selection passed with 277 tests and four opt-in skips.
- The configured PostgreSQL run passed all 60 tests in `test_summary_persistence.py`, `test_jobs.py` and `test_api.py` using isolated schemas.
- All 114 integration tests passed on the combined checkout against disposable TLS-enabled PostgreSQL. Coverage included approval, exhausted drafts, REST visibility, exact job counters, transaction rollback and replay.

## Follow-ups

- Rows written by the former auto-approval code retain their historical state. The old persistence code discarded the original decision, so a reliable historical cleanup would require re-review.
