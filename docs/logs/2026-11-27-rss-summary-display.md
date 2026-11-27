# RSS description and approved AI summary display

**Date:** 2026-11-27 · **Branch:** `feat/rss-summary-display` (uncommitted; independent review round 2 PASS) · **Specs touched:** [backend](../specs/backend.md), [frontend](../specs/frontend.md)

## Goal

Implement only the P4.3 RSS description + AI summary display task, preserving article visibility and summary approval rules. Its checkbox was checked only after independent review round 2 passed; the rest of P4.3 remains open.

## What changed

- Added nullable `rss_description` to article cards and details, including frontend API types. Ingestion already uses BeautifulSoup to strip markup/scripts/styles and decode HTML entities before storing RSS descriptions; API serialization preserves nonblank stored plain text verbatim, including literal angle brackets, entity spellings and whitespace; only NULL/blank descriptions become NULL. Stored data is not rewritten and neither text is truncated or merged.
- The reader displays full plain-text “Mô tả từ báo” with publisher attribution and full approved “Tóm tắt AI”, plus the original link. Empty/missing blocks are omitted; if neither exists, the existing status/link fallback remains. Long text wraps in the scrollable dialog and summary paragraph breaks are preserved.
- Visibility predicates are unchanged. Summary text remains limited to approved `ready` articles; rejected drafts stay hidden. The reader also checks `ready` and `ai_generated` before showing summary text. Existing feed filtering is unchanged, so missing-summary reader cases use a readable list fixture followed by an updated detail response, rather than exposing additional feed articles.
- Added database-independent API contract tests and dev-only Playwright browser tests. The frontend had no test runner; Playwright adds three dev packages and reuses cached Chromium, with no separate unit-test framework or runtime dependency. Updated the decision, vision, task status and current specs.

## Builder verification

- `uv run --locked pytest -m "not integration and not model and not live" -q --tb=no`: 341 passed, 122 deselected.
- `uv run --locked pytest tests/test_article_rss_display.py -q --tb=no`: 33 passed, covering list/detail descriptions, NULL/blank/long text, exact preservation of literal text/whitespace, feed-to-API HTML cleanup and entity regressions, and approved/non-approved/not-ready/missing summary behavior with an overridden database dependency.
- `uv run --locked ruff check --line-length 100 backend tests` and `uv run --locked ruff format --check --line-length 100 backend tests`: passed.
- From `frontend/`, `npm run lint` and `npm run build`: passed.
- From `frontend/`, `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/home/ttnhan/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome npm run test:reader`: 16 passed, at desktop 1280 × 900 and mobile 390 × 844. All API responses were mocked. Covered both blocks, either/both missing, separate readiness/AI-visibility guards, full long text, escaping, attribution and original links; no browser console errors or uncaught page errors. Both-block and long-text screenshots were inspected. The runner stopped its Vite server.
- The initial API test stub lacked SQLAlchemy's `.all()` method; corrected the stub. The first browser run timed out during cold Vite navigation; the test allows 60 seconds and waits for DOM readiness, then passed without retries.
- PostgreSQL integration tests were skipped: their fixtures create schemas/write rows, which conflicts with this task's explicit no-database-writes rule. No migrations, schema changes, ingestion, worker or model/provider calls were performed.
- Live GET-only API smoke was unavailable: `curl --silent --max-time 2 --output /dev/null --write-out '%{http_code}\n' http://127.0.0.1:8000/health` returned connection failure / HTTP code `000`. No live database-backed reads were verified and no backend server was started.
- `git diff --check`, changed-file scope and touched documentation links/anchors were checked. No commits, pushes, merges or PRs.

## Publisher terms and follow-ups

The existing [source evidence](../specs/source-evidence.md) supports personal/nonprofit RSS-reader use with attribution for VnExpress and Tuổi Trẻ, including source/original links and cessation conditions; it requires cleaned plain text rather than RSS HTML. This fits the existing local reader scope, not unrestricted public redistribution. It does not establish publisher permission for full-article extraction, third-party AI processing or generated-summary publication. The later enablement note is user direction for the local reader, not new publisher permission. Thanh Niên remains unresolved/inactive. No new publisher terms or permissions were obtained; reassess before changing deployment scope.

Independent review round 2 passed, including isolated-schema PostgreSQL integration tests and a live GET-only smoke reported below. Only this display task is complete; the rest of P4.3 remains open. Manual/out-of-band database writes of raw HTML are unverified. No live provider or model tests were performed; publisher terms limits and future hosted-use review requirements are unchanged.

## Independent review round 1 — FAIL; builder fixes

The reviewer found that re-cleaning stored descriptions removed literal `<code>` text and decoded literal `&copy;`. Feed-to-API regression cases reproduced the issue before the fix. Removed all parsing/unescaping from serialization; only NULL/whitespace-only values map to NULL. Git history shows the original collector (`8084aff`) already cleaned descriptions before the ingestion path stored them; the current insertion path still copies `FeedEntry.rss_description` unchanged. No known legacy raw-HTML write path or format marker was found, and arbitrary stored text is not classified with heuristics. Rendering remains safe through React text nodes.

All mocked detail responses now have a 350 ms delay, and tests wait for the response and the loading indicator to disappear before any block-absence assertion. A temporary mutation that always rendered the RSS block caused the delayed `rss missing` tests to fail on both widths as expected; the mutation was restored before the passing run. Required backend, Ruff, frontend lint/build and 16 reader checks were rerun by the builder. The task stayed unchecked until the separate round 2 PASS below.

## Independent review round 2 — PASS

The independent reviewer returned **VERDICT: PASS**, relayed to the builder by the planner agent. These reviewer checks are distinct from the builder checks above:

- 341 backend tests passed, plus Ruff and frontend lint/build.
- 16 mocked Playwright reader tests passed.
- 19 PostgreSQL integration tests passed in isolated schemas, with model/provider adapters mocked.
- Live GET-only smoke: `rss_description` appeared on 116/116 cards; 30 cards had approved previews; three metadata-only details showed RSS without a summary; three real articles were checked at both desktop and mobile viewports.

The builder recorded these review results relayed by the planner agent in a docs-only closing edit, without rerunning database or live checks. Round 1's RSS re-cleaning and weak absence assertion findings are fixed. Only the RSS description + AI summary display task is checked in P4.3; all other task boxes and the milestone remain open. Manual/out-of-band database writes of raw HTML remain unverified; no live provider or model tests were performed; publisher terms limits are unchanged.
