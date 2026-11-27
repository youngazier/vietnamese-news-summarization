# Frontend spec

← Back to [architecture](../architecture.md)

"Viet News" — a Vietnamese news reader built with React 19, Vite 7, TypeScript, Tailwind CSS v4 and shadcn/ui (Base UI). Agent coding rules live in [frontend/AGENTS.md](../../frontend/AGENTS.md).

## Structure

| Path (`frontend/src/`) | Purpose |
| --- | --- |
| `App.tsx` | Page composition: feed, featured story, digest, grid, search and category filter |
| `services/api.ts` | Typed fetch client (`getArticles`, `getArticle`) with `AbortSignal` and Vietnamese errors |
| `components/news/` | `ArticleCard`, `ArticleReader` (detail dialog), `NewsHeader`, `NewsSkeleton` |
| `components/ui/` | shadcn/ui primitives |
| `data/articles.ts` | UI `Article` type, mapping from API data, Vietnamese category labels |

## API access

- Only relative `/api/v1/...` URLs. Dev: Vite proxies `/api` → `http://127.0.0.1:8000`. Docker: Nginx proxies `/api/` → `http://api:8000/api/`.
- The browser never talks to Supabase, Gemini or the worker. No credentials in frontend env.
- TypeScript types mirror the REST schemas in the [backend spec](backend.md#rest-api).

## UI rules

- Each card: title, source, local time (`Asia/Ho_Chi_Minh`), category, summary preview, optional image (placeholder on missing/failed), and a validated `http/https` link to the original article.
- Show a summary only when the API returns one. Never invent summaries for `pending`, `needs_review` or `failed` articles; label AI-generated text and excerpt/truncated input.
- The detail reader shows full `rss_description` as “Mô tả từ báo”, with `Nguồn: <publisher>`, and the full approved summary as “Tóm tắt AI”, plus the existing original link. RSS markup is cleaned during ingestion, not serialization. React renders the stored plain text as text nodes, preserving literal angle brackets and entity spellings without interpreting or injecting them as HTML. No filtering, merging or rewriting; paragraphs and long words wrap within the scrollable dialog.
- Omit an empty RSS block. Omit the AI block when the summary is missing/empty, the article is not `ready`, or `ai_generated` is false; show available RSS only for already-readable articles. If both blocks are absent, show the existing status/original-link fallback. Feed visibility is unchanged.
- Loading (`NewsSkeleton`), empty (`Chưa có bài viết`), error (`Không thể tải tin tức`) and retry (`Thử lại`) states.
- Mobile-first, accessible controls, Vietnamese copy.

## Current state vs. plan

Implemented: feed, featured/digest layout, category filter, diacritic-insensitive client search, detail dialog, images, all loading/empty/error states, and the two-block RSS description + approved AI summary reader (independent review round 2 passed on 2026-11-27).

Not yet implemented (see [todos](../todos.md)): server-side search/filter/pagination wired to API params, source filter, `/articles/:id` route with back-navigation state, optional `/ingestion` page.

## Commands

```sh
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
npm run lint
npm run build
npm run test:reader
```

## Reader verification

`npm run test:reader` runs Playwright against a temporary Vite server on port 5175 with mocked article list/detail responses, at 390 × 844 and 1280 × 900. It covers both blocks, either/both missing, hidden summaries, full long text, literal-markup escaping, attribution, original links and browser errors. Every mocked detail response is delayed 350 ms, and assertions wait for the loading indicator to appear and then disappear after the response, including before asserting absent blocks. The test runner stops its server when finished. Use an installed Playwright Chromium, or set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to an existing compatible Chromium binary. Browser artifacts go to `/tmp/rss-summary-display-playwright`. This verifies reader rendering, not live database connectivity or publisher permission.
