# Implementation logs

One file per milestone, named `YYYY-MM-DD-short-topic.md` (date the milestone finished). Logs are history: don't rewrite old ones; if something later changes, note it in the relevant spec and the newer log. Logs are never moved to `archived/`.

| Date | Log |
| --- | --- |
| 2026-10-14 | [Day 2 — database to REST](2026-10-14-day-2-database-to-rest.md) |
| 2026-10-14 | [Day 3 — RSS collection and dedup](2026-10-14-day-3-rss-collection.md) |
| 2026-10-15 | [Day 4 — text extraction](2026-10-15-day-4-text-extraction.md) |
| 2026-10-15 | [Day 5 — ViT5 and Gemini](2026-10-15-day-5-vit5-gemini.md) |
| 2026-10-15 | [Day 6 — review and persistence](2026-10-15-day-6-review-persistence.md) |
| 2026-10-15 | [Day 7 — worker and jobs](2026-10-15-day-7-worker-jobs.md) |
| 2026-10-27 | [Day 8 — frontend reader](2026-10-27-day-8-frontend-reader.md) |
| 2026-11-07 | [Auto-approved summaries, extraction/AI enabled](2026-11-07-auto-approve-summaries.md) |
| 2026-11-08 | [Article images](2026-11-08-article-images.md) |
| 2026-11-25 | [Ingestion refactor](2026-11-25-refactor-ingestion.md) |
| 2026-11-26 | [MVP runtime verification](2026-11-26-mvp-runtime-verification.md) |

## Template

```markdown
# <Milestone title>

**Date:** YYYY-MM-DD · **Branch/commits:** `...` · **Specs touched:** [x](../specs/x.md)

## Goal
One or two sentences.

## What changed
- Files/modules and behavior changes.

## Verification
- Commands run and results (counts, pass/fail, skipped checks).

## Follow-ups
- Anything left open (also add to todos.md).
```
