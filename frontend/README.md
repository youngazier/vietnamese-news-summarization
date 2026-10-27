# Góc Việt frontend

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

The feed loads all API pages for client-side search and category filtering. Categories follow the backend enum and use Vietnamese display labels. Every story shows its publisher and publication time (or explicitly labeled collection time). Opening a story fetches its detail; its headline and “Đọc toàn văn” link open the stored `original_url` in a new tab.

Only approved, ready summaries are displayed. Other articles show their processing status and original link without invented summaries or categories. Excerpt-only or truncated inputs are labeled in the preview. Publisher image URLs from the API appear in featured stories, cards, and previews. Missing or failed images use neutral editorial placeholders. See `docs/article-images.md` in the repository root for collection and backfill details.

```sh
npm run lint
npm run build
```


## Manual review

Choose **Duyệt bài** in the header, or open http://127.0.0.1:5173/#duyet-bai. Compare the stored source and saved draft, then accept to publish or decline with a reason. Articles without a draft cannot be approved. Decisions refresh the reader feed and appear under the corresponding history tab. The review API is local-only; see `docs/manual-review.md` for setup, access boundaries, and behavior.
