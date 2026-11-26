# Viet News frontend

Desktop Vietnamese news reader for screens at least 1024px wide. The feed reads stored articles from the existing FastAPI backend, which connects to Supabase using the root `.env`. No database or model credentials belong in frontend configuration.

From the repository root, start the API:

```sh
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. Vite proxies `/api` to http://127.0.0.1:8000. Production hosting must route `/api` to the backend as well.

The feed loads all API pages for client-side search and category filtering. Categories follow the backend enum and use Vietnamese display labels. Every story shows its publisher and publication time (or a collection time labeled “Thu thập”). Opening a story fetches its detail; its headline and “Đọc toàn văn” link open the stored `original_url` in a new tab.

The feed shows only articles that have an approved summary (since 2026-11-07 the backend auto-approves every completed summary; see `docs/specs/summarization.md`). Excerpt-only or truncated inputs are labeled in the preview. Publisher image URLs from the API appear in featured stories, cards, and previews. Missing or failed images use neutral editorial placeholders. See `docs/specs/ingestion.md` (Article images section) in the repository root for collection and backfill details.

```sh
npm run lint
npm run build
```
