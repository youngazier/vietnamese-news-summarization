# Auto-approved summaries and enabled extraction/AI

**Date:** 2026-11-07 (cleanup 2026-11-08) · **Branch/commits:** `f729288`, `ee34616` · **Specs touched:** [summarization](../specs/summarization.md), [source evidence](../specs/source-evidence.md)

## Goal
Make the personal reader show summaries without a manual approval step, and let the worker extract and summarize articles from the two active sources.

## What changed
- `config/sources.json`: by explicit user direction, `article_extraction_allowed` and `ai_processing_allowed` set to `true` for VnExpress (`article.fck_detail`) and Tuổi Trẻ (`div.detail-content`). Thanh Niên stays fully disabled.
- `services/summary_persistence.py`: every completed graph result is saved with `approved=True` and status `ready`; Gemini review feedback is kept for diagnostics.
- `f729288` also added article images (migration `0003`) and a manual-review feature (migration `0004`, `api/reviews.py`, `ReviewPage.tsx`).
- `ee34616` removed the manual-review API, service, UI, tests and `docs/manual-review.md`; it also added `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf` and `compose.yaml`. Migration `0004` columns remain in the schema.

## Verification
- Not recorded.

## Follow-ups
- Decide whether to keep or drop the unused `human_review_*` columns ([todos](../todos.md)).
