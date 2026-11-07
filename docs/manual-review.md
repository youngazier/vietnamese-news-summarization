# Manual article review

Open **Duyệt bài** in the desktop header, or http://127.0.0.1:5173/#duyet-bai.

1. Choose an article marked **Có bản nháp**. Drafts appear before articles without summaries.
2. Compare the stored source text with the draft, category, keywords, and AI feedback. The source link opens the publisher's complete article.
3. Choose **Chấp nhận & xuất bản** to approve the stored summary, or enter a reason and choose **Từ chối** to keep it unpublished.
4. Use **Đã chấp nhận** and **Đã từ chối** to find recorded manual decisions and notes.

Articles marked **Chưa có bản nháp** cannot be accepted or declined. Their detail explains the missing input. They need sufficient permitted source text and an AI draft first; the review screen does not automatically crawl or run models.

The worker now retries older no-draft articles once when their original reason was
`extraction_disabled; ...` and their source is subsequently configured to allow both
reviewed full-text extraction and AI processing. A successful extraction returns the
article to `pending` for the normal ViT5 and Gemini pipeline. An unsuccessful attempt
stays in `needs_review` with its new reason. Existing rejected drafts and human
decisions are not overwritten. The committed source configuration still disables
extraction and AI processing, so running the worker alone does not clear that backlog.

The summarizer reads stored `articles.content`. Its provenance is either
`extracted` (cleaned article body) or `rss_excerpt` (feed description). It does not
fetch the publisher page itself. It retains at most 1,023 source tokens plus EOS;
`input_truncated` records when longer text was cut. Longer inputs now ask ViT5 for
at least 48 generated tokens, subject to Gemini review. Reader cards show only the
first 240 characters of an approved summary; opening the article shows the full
generated summary.

## Storage and API

Migration `0004` adds `human_review_decision`, `human_review_note`, and `human_reviewed_at` to `summaries`. It preserves the original AI feedback and existing approval states. The database enforces consistency between the decision, approval flag, time, and decline reason.

- `GET /api/v1/reviews?decision=pending|accept|decline&page=1&page_size=20`: review queue and manual decision history.
- `GET /api/v1/reviews/{id}`: source text, unpublished draft, feedback, eligibility, and current version.
- `POST /api/v1/reviews/{id}`: `{decision: "accept"|"decline", expected_version: "…", note: "…"}`.

Decisions update the summary and article in one transaction. Accept sets `approved=true` and article status `ready`; decline sets `approved=false` and retains `needs_review`. Public responses expose the manual decision label, but continue to suppress unapproved summary text, category, and keywords. A declined draft is removed from the pending queue and remains accessible in the declined history.

Each decision records the latest manual outcome and note; decisions are final in this first version. The supplied version must match the source and draft currently stored. Concurrent or repeated decisions receive `409`; reload to see the saved result instead of overwriting it. No historical job counters are rewritten.

## Local access

The review endpoints are available only to loopback clients and reject non-local browser origins. Run the API and Vite on `127.0.0.1`; never put an unauthenticated proxy to these endpoints on a public or shared network. Remote deployment needs reviewer authentication and authorization before exposing this workflow. Reader endpoints keep their existing behavior.

```sh
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
# Another terminal:
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

## Validation

- Migration upgrade/repeated upgrade/downgrade/re-upgrade and decision constraints passed in disposable PostgreSQL schemas; migration `0004` was then applied to the configured development database.
- 281 unit tests passed; four opt-in model/live checks were skipped.
- 27 PostgreSQL checks passed across the review, migration, and public API tests. Concurrent reviewers produced one saved decision and one conflict. A threaded test connection DNS failure was resolved by reusing the fixture's resolved database host address.
- Frontend lint and build passed. Playwright verified both 1440×900 and 1024×768, including decline validation, accept/decline histories, stale-version recovery, missing-draft protection, and queue pagination. Decision UI tests used intercepted fixtures; persistence tests used only disposable database schemas.
- The real queue was verified read-only: 40 pending articles, one saved draft, and 39 without a draft. No application article was accepted or declined during validation.
- Changed Python files pass Ruff with `EXE002` excluded because this filesystem reports ordinary source files as executable. Existing unrelated repository-wide lint findings remain outside this change.
