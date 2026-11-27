# Todos

Living task list aligned with [vision.md](vision.md). Update it whenever a task is finished, added or dropped (see the documentation rules in [AGENTS.md](../AGENTS.md)). Check a box only after its verification passed. Completed milestone history: [logs/](logs/) and the [archived 14-day plan](archived/14-day-plan-2026-11-08.md).

**Last updated:** 2026-11-27

## Status

| Area | State |
| --- | --- |
| API, database, migrations (`0001`–`0006`) | Done (`0005` and `0006` merged on `master`; `0006` applied on dev DB) |
| RSS ingestion, dedup, text extraction, images | Done (VnExpress, Tuổi Trẻ; paragraph extraction, publisher meta & quality gate merged in `P1.1`) |
| MVP ViT5 + Gemini LangGraph workflow | Review publication gate restored |
| Jobs, worker, scheduler, startup recovery | Done |
| Ingestion refactor (5 phases) | Done, merged 2026-11-25 |
| Reader UI (feed, client filter/search, detail dialog) | MVP mostly done; full routing/search in `P4.3` |
| Docker (`frontend`, `api`, `worker`) | Offline, model isolation and restart checks passed. Live job completion blocked by Gemini HTTP 503 → `P0.3` |
| Post-MVP vision ([vision.md](vision.md)) | `P0.1`–`P0.2` & `P1.1` merged; `P1.2` offline baseline, 50-article cross-source labeled & protected snapshot, and default gate P/R measured; offline work merged on `master`; human label review incomplete and remaining `P1.2` work deprioritised (not dropped) by user direction on 2026-11-27; online Gemini stages last stopped by HTTP 429 on `gemini-3.8-flash` (~430–525 calls vs. ~20 RPD free-tier cap) and not yet retried on `gemini-3.5-flash-lite` |
| Third source (Thanh Niên) | Blocked on reuse terms |

## Agent execution guide

Every milestone below is scoped to be picked up and completed by a coding agent on its own branch:

1. **Read mandatory rules first:** Always read [AGENTS.md](../AGENTS.md) at the start of the session (never read or print `.env`, never expose secrets in logs/tracebacks, pass `--tb=no` and never `--showlocals` on integration/live tests, and never hard-wrap Markdown lines). Also read [frontend/AGENTS.md](../frontend/AGENTS.md) before touching `frontend/`.
2. **Read task context:** Read every document listed under **Read first** in your assigned milestone before planning or editing code.
3. **Create a dedicated branch from `master`:** Ensure `master` is clean and up to date (`git checkout master && git pull --ff-only`), then create the exact branch shown in the milestone (`git checkout -b <branch-name>`). Keep one milestone per branch; do not bundle later phases.
4. **Verify before checking off:** Run unit tests (`uv run --locked pytest -m "not integration" -q`), Ruff check/format, relevant integration/model/frontend checks from [specs/testing.md](specs/testing.md), update any affected spec in [specs/](specs/) and [decisions.md](decisions.md), add a milestone log in [logs/](logs/) (and index it in [logs/README.md](logs/README.md)), then mark `[x]` here and bump **Last updated**.

---

## Priority 0 — Pre-Vision Cleanup, Safety Net & MVP Smoke Checks

Finish these MVP loose ends first so every Vision phase builds on clean imports, green CI, structured logs, and verified container behavior.

### P0.1 Codebase cleanup, Ruff baseline, structured logs & CI

**Why:** Pre-existing Ruff issues, loose scripts in `backend/app/`, missing CI, and plain-text logs will create friction on every later branch.

**Branch:** `git checkout master && git checkout -b chore/cleanup-and-ci`

**Read first:** [AGENTS.md](../AGENTS.md), [decisions.md](decisions.md), [specs/backend.md](specs/backend.md), [specs/ingestion.md](specs/ingestion.md), [specs/testing.md](specs/testing.md).

- [x] Move `SourceConfig` and source config loading out of `backend/app/seed_sources.py` into `backend/app/core/source_config.py`; move `seed_sources.py` and `backfill_article_images.py` into `backend/app/cli/` and update all imports, CLI invocations, tests, and specs ([specs/backend.md](specs/backend.md), [specs/ingestion.md](specs/ingestion.md)).
- [x] Remove the unused `langchain-google-genai` dependency (`uv remove langchain-google-genai`) so `pyproject.toml` and `uv.lock` stay in sync.
- [x] Configure `[tool.ruff]` (`line-length = 100`) and `[tool.ruff.lint]` (`ignore = ["EXE002"]`) in `pyproject.toml`; fix all existing Ruff lint and format issues across `backend/` and `tests/` in a clean `style:` pass.
- [x] Wire `LOG_LEVEL` into Python logging (`backend/app/core/` + `main.py`, `worker.py`, `cli/*`) using a 1-line JSON structured log formatter (`ts`, `level`, `logger`, `event`, `job_id`, `source_id`, `article_id`, `latency_ms`) that never logs secrets, query tokens, or article bodies.
- [x] Add `.github/workflows/ci.yml` running `uv run --locked ruff check backend tests`, `uv run --locked ruff format --check backend tests`, `uv run --locked pytest -m "not integration and not model and not live" -q`, and `npm --prefix frontend ci && npm --prefix frontend run lint && npm --prefix frontend run build`; add the CI status badge to [README.md](../README.md) and note post-MVP CI in [decisions.md](decisions.md).
- [x] Verify the manual-review cleanup and record local checks in the [cleanup log](logs/2026-11-26-cleanup-and-ci.md).

**Done when:** `ruff check`, `ruff format --check`, unit tests, and frontend lint/build pass with zero warnings, logs emit 1-line JSON honoring `LOG_LEVEL`, and GitHub Actions is green.

### P0.2 Restore review publication gate (former R1)

**Why:** Since 2026-11-07 `persist_summary` forces `approved=True`, publishing drafts even when Gemini rejected them.

**Branch:** `git checkout master && git checkout -b fix/review-gate`

**Read first:** [AGENTS.md](../AGENTS.md), [decisions.md](decisions.md), [specs/summarization.md](specs/summarization.md), [specs/database.md](specs/database.md), [logs/2026-11-07-auto-approve-summaries.md](logs/2026-11-07-auto-approve-summaries.md).

- [x] Update `backend/app/services/summary_persistence.py` and `backend/app/services/article_processing.py` so `approved=True` and article status `ready` are set **only** when the graph outcome is `approved`.
- [x] Route rejected outcomes (after max drafts) to `approved=False` and article status `needs_review` (hidden from `/api/v1/articles`), incrementing `ingestion_jobs.articles_needs_review`.
- [x] Record in [decisions.md](decisions.md) that rejected summaries stay hidden (`needs_review`) and that the unused `human_review_*` columns on `summaries` will be dropped in `P2.2`'s migration.
- [x] Update unit and PostgreSQL integration persistence tests (`uv run --locked --env-file .env pytest -m integration tests/integration -q --tb=no`).
- [x] Update [specs/summarization.md](specs/summarization.md) and write a milestone log in [logs/](logs/).

**Done when:** A rejected summary is never returned by `/api/v1/articles`, `articles_needs_review` increments accurately, and unit + integration tests prove it.

### P0.3 MVP Docker & crash-recovery verification

**Why:** Docker images are built, but offline model enforcement, API memory isolation, and mid-job crash recovery have not been verified at runtime yet.

**Branch:** `git checkout master && git checkout -b chore/mvp-runtime-verification`

**Read first:** [AGENTS.md](../AGENTS.md), [specs/deployment.md](specs/deployment.md), [specs/backend.md](specs/backend.md), [specs/testing.md](specs/testing.md), [compose.yaml](../compose.yaml).

- [x] Run the `--network none` offline ViT5 smoke test inside `vietnam-news-backend:local` and confirm a missing `SUMMARIZATION_MODEL_PATH` fails fast with a nonzero exit code without attempting network downloads.
- [x] Confirm the `api` container never imports or loads ViT5 into memory while `worker` preloads it once at startup.
- [ ] Start the full stack via `docker compose up -d`, submit a job via `POST /api/v1/ingestion-jobs`, follow it to completion, and verify structured worker logs, job counters, and reader UI rendering. The live job returned 202 and the UI and counters were verified. Completion remains blocked by Gemini HTTP 503.
- [ ] Verify failure/restart resilience: restart `worker` mid-job (abandoned `running` job marked `failed` on startup, `pending` articles resumed next job); stop `api` while `worker` runs (scheduling and processing continue); observe one real 30-minute scheduled cycle with no overlap. Mid-job recovery and the real 30-minute enqueue behind the active job passed with the API stopped. Scheduled execution through completion remains open.
- [x] Simulate RSS timeout / malformed feed / single-source failure and confirm healthy sources still complete; inspect logs to verify zero leaked credentials, full publisher URLs from HTTPX exceptions, or raw article text.
- [x] Rehearse setup instructions from [README.md](../README.md) and record runtime versions, baseline worker RAM/CPU latency, and smoke results in the [runtime log](logs/2026-11-26-mvp-runtime-verification.md).

**Done when:** Offline model checks, full Compose stack execution, and crash-recovery checks are verified and logged.

---

## Priority 1 — Phase 1: Clean Input, Quality Gate & Evaluation Baseline

Fix HTML paragraph extraction once and establish reproducible baseline metrics **before** replacing the AI loop.

### P1.1 Paragraph-preserving HTML extraction, single-pass `<meta>` capture & quality gate (upgraded R2)

**Why:** `clean_text()` currently flattens `<p>` tags into spaces and only checks `len >= 200`, letting RSS teasers, gallery stubs, and boilerplate reach ViT5 while discarding publisher metadata.

**Branch:** `git checkout master && git checkout -b feat/text-quality-gate`

**Read first:** [AGENTS.md](../AGENTS.md), [vision.md](vision.md) (Section 1: Quality gate, Categories and tags), [specs/ingestion.md](specs/ingestion.md), [specs/database.md](specs/database.md), [specs/source-evidence.md](specs/source-evidence.md).

- [x] Update `backend/app/services/article_extractor.py` to strip `<figcaption>`, `figure`, related-article boxes, and share/comment blocks in DOM while preserving paragraph breaks (`\n\n`) from `<p>` blocks instead of flattening text into one line.
- [x] In the **same single BeautifulSoup parse pass**, extract raw publisher `<meta>` tags (`article:section`, `its_subsection`, `news_keywords`, `article:tag`, `its_tag`, `its_type`, `its_wordcount`) and store raw publisher section, keywords, and content-type hints on `articles` via a new Alembic migration (test upgrade → repeated upgrade → downgrade → re-upgrade).
- [x] Never summarize `content_origin=rss_excerpt` rows; route them to `needs_review` with reason code `rss_excerpt_only`.
- [x] Replace `MIN_TEXT_CHARACTERS = 200` with combined deterministic signals: minimum word count, sentence count, token overlap with RSS title/description, duplicate-line ratio, boilerplate phrase blocklist (`"Đăng nhập"`, `"Xem thêm"`, …), `its_type` photo/video check, and `/video/` or `/photo/` URL patterns; store exact failing reason codes in `articles.processing_error`.
- [x] Add fixture-based unit tests and PostgreSQL migration integration tests; update [specs/ingestion.md](specs/ingestion.md) and [specs/database.md](specs/database.md); write a milestone log in [logs/](logs/).

- [ ] Detect and exclude quiz/puzzle content at the quality gate (user requirement, 2026-11-27; calibration article 84 identified as an unwanted quiz), with a clear rejection reason, fixture tests and an update to [specs/ingestion.md](specs/ingestion.md). No dedicated detection exists in the current gate; avoid treating ordinary news questions as quizzes.

**Done when:** Paragraph breaks and publisher `<meta>` fields are captured in one pass, no RSS excerpt or video/photo stub reaches summarization, and every rejection stores a clear reason code.

### P1.2 Evaluation harness, synthetic error set & ~50-article calibration (upgraded R3)

**Why:** Every later change in [vision.md](vision.md) requires a reproducible before/after number, calibrated once against human labels so the automated judge is trustworthy.

**Status (2026-11-27):** Remaining P1.2 work is deprioritised, not dropped; this milestone is not done. An independent AI review labelled all 50 items using stored text only, without reading live article bodies. The user then checked selected items: 94 and 95 were fine, 84 was an unwanted quiz, and the user had no opinion on the other disputed items (54, 62, 63, 65, 71, 75, 90). The user chose to stop label work and not prioritise ViT5 performance for now. These selected comments are not human labels for all 50 items and do not establish human-to-judge agreement.

**Branch:** `git checkout master && git checkout -b feat/evaluation-baseline`

**Read first:** [AGENTS.md](../AGENTS.md), [vision.md](vision.md) (Guiding rules & Section 2: Evaluation first), [specs/summarization.md](specs/summarization.md), [specs/testing.md](specs/testing.md).

- [ ] Create a frozen evaluation dataset (~50 real stored articles across active sources flagged exempt from 30-day content deletion, with one-time human labels for extraction validity and summary faithfulness) plus a held-out slice of the `vietnews` dataset. The frozen, protected snapshot and the `vietnews` slice are done; its labels are AI-assisted, not a 50-item human-label dataset; human review remains incomplete and is deprioritised, not dropped.
- [ ] Tune `P1.1`'s quality-gate thresholds against Gemini + human calibration labels and record measured precision/recall (default gate measured at precision `0.9592`, recall `1.0000`, F1 `0.9792` vs. 50 labeled articles; Gemini-paired tuning waits for 429 quota reset).
- [x] Implement a deterministic synthetic error injector over known-good summaries (`vietnews` references + accepted summaries) creating sentence-labeled corruptions: number mutation, proper-name swap, date shift, clause negation, and cross-article sentence insertion.
- [x] Build a single reproducible CLI (`python -m app.cli.eval`) outputting: ViT5 ROUGE on held-out `vietnews`, synthetic catch rate and false-accept rate, human-to-judge agreement (Cohen's κ) and real-paraphrase false-reject rate on the ~50-article calibration set, judge stability across 2 identical runs, CPU latency/article, peak RSS RAM, and logical/wire Gemini calls per article.
- [ ] Run `python -m app.cli.eval` online stages (`synthetic`, `calibration`, `stability`, `graph`) on the current MVP summarization pipeline once Gemini API 429 quota resets, and commit the completed **baseline** Markdown report to [logs/](logs/).

The evaluator supports paced requests and individual online stages. The [evaluation baseline](logs/2026-11-26-evaluation-baseline.md) records held-out ViT5 metrics, the 50-article cross-source AI-assisted labeled & protected snapshot (30 VnExpress + 20 Tuổi Trẻ, `evaluation_exempt=True`), default quality-gate P/R (`0.9592` / `1.0000`, F1 `0.9792`), and 24 synthetic cases. The live Gemini stages were last stopped by HTTP 429 (`retry_deferred: true`) on `gemini-3.8-flash`. Review the 50 labels before relying on human-to-judge κ, and run all online stages on one named model. Running all four full online stages requires ~430–525 logical Gemini calls (exceeding typical ~20 RPD free-tier caps), so completing them needs Tier 1 billing, a higher-RPD model, or checkpointed stage slicing.

**Done when:** One command reproduces the baseline evaluation report, quality-gate precision/recall and judge Cohen's κ are recorded, and frozen eval fixtures are protected from retention cleanup.

---

## Priority 2 — Phase 2: Deterministic Summarize–Verify Agent Loop

Replace the blind 2-draft LangGraph loop with the code-routed, citation-checked, offline-replayable workflow from [vision.md](vision.md).

### P2.1 Paragraph/sentence preparation & ViT5 long-input tuning

**Why:** ViT5-base fails mainly on noisy captions/bylines and arbitrary 1,024-token cutoffs, while sentence citations require reliable Vietnamese sentence numbering.

**Branch:** `git checkout master && git checkout -b feat/sentence-prep-vit5`

**Read first:** [AGENTS.md](../AGENTS.md), [vision.md](vision.md) (Section 2: Help ViT5 first), [specs/summarization.md](specs/summarization.md), `backend/app/services/summary_service.py`.

- [ ] Implement `Prepare` in Python: strip trailing author bylines and `"Xem thêm"` lines at paragraph level, split sentences within paragraphs first using an abbreviation-aware Vietnamese splitter (`TP.`, `TS.`, `ThS.`, `PGS.`, `GS.`, `UBND.`, `HĐND.`, initials, and `1.500`-style thousand separators never split sentences), and emit numbered source sentences `[1]..[N]`.
- [ ] For inputs exceeding 1,024 ViT5 tokens, implement contiguous `lead paragraphs + final concluding paragraph` packing (up to 1,023 tokens + EOS) and benchmark ROUGE + faithfulness against plain head truncation via `python -m app.cli.eval`; ship only if it improves metrics.
- [ ] Tune single-draft ViT5 decoding parameters (`num_beams`, `length_penalty`, `min_new_tokens`) against the evaluation set; add unit tests covering tricky Vietnamese sentence boundaries and update [specs/summarization.md](specs/summarization.md).

**Done when:** Source sentences are cleanly numbered without breaking on Vietnamese abbreviations/numbers, and ViT5 input selection + decoding are backed by `eval` numbers.

### P2.2 `summary_attempts` schema & code-checked Summarize–Verify–Escalate loop

**Why:** Models should only produce candidate text or structured per-sentence evidence while pure Python code decides keep, coherent trim, escalation, or rejection.

**Branch:** `git checkout master && git checkout -b feat/summarize-verify-loop`

**Read first:** [AGENTS.md](../AGENTS.md), [vision.md](vision.md) (Section 2: Summarize–verify loop), [decisions.md](decisions.md), [specs/summarization.md](specs/summarization.md), [specs/database.md](specs/database.md).

- [ ] Add an Alembic migration creating immutable `summary_attempts` (`1:N` per article: model version, prompt version, config hash, candidate sentences, local check flags, Gemini verdicts, `cited_ids`, `answers_headline`, decision, latency_ms), adding `winning_attempt_id` FK and `summary_source` (`vit5`, `vit5_trimmed`, `gemini`) to `summaries`, updating `draft_attempts` constraints as needed, and dropping the unused `human_review_*` columns and check constraint.
- [ ] Decouple metadata/tagging into a standalone per-article step outside the summary loop so summary verification/escalation never re-runs tagging.
- [ ] Implement Python `Local checks` per sentence: canonicalized digits/percentages/dates (`1.500` → `1500`, `25-11` / `ngày 25 tháng 11` → `25/11`), Unicode NFC + alias-expanded multi-syllable Title-Case spans (≥ 2 consecutive capitalized words not at sentence index 0), repeated-sentence check, and cut-off trailing-sentence check.
- [ ] Implement Python `Coherent trim` rules: (a) sentence 1 survives, (b) total surviving words ≥ `min_words` (~25, configurable), and (c) no kept sentence `k > i` after a dropped sentence `i` begins with anaphoric/contrastive connectors (`Tuy nhiên`, `Do đó`, `Theo đó`, `Ngoài ra`, `Ông `, `Bà `, `Người này`, `Cơ quan này`, `Điều này`); escalate directly to Gemini write without calling `Verify` if local drops fail (a)–(c).
- [ ] Implement blind Gemini `Verify` (`temperature=0`, strict JSON schema returning per-sentence `supported` / `not_supported` + `cited_ids` and summary-level `answers_headline: bool`, with model-blind payload `(title, numbered_source_sentences, candidate_sentences)`) plus Python's judge check verifying every canonicalized number, date, and multi-syllable Title-Case span appears in `cited_ids ± 1 neighbor sentence ∪ {title}`.
- [ ] Implement pure-Python `Decide` (`vit5` / `vit5_trimmed` / escalate) and `Escalate` (`Gemini 2–4 sentence write → Python local checks + fresh stateless blind Verify → gemini | needs_review`).
- [ ] Record in [decisions.md](decisions.md) that Gemini may write verified fallback summaries (`summary_source='gemini'`); cover all branches and migrations with unit + PostgreSQL integration tests; update [specs/summarization.md](specs/summarization.md) and [specs/database.md](specs/database.md).

**Done when:** Every loop branch is decided by deterministic Python functions, Gemini fallback drafts undergo a fresh blind re-check, and every attempt is recorded in `summary_attempts`.

### P2.3 Infra resilience, offline `replay` CLI & before/after evaluation report

**Why:** Provider outages must not mark good articles as quality failures, and threshold tuning should run offline on stored attempts with zero API cost.

**Branch:** `git checkout master && git checkout -b feat/agent-replay-resilience`

**Read first:** [AGENTS.md](../AGENTS.md), [vision.md](vision.md) (Section 2: Limits, error handling, replay), [specs/summarization.md](specs/summarization.md), [specs/backend.md](specs/backend.md).

- [ ] Distinguish Gemini infrastructure errors (timeout, 429, 5xx, malformed JSON after HTTP retry) from quality rejections: keep affected articles `pending` with retry count and backoff, mark `failed` only after 3 job cycles, and add a worker circuit breaker that skips Gemini calls when recent calls fail.
- [ ] Build `python -m app.cli.replay` to re-execute Python local checks, citation checks, coherent-trim rules, and `Decide` under new config thresholds on stored `summary_attempts` rows without calling ViT5 or Gemini.
- [ ] Run `python -m app.cli.eval` on the new loop and write a milestone log in [logs/](logs/) comparing before vs. after synthetic catch rate, false-accept rate, real-paraphrase false-reject rate, Cohen's κ, `vit5_trimmed` save rate, escalation rate, and logical/wire Gemini calls per article.

**Done when:** Transient Gemini failures never approve or prematurely fail articles, `replay` runs 100% offline, and the before/after evaluation report is committed.

---

## Priority 3 — Phase 3: Multi-Categories, Tags, Story Clusters & Monitoring

Turn isolated articles into a multi-category, entity-tagged, deduplicated, and monitored dataset.

### P3.1 Multi-categories & grounded typed tags

**Why:** Articles often span multiple topics (e.g. *Kinh doanh*, *Công nghệ*, and *Pháp luật*), and free-text per-summary keywords cannot power filters, trending topics, or user interests.

**Branch:** `git checkout master && git checkout -b feat/categories-and-tags`

**Read first:** [AGENTS.md](../AGENTS.md), [vision.md](vision.md) (Section 1: Categories and tags), [specs/database.md](specs/database.md), [specs/summarization.md](specs/summarization.md), [specs/backend.md](specs/backend.md).

- [ ] Add an Alembic migration creating `categories` (~10–12 publisher-aligned categories replacing the 6-value enum), `article_categories` (many-to-many with `is_primary` and `origin`), `tags` (`name`, accent-free `slug`, `type` in `person|organization|place|topic`), `article_tags` (`origin` in `gemini|publisher`), and `tag_aliases`; migrate existing rows cleanly and test full upgrade/downgrade lifecycle.
- [ ] Map raw publisher sections (`article:section`, `its_subsection`) to primary categories when present; update the single per-article Gemini tagger call to assign 1–3 categories (marking one `is_primary`) plus typed tags.
- [ ] In Python, drop `person`/`organization`/`place` tags absent from the source text after Unicode NFC normalization, casefolding, and `tag_aliases` expansion (`TP.HCM` ↔ `Thành phố Hồ Chí Minh`); track agreement between Gemini and publisher primary categories.
- [ ] Update `/api/v1/articles` list/detail schemas and query filters to return `primary_category`, `categories[]`, and `tags[]`; update [specs/database.md](specs/database.md) and [specs/backend.md](specs/backend.md); write a milestone log in [logs/](logs/).

**Done when:** Articles support 1 primary + optional secondary categories and grounded shared tags, and publisher ↔ Gemini category agreement is measurable.

### P3.2 `pgvector` embeddings, `story_clusters` & similarity verification

**Why:** VnExpress and Tuổi Trẻ cover the same breaking events; clustering cross-source duplicates enables *"Cùng sự kiện"* and *"Tin liên quan"* without adding RAM to the worker.

**Branch:** `git checkout master && git checkout -b feat/story-clusters`

**Read first:** [AGENTS.md](../AGENTS.md), [vision.md](vision.md) (Section 1: Near-duplicates and story clusters, Open questions), [specs/database.md](specs/database.md), [specs/ingestion.md](specs/ingestion.md).

- [ ] Add an Alembic migration enabling `pgvector`, adding `halfvec` embedding storage on `articles` (`title + first paragraph` via Gemini Embedding API; benchmark 256 vs. 512 dims), and creating `story_clusters` and `article_similarity`.
- [ ] Query cross-source nearest neighbours within a 48h window on ingestion; group matches above threshold into `story_clusters`, and log top-`K` (`K = 5` or similarity ≥ 0.45) plus a 1% stratified sample of lower-score pairs in `article_similarity` (pair, score, decision).
- [ ] Build a non-blocking periodic verification CLI/job sampling logged pairs across score bands (above, near, and below threshold), deciding clear pairs via deterministic signals (shared names, numbers, dates, places) and calling Gemini only for borderline pairs, storing verdicts to estimate threshold precision/recall over time.
- [ ] Update [specs/database.md](specs/database.md) and [specs/ingestion.md](specs/ingestion.md); write a milestone log in [logs/](logs/).

**Done when:** Cross-source stories cluster automatically within 48h, `article_similarity` stays compact, and threshold precision/recall is measured.

### P3.3 Idempotent reprocessing, 30-day retention & monitoring analytics

**Why:** Model/prompt upgrades need clean reprocessing over retained text, database growth must stay bounded, and pipeline health needs SQL views + a reproducible analysis report.

**Branch:** `git checkout master && git checkout -b feat/monitoring-and-retention`

**Read first:** [AGENTS.md](../AGENTS.md), [vision.md](vision.md) (Section 1: Reprocessing, Monitoring and analysis), [specs/database.md](specs/database.md), [specs/backend.md](specs/backend.md).

- [ ] Build `python -m app.cli.reprocess` to idempotently re-run summarization on selected articles within the ~30-day full-text window (plus frozen eval fixtures), recording new `summary_attempts` rows and upserting `summaries.winning_attempt_id`.
- [ ] Add scheduled retention tasks: clear `articles.content` older than ~30 days (preserving title, summary, categories, tags, URL, and frozen eval fixtures) and roll up granular operational logs into daily summary tables.
- [ ] Add SQL views via Alembic (`v_daily_ingestion`, `v_daily_summary_outcomes`, `v_rejection_reasons`, `v_similarity_bands`, `v_publish_to_ready_latency`, `v_db_size`) and document a read-only Postgres role for Grafana Cloud (and/or `GET /api/v1/stats`).
- [ ] Run an analysis script (`polars`/`pandas` + `matplotlib`) over collected rejection, escalation, and duplicate-similarity data and commit a charted Markdown analysis report in [logs/](logs/).

**Done when:** Reprocessing and 30-day retention run idempotently, SQL monitoring views are live, and the data analysis report with charts is committed.

---

## Priority 4 — Phase 4: Efficiency, Fast API & Complete Reader

Shrink worker memory for free-tier hosting and finish the fast, searchable single-user reader experience.

### P4.1 ONNX + int8 ViT5 worker optimization

**Why:** Worker RAM (~1.3 GiB in FP32 PyTorch) dictates hosting cost; quantizing ViT5 to ONNX int8 lowers RAM and CPU latency if summary quality holds.

**Branch:** `git checkout master && git checkout -b feat/onnx-int8-vit5`

**Read first:** [AGENTS.md](../AGENTS.md), [vision.md](vision.md) (Section 3: Light worker), [specs/summarization.md](specs/summarization.md), [specs/deployment.md](specs/deployment.md).

- [ ] Export `VietAI/vit5-base-vietnews-summarization` to ONNX with int8 weights and update offline artifact manifest validation (`model_artifacts.py`, `download_summarization_model.py`, `backend/Dockerfile`).
- [ ] Benchmark FP32 PyTorch vs. ONNX int8 using `python -m app.cli.eval` and `--smoke-test`: peak RSS RAM, p50/p95 CPU latency, Docker image size, `vietnews` ROUGE, and faithfulness/escalation rates.
- [ ] Make ONNX int8 the default runtime **only** if quality holds on `eval`; commit the before/after table in [logs/](logs/) and update [specs/summarization.md](specs/summarization.md) and [specs/deployment.md](specs/deployment.md).

**Done when:** Before/after RAM, latency, image size, and quality numbers are published in [logs/](logs/) and offline `--network none` inference passes.

### P4.2 PostgreSQL `unaccent` search, keyset pagination & API hardening (upgraded R7)

**Why:** Client-side full-feed fetching breaks as articles grow; server-side Vietnamese search, keyset pagination, and caching keep API `p95 < 200 ms`.

**Branch:** `git checkout master && git checkout -b feat/api-search-perf`

**Read first:** [AGENTS.md](../AGENTS.md), [vision.md](vision.md) (Section 3: Fast pages, Targets, Basics), [specs/database.md](specs/database.md), [specs/backend.md](specs/backend.md).

- [ ] Add an Alembic migration enabling PostgreSQL `unaccent` + full-text search index on titles/summaries and composite keyset pagination index `(COALESCE(published_at, created_at) DESC, id DESC)`; verify query plans with `EXPLAIN ANALYZE`.
- [ ] Update `GET /api/v1/articles` and `GET /api/v1/articles/{id}` with keyset pagination cursors, diacritic-insensitive search (`q`), multi-category/tag/source filters, related articles (**"Cùng sự kiện"** from `story_clusters` + **"Tin liên quan"** from nearest embeddings), and HTTP `Cache-Control` / `ETag` headers.
- [ ] Add rate limiting, strict CORS, security response headers, and request input limits; load-test the read API to confirm `p95 < 200 ms` and log before/after results in [logs/](logs/).

**Done when:** Search is diacritic-insensitive in PostgreSQL, pagination uses keyset cursors, indexes are verified with `EXPLAIN ANALYZE`, and load-tested API `p95 < 200 ms`.

### P4.3 Complete Reader UI, routing & mobile performance (upgraded R4)

**Why:** Connects the upgraded multi-category, tagged, clustered API to a fast, accessible mobile-first Vietnamese reader.

**Branch:** `git checkout master && git checkout -b feat/reader-complete`

**Read first:** [AGENTS.md](../AGENTS.md), [frontend/AGENTS.md](../frontend/AGENTS.md), [vision.md](vision.md) (Sections 2–4), [specs/frontend.md](specs/frontend.md), [specs/backend.md](specs/backend.md).

- [ ] Replace the multi-page fetch loop in `frontend/src/services/api.ts` with cursor/keyset pagination, debounced server-side search (`q`), multi-category filter, clickable tag chips, and source filter backed by `AbortController`.
- [ ] Add route-based navigation (`/articles/:id` plus `/ingestion` or `/stats` dashboard view) with route code-splitting, preserving feed scroll/filter state when navigating back, loading skeletons, 404/error retry states, and fixed-size `loading="lazy"` images.
- [x] Implement the [RSS description + AI summary display decision](vision.md#rss-description-and-ai-summary-together-implemented-reviewed): expose the stored `rss_description` in the article API schema/routes and frontend types, show the full description and full approved ViT5 summary as “Mô tả từ báo” and “Tóm tắt AI” with attribution and original link, without filtering/merging. Handle missing blocks without changing article visibility or exposing non-approved summaries; confirm publisher terms against [source evidence](specs/source-evidence.md), add API/reader tests and update [specs/backend.md](specs/backend.md) and [specs/frontend.md](specs/frontend.md). Implemented on `feat/rss-summary-display` on 2026-11-27; independent review round 2 PASS after round 1 fixes, including reviewer PostgreSQL integration and live GET-only reader checks; see the [milestone log](logs/2026-11-27-rss-summary-display.md). The rest of P4.3 remains open.
- [ ] Render the model transparency chip (`Tóm tắt AI · ViT5` for `vit5`/`vit5_trimmed`, `Tóm tắt AI · Gemini` for `gemini`), truncation/collection-time labels, and **"Cùng sự kiện"** + **"Tin liên quan"** cards on article detail.
- [ ] Verify mobile/desktop responsiveness, keyboard focus/navigation, and Lighthouse mobile performance ≥ 90; update [specs/frontend.md](specs/frontend.md) and write a milestone log in [logs/](logs/).

**Done when:** Full reader navigation, filters, related stories, and model chips work end-to-end on mobile and desktop with Lighthouse mobile ≥ 90.

---

## Priority 5 — Phase 5: Invite-Only Product, Feedback, Deployment & Launch

Close the user feedback loop safely under personal/invite-only terms and package the portfolio showcase.

### P5.1 Invite-only Supabase Auth, user interests & personalized feed

**Why:** Lets a small invited group personalize their feed and flag bad summaries (`"tóm tắt sai"` → evaluation set) without open public redistribution.

**Branch:** `git checkout master && git checkout -b feat/auth-and-personalization`

**Read first:** [AGENTS.md](../AGENTS.md), [frontend/AGENTS.md](../frontend/AGENTS.md), [vision.md](vision.md) (Sections 3–5), [decisions.md](decisions.md), [specs/database.md](specs/database.md), [specs/backend.md](specs/backend.md), [specs/frontend.md](specs/frontend.md), [specs/source-evidence.md](specs/source-evidence.md).

- [ ] Integrate Supabase Auth in invite-allowlist mode (email, optional Google; no open public sign-up); verify Supabase JWTs in FastAPI, scope all user queries by `user_id`, and enforce PostgreSQL Row Level Security (RLS) on user tables (`user_preferences`, `article_feedback`).
- [ ] Build onboarding and preferences UI for selecting favorite categories, tags, and sources, plus 👍/👎 article feedback with optional reason (`"tóm tắt sai"`, `"không quan tâm"`).
- [ ] Auto-add articles receiving 👎 `"tóm tắt sai"` into the evaluation review queue, and implement SQL-scored personalized feed ordering (interest overlap + recency + user feedback).
- [ ] Record the invite-only auth decision in [decisions.md](decisions.md), add unit/integration auth & RLS tests, and update [specs/database.md](specs/database.md), [specs/backend.md](specs/backend.md), and [specs/frontend.md](specs/frontend.md).

**Done when:** Invited users can sign in, pick interests, read a personalized feed, and submit 👍/👎 feedback with JWT + RLS isolation verified by tests.

### P5.2 Hosted beta deployment & Sentry crash monitoring

**Why:** Runs the full loop unattended with crash alerts while respecting publisher terms and free-tier RAM budgets.

**Branch:** `git checkout master && git checkout -b feat/deployment-and-sentry`

**Read first:** [AGENTS.md](../AGENTS.md), [vision.md](vision.md) (Section 5: Deployment), [specs/deployment.md](specs/deployment.md), [specs/source-evidence.md](specs/source-evidence.md).

- [ ] Add `sentry-sdk` (`send_default_pii=False`, tagging only `job_id`, `source_id`, `article_id`—never article text or secrets) to `api` and `worker`.
- [ ] Recheck publisher RSS/usage terms in [specs/source-evidence.md](specs/source-evidence.md) before inviting users; verify source attribution (`Nguồn: …`) and prominent original links on every screen.
- [ ] Deploy the Compose stack on a free VM sized from `P4.1` RAM numbers (e.g. Oracle Always Free Arm, or static frontend + free API host + local worker fallback) with HTTPS, internal-only service ports, and uptime/publish-to-summary latency tracking; document in [specs/deployment.md](specs/deployment.md) and [logs/](logs/).

**Done when:** The invite-only beta runs unattended with Sentry error tracking and publish-to-summary `p50`/`p95` tracked.

### P5.3 Diagrams, demo video & Portfolio README (upgraded R6)

**Why:** [README.md](../README.md) and the demo video are the front door for engineers and recruiters reviewing the project.

**Branch:** `git checkout master && git checkout -b docs/portfolio-launch`

**Read first:** [AGENTS.md](../AGENTS.md), [vision.md](vision.md) (Section 6 & Target numbers), [architecture.md](architecture.md), [README.md](../README.md), [logs/README.md](logs/README.md).

- [ ] Draw the 4 headline diagrams (`system overview`, `data pipeline funnel`, `summarize–verify loop`, `deployment map`) following `diagram-design` and embed them cleanly in [README.md](../README.md).
- [ ] Capture mobile/desktop screenshots and record a 1–2 minute end-to-end demo video.
- [ ] Update the top of [README.md](../README.md) with the single-loop story, diagrams, engineering highlights (`FOR UPDATE SKIP LOCKED`, idempotent ingestion, code-checked blind `Verify` loop, `pgvector` story clusters, ONNX int8 ViT5), and verified metrics table (`vietnews` ROUGE, human-to-judge κ, false-accept & escalation rates, duplicate P/R, worker RAM/latency before/after int8, API p95, Lighthouse score, logical Gemini calls/article) while keeping local setup reproducible in a fresh checkout.

**Done when:** [README.md](../README.md) opens with the pitch, diagrams, demo video, and verified numbers from [logs/](logs/), and fresh setup still works end-to-end.

---

## Gate-Driven & Blocked

- [ ] **ViT5 distillation & preference fine-tuning (`feat/vit5-finetune`):** Start **only** once `summary_attempts` logs ≥ 1,000 `(vit5_rejected, gemini_accepted)` preference pairs **and** post-cleaning ViT5 escalation remains > 20%; read [vision.md](vision.md) (Feedback loop for ViT5) and ship only if `python -m app.cli.eval` improves.
- [ ] **Thanh Niên third source (`feat/source-thanh-nien`):** Blocked until footer copyright/reuse terms in [specs/source-evidence.md](specs/source-evidence.md) are resolved; keep inactive (`2` active sources + `1` policy-blocked source is the accepted baseline).

## MVP acceptance gates

- [x] Active sources reviewed with explicit policy gates and attribution (`2` active: VnExpress, Tuổi Trẻ; `1` intentionally inactive: Thanh Niên).
- [x] Alembic schema reachable from API and worker; repeated ingestion makes no duplicates.
- [x] Real ViT5 generates Vietnamese summaries; real Gemini supplies metadata/review.
- [x] Graph stops after bounded attempts.
- [x] Newly rejected summaries are hidden from the article API (`P0.2`).
- [x] Manual `202` + polling and 30-minute scheduling; crash recovery keeps committed results.
- [x] Compose offline `--network none` model smoke and mid-job restart smoke verified (`P0.3`).
- [x] Lockfiles, Ruff lint/format, and CI quality gate pass (`P0.1`).
- [ ] End-to-end search/filter/detail reader UI and reproducible README setup/demo complete (`P4.3`, `P5.3`).
