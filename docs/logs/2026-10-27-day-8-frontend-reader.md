# Day 8 — Frontend reader

**Date:** 2026-10-27 · **Branch/commits:** `bffda2e` · **Specs touched:** [frontend](../specs/frontend.md)

## Goal
A Vietnamese reader UI ("Góc Việt") that shows stored articles from the REST API.

## What changed
- React 19 + Vite 7 + TypeScript + Tailwind CSS v4 + shadcn/ui scaffold in `frontend/`.
- `vite.config.ts` proxies `/api` to `http://127.0.0.1:8000` and binds to loopback.
- `services/api.ts`: typed client for the REST schemas; loads all article pages for client-side search and category filtering.
- `data/articles.ts`, `App.tsx` and `components/news/{ArticleCard,ArticleReader,NewsHeader, NewsSkeleton}.tsx`: featured story, digest, grid, reader dialog, loading/empty/error/retry states, Vietnamese labels, `Asia/Ho_Chi_Minh` times.
- The same commit also added a manual review page (`ReviewPage.tsx`, `services/reviews.ts`), later removed (see [2026-11-07 log](2026-11-07-auto-approve-summaries.md)).

## Verification
From the [archived 14-day plan](../archived/14-day-plan-2026-11-08.md) Day 8 section:
- Browser displayed real backend data through the `/api` proxy; loading/empty/error/retry, images, category filter, diacritic-insensitive search and reader dialog worked.
- `npm run lint` and `npm run build` passed. Exact output not recorded.

## Follow-ups
- Day 9–10 items (URL routes, pagination, mobile layout, keyboard checks) remain in [todos](../todos.md).
