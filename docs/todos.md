# Todos

Living task list. Update it whenever a task is finished, added or dropped (see the documentation rules in [AGENTS.md](../AGENTS.md)). Check a box only after its verification passed. Completed day-by-day history: [logs/](logs/) and the [archived 14-day plan](archived/14-day-plan-2026-11-08.md).

**Last updated:** 2026-11-25

## Status

| Area | State |
| --- | --- |
| API, database, migrations (`0001`–`0004`) | Done |
| RSS ingestion, dedup, text extraction, images | Done (VnExpress, Tuổi Trẻ) |
| ViT5 + Gemini LangGraph workflow, auto-approved persistence | Done |
| Jobs, worker, scheduler, startup recovery | Done |
| Ingestion refactor (5 phases) | Done, merged 2026-11-25 |
| Reader UI (feed, filter, search, detail dialog) | Mostly done |
| Docker (frontend, api, worker) | Built; runtime smoke checks open |
| Third source (Thanh Niên) | Blocked on reuse terms |

## Improvement roadmap

Planned improvements, ordered by priority; each is done later on its own branch with a review loop.

### R1 Make Gemini review gate publication again

**Why:** `persist_summary` always sets `approved=True`, so since 2026-11-07 a summary Gemini rejected is still published; the review stores feedback but filters nothing.

**Branch:** `fix/review-gate`

- [ ] Set `approved=True` only when the graph outcome is `approved`.
- [ ] Rejected after 2 drafts → `needs_review` and hidden, or shown with a "chưa kiểm duyệt" badge; record the choice in [decisions.md](decisions.md).
- [ ] Job counter `articles_needs_review` reflects rejected articles.
- [ ] Update unit and integration summary-persistence tests.
- [ ] Update [summarization spec](specs/summarization.md) and [decisions.md](decisions.md); write a log.

**Done when:** a Gemini-rejected summary is never shown as approved, and tests prove it.

### R2 Replace the ≥200-character quality gate

**Why:** length is not quality (`MIN_TEXT_CHARACTERS = 200`): long RSS teasers pass and get "summarized" into themselves, junk (cookie banners, gallery captions, video/live pages) passes, and nothing checks the selector grabbed the right article.

**Branch:** `feat/text-quality-gate`

- [ ] Never summarize `rss_excerpt` text; show the excerpt with a "Trích đoạn" label.
- [ ] For extracted text, combine signals: minimum word count (~150, tune), ≥ 3 sentences, overlap with RSS title/description, low duplicate-line ratio, boilerplate phrase blocklist ("Đăng nhập", "Xem thêm", …).
- [ ] Skip URL patterns such as `/video/` and `/photo/`.
- [ ] Store the failing reason code in `processing_error`.
- [ ] Label 50–100 real articles per source; pick thresholds from measured precision/recall.
- [ ] Unit tests with fixtures; update [ingestion spec](specs/ingestion.md).

**Done when:** thresholds are backed by measured precision/recall and no excerpt is summarized.

### R3 Measure summary quality

**Why:** there are no numbers on summary quality; needed for credibility and the CV.

**Branch:** `feat/evaluation`

- [ ] ROUGE for ViT5 on a held-out slice of the vietnews dataset.
- [ ] Gemini-as-judge faithfulness score on ~100 real stored articles.
- [ ] Manual spot-check of ~30 articles with a simple rubric.
- [ ] Record per-article CPU latency and peak RAM.
- [ ] Record CPU batch duration per job; lower `JOB_MAX_ARTICLE_RESULTS` if a cycle can't fit in 30 minutes.
- [ ] Reproducible script under a new `eval/` (or `backend/app/cli/`) folder.
- [ ] Commit results as a Markdown report in [logs/](logs/); put summary numbers in the README.

**Done when:** one command reproduces the report and the README shows its numbers.

### R4 Finish the reader and demo

**Why:** makes the project presentable.

**Branch:** `feat/reader-routing`

- [ ] Search, category and source filters call the API (`q`, `category`, `source_id`) with debounce and `AbortController` for stale requests.
- [ ] Previous/next pagination from `total`/`page_size`; reset to page 1 on filter change.
- [ ] `/articles/:id` route with loading/error/404; keep feed state when going back.
- [ ] Show status + original link (no summary) for pending/needs_review/failed items.
- [ ] Excerpt/truncation warnings; collection-time label when `published_at` is missing.
- [ ] Check mobile and desktop widths, keyboard navigation, focus states, labels.
- [ ] Trigger a job via REST, follow it to completion, open the new article in the UI.
- [ ] Exercise slow/lost API connection and empty filters; verify retry.
- [ ] README screenshots/GIF.
- [ ] 1–2 minute demo video (preferred over public deployment because publisher terms are personal/non-commercial).

**Done when:** the full reader journey works on mobile and desktop and the demo is linked from the README.

### R5 CI

**Why:** visible quality signal; enforces lint.

**Branch:** `chore/ci`

- [ ] GitHub Actions workflow: Ruff check/format, unit tests (`-m "not integration and not model and not live"`), frontend lint + build.
- [ ] CI status badge in the README.
- [ ] `style:` commit for remaining Ruff issues; add `EXE002` to the Ruff ignore list.
- [ ] Note in [decisions.md](decisions.md) that CI was added after the MVP (it was out of MVP scope).

**Done when:** the workflow passes on the default branch and the badge is green.

### R6 Portfolio README

**Why:** the README is the first thing a reviewer sees.

**Branch:** `docs/portfolio-readme`

- [ ] Top section: one-paragraph pitch, architecture diagram, feature list.
- [ ] Engineering highlights: atomic job claims with `SKIP LOCKED`, idempotent ingestion, bounded LLM retries, offline model baked into the Docker image, test counts (re-verify before writing).
- [ ] Results from R3, then the existing setup content unchanged.

**Done when:** the README opens with the pitch and verified numbers, and setup still works.

### R7 Search and observability

**Why:** server-side search and readable logs make the app usable beyond a small feed.

**Branch:** `feat/search-observability`

- [ ] PostgreSQL full-text search for Vietnamese with `unaccent` (new migration); replaces client-side search.
- [ ] Wire `LOG_LEVEL` into logging; structured logs.
- [ ] `/ingestion` page showing jobs and counters.
- [ ] Optional: type checking with mypy or pyright.

**Done when:** search runs in PostgreSQL with diacritic-insensitive matching and logs honor `LOG_LEVEL`.

## Next up

### Packaging (old Days 11–12)

- [ ] Run network-none model smoke in the image; check missing-model failure (nonzero exit).
- [ ] Confirm the API container never loads the model; the worker loads it once.
- [ ] Full stack via `docker compose up`: submit a job, check worker logs, counters and UI.
- [ ] Restart the worker mid-job: abandoned job → failed, pending articles resume next job.
- [ ] Stop the API while the worker runs; processing and scheduling continue.
- [ ] Observe one real 30-minute scheduled cycle with no overlap.
- [ ] `npm ci` + lint + build from a clean install.

### Reliability and handoff (old Days 13–14)

- [ ] Simulate RSS timeout, malformed feed, one-source and all-source failure.
- [ ] Simulate Gemini timeout, rate limit, malformed output; confirm failures never approve.
- [ ] Interrupt around insert / graph / commit; check unique rows and counters after restart.
- [ ] Inspect logs for secrets and misleading success messages.
- [ ] Rehearse README setup in a fresh checkout.
- [ ] Record final versions, latency/RAM and known limitations.

### Cleanup

- [ ] Move `seed_sources.py` and `backfill_article_images.py` into `app/cli/`; move `SourceConfig` to `core/`.
- [ ] Decide whether to keep or drop the unused `human_review_*` columns.
- [x] Remove stale manual-review section from `frontend/README.md`.

### Blocked

- [ ] Resolve Thanh Niên reuse terms, then activate it as the third source (old D3.1).

## Acceptance gates

- [ ] Three verified, permitted feeds configured with attribution.
- [x] Alembic schema reachable from API and worker; repeated ingestion makes no duplicates.
- [x] Real ViT5 generates Vietnamese summaries; real Gemini supplies metadata/review.
- [x] Graph stops after at most two drafts.
- [ ] Gemini-rejected summaries are never shown as approved (R1).
- [x] Manual 202 + polling and 30-minute scheduling; crash recovery keeps committed results.
- [ ] REST search/filter/page/detail and mobile-friendly Vietnamese UI work end to end.
- [ ] Compose services on loopback; shared backend image with complete model artifacts.
- [ ] Network-disabled model smoke succeeds; missing model fails without downloading.
- [ ] Lockfiles, tests and final quality gate pass.
- [ ] README reproduces setup and demo; limitations documented.

## Optional later

- [ ] Read-only review tools (`get_source_article`, `search_related_articles`), max 3 calls.
- [ ] GPU inference, long-article chunking — only on measured need.
