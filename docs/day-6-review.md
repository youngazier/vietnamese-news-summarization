# Day 6: review, bounded routing and summary persistence

Implemented on 2026-10-15. The Day 6 pipeline connects the existing local CPU ViT5
summarizer and Gemini metadata adapter to source-based review and PostgreSQL.
The worker, job counters, scheduler and ingestion-job routes remain Day 7 work.

## Graph and provider contract

`app.agents.graph.build_news_graph` compiles a `StateGraph` with the following path:
START → draft → review → accept/retry/reject → END. An approved first draft stops
immediately. A rejected first draft gets one alternate generation; a rejected
second draft ends as `needs_review`. `MAX_GRAPH_DRAFT_ATTEMPTS` can lower the limit
to one. A separate recursion limit of eight stops an accidental graph cycle.

Each invocation accepts only article inputs, preventing stale approval, outcomes
or attempt counts from entering a new run. Drafting resets approval and feedback,
recomputes category/keywords, and keeps source text unchanged. ViT5 uses four beams
and length penalty 1.0 on attempt one, then two beams and length penalty 0.8 on
attempt two. Both use deterministic decoding, no repeated trigrams, at most 1,024
input tokens and 256 new tokens. Review feedback never enters ViT5 input.

`agents/prompts.py` keeps instructions separate from JSON article data. Review
receives cleaned bounded source text, exact tokenizer-retained text, origin and
truncation context, the local summary and metadata. It checks source support for
names, dates, numbers, quotes and critical claims. Both source and candidate text
are untrusted data. Review is a quality heuristic against the supplied source,
not independent fact-checking.

`ReviewResult` requires a strict boolean, feedback of at most 1,000 characters,
and a nonempty rejection reason. Invalid/noncompleted/empty responses and SDK
failures propagate as processing errors. Metadata and review each retain the
existing 30-second request timeout, `store=False`, structured-output validation
and three-wire-request ceiling. There is no additional application retry loop;
two operations per draft × two drafts × three requests caps an article at twelve
provider requests.

The implementation follows the official [LangGraph graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
and [Gemini Interactions](https://ai.google.dev/gemini-api/docs/interactions-overview)
contracts, with wire tests against the locked google-genai 2.29.0 SDK.

## Processing and atomic persistence

`services.ingestion.process_article` checks the active source/configuration and AI
permission, claims one pending article in a short transaction, and commits before
model/provider work. Inadequate prepared text becomes `needs_review` without
inference. Ready, rejected, failed and already-processing rows are skipped.

The graph returns state only. `ReviewedNews` validates the final output and checks
that approval matches the terminal outcome. `services.summary_persistence.persist_summary`
locks the article, checks that title/text/origin still match, and writes the final
candidate, category/keywords, review, attempt count, truncation and separate ViT5 /
Gemini model IDs together with article status in one caller-owned transaction.
Only approved candidates become `ready`; rejected candidates remain stored for
audit and hidden by all existing read routes and category filters. The existing
one-summary constraint is retained; no schema migration is needed.

Model/provider/schema failures save a fixed `AI processing failed` message and
`failed` status without a partial candidate. Database errors propagate; a failed
final write rolls back its summary and status together. Its committed processing
claim is left for Day 7 startup recovery. Replays do not replace terminal results.
Job counters and recovery are deliberately not implemented in Day 6.

## Run one reviewed article

The normal source configuration keeps every publisher AI flag disabled. A reviewed
AI-enabled configuration must explicitly set `ai_processing_allowed: true` and
provide a nonblank `ai_processing_review_note` on an active source. The existing
source/RSS host and access checks still apply. The Day 6 user-selected test uses a
separate temporary configuration; it does not enable ongoing publisher processing.

With local artifacts, Gemini credentials and a prepared pending article from an
eligible source, run:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked --env-file .env \
  python -m app.services.ingestion --source-id SOURCE_ID \
  --process-article-id ARTICLE_ID --config /path/to/reviewed-sources.json
```

This explicit processing mode performs no RSS collection or article HTML fetch.
It prints the article ID and whether a new terminal transition was saved. The
model loads only for this processing mode; regular collection and the API remain
independent of model loading. Poll `GET /api/v1/articles/ARTICLE_ID` for the saved
status and visible approved output.

## Verification

Commands run from the repository root:

```sh
uv run --locked pytest -m "not integration" -q
uv run --locked --env-file .env pytest -m integration \
  tests/integration/test_summary_persistence.py -q --tb=short
uv run --locked --env-file .env pytest -m live tests/live/test_gemini.py -q -s --tb=short
uv build
```

The unit regression passed **233 tests**, with four real model/live tests skipped
by default. The **20 new hosted PostgreSQL tests passed** in generated
`test_news_<uuid>` schemas using the existing migration fixtures. They cover graph
outcomes, provenance, no inference inside transactions, uniqueness, rollback,
replay, unchanged-source guards, provider failures, permission/text gates and
REST suppression. Real Gemini checks passed **two tests**: metadata plus review
of a supported draft and a draft with invented names, date, place and numbers.
The latter was rejected with concrete feedback. Package build and focused Ruff
checks pass; Ruff checks ignore the existing EXE002 filesystem mode issue.

The sandbox cannot resolve Supabase DNS and FastAPI TestClient stalls under it.
Successful database/REST tests ran outside the sandbox. These were genuine hosted
PostgreSQL checks, not SQLite or mocked connectivity.

All **60 existing hosted PostgreSQL regression tests passed** separately, including
migration upgrade/repeated-upgrade/downgrade/re-upgrade, read API, persistence,
source seeding and ingestion. Together with the new tests, **80 PostgreSQL tests
passed**. Repository-wide Ruff still reports existing executable-mode, import,
annotation and test-style issues, and formatting flags ten older files; no unrelated
formatting changes were applied.

## Real VnExpress rejection and approval checks

The user selected [VnExpress latest-news RSS](https://vnexpress.net/rss/tin-moi-nhat.rss)
for a single live test. Its current response supplied 52 parsed entries, but none
had an excerpt meeting the existing 200-character adequacy threshold. The threshold
was retained. The development database already held one adequate prepared excerpt
from that feed, article **5**, about Bruno Fernandes and Manchester United:
[original article](https://vnexpress.net/bruno-fernandes-la-nguyen-nhan-hay-nan-nhan-trong-con-khung-hoang-cua-man-utd-5131762.html).
Only the stored RSS excerpt was processed; no article HTML was fetched.

Using a separate temporary reviewed configuration with a note documenting this
user-selected test, real local `VietAI/vit5-base-vietnews-summarization` and real
`gemini-3.8-flash` completed exactly **two drafts**. The final category was `sports`,
with four keywords and `input_truncated=false`. Both drafts were rejected.
Manual comparison confirms the final draft invents a statement by the captain;
the excerpt reports a question about his performance and contains no such speech.
It also supplies no concrete dates or numbers that could justify adding them.
The final candidate has no concrete date/number, but its unsupported attribution
is sufficient for rejection. Gemini's recorded feedback identifies that error.

Atomic persistence saved article 5 as **needs_review**, with `approved=false`,
`draft_attempts=2`, review feedback and both model IDs. A real loopback HTTP request
returned **200**, `processing_status=needs_review`, `summary=null`, `category=null`,
`summary_preview=null`, `input_truncated=null` and `ai_generated=false`. Replaying
processing with a graph that would fail if invoked returned `changed=false`.
The candidate stays in PostgreSQL for audit and is hidden from readers.

The initial excerpt run verifies rejection, termination, persistence and suppression.
The full-text check below subsequently closes approved-result acceptance.

### Approved public full-text article — D6.11 complete

The user next selected [VnExpress World RSS](https://vnexpress.net/rss/the-gioi.rss).
The official RSS directory links that feed and its robots rules permit fetching it.
It returned **60 entries**, with cleaned excerpts of **98–178 characters**; none
meets the unchanged 200-character adequacy threshold. The user explicitly authorized
one linked article's public full text for local ViT5 and Gemini processing.

The selected [Pakistan school-collapse article](https://vnexpress.net/sap-mai-truong-hoc-tai-pakistan-it-nhat-35-nguoi-chet-5132860.html)
was fetched through the existing extractor after its access checks. A temporary
`ArticleExtractionPolicy` allows only that exact public article path and selects
`article.fck_detail`; it records the user's one-off authorization. No access controls
were bypassed. The committed `config/sources.json` remains unchanged.

The development database now holds **source 4**, `VnExpress — Thế giới`, with that
World RSS URL, and **article 41**, with the original URL, publication timestamp,
RSS excerpt and **2,598 cleaned full-text characters**, `content_origin=extracted`.
ViT5 retained **645 tokens**, including EOS, without truncation.

The initial full-text run generated a faithful local draft but its Gemini review
operation failed before returning a decision. It correctly saved `failed` and no
candidate. A separate bounded diagnostic review of that exact real draft succeeded
in one HTTP request (200; 4.16 seconds) and approved it. This indicates an intermittent
provider failure; the first run's exact low-level cause was not retained by the
redacted adapter. No application timeout/retry setting was changed on that basis.

For this authorized acceptance check, one controlled **manual** retry returned only
that failed, summary-free, unchanged article to pending. This is an operator action,
not a new automatic retry or a worker feature. The retry's graph ceiling was lowered
to **one draft**, so the failed run plus manual retry generated only **two local
drafts in total**. The second invocation reran real ViT5 and recomputed real Gemini
metadata; Gemini review approved its first draft. The normal graph ceiling remains
two, and normal processing continues to skip terminal articles.

The completed invocation saved exactly one approved summary (**summary ID 2**),
`draft_attempts=1` for that invocation, category `society`, five distinct keywords,
`input_truncated=false`, both real model IDs, and article status **ready** in the
same transaction. Its stored feedback affirms source support. The ViT5 generation
in the successful invocation took 6.97 seconds; this is a single observation, not a
batch throughput guarantee.

Manual comparison confirmed the draft's locations and numbers: the source's
34 children plus one teacher support the minimum death count, and the injury count
matches the source. The draft adds no date, named person or invented statement.
This comparison checks fidelity to the supplied article, not independent verification
of the news report.

Actual loopback HTTP checks returned **200** for:

- `GET /api/v1/articles/41`: `ready`, `ai_generated=true`, visible summary/category/
  keywords, `content_origin=extracted`, `input_truncated=false`, and both model IDs.
- `GET /api/v1/articles?source_id=4&category=society&q=Pakistan`: one matching item
  with the approved preview and accurate total.
- `GET /api/v1/sources`: source 4 and its World RSS URL are present.
- `GET /api/v1/articles/5`: the previous rejected candidate still has
  `summary=null`, `ai_generated=false` and `needs_review`.

A further processing replay returned `changed=false` without invoking a model.
PostgreSQL contains exactly one summary for article 41. The temporary HTTP server
was stopped after verification.

**D6.11 is complete:** a genuine article passed local ViT5 and Gemini review,
atomic persistence, manual source comparison and actual REST visibility. The
233 unit / 80 PostgreSQL / two live Gemini regression results above still apply;
this follow-up changed documentation and ran the real acceptance procedure, without
changing production code or rerunning unchanged suites.

The committed publisher extraction/AI flags and Day 3 Thanh Niên policy gate remain
unchanged. This user-authorized one-off test does not establish ongoing publisher
clearance or activate a scheduled pipeline.
