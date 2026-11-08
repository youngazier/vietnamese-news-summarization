# Vietnamese AI News Aggregator & Summarizer

**Project type:** Full-stack learning project / two-week MVP  
**Status:** Architecture specification; Day 2, D3.2–D3.9 and Days 4–7 implemented and verified, including a genuine approved result through REST; D3.1 third-source reuse and ongoing publisher extraction/AI clearance remain open; worker/jobs/scheduling are implemented; frontend is next (updated 2026-10-15)  
**Runtime scope:** Local-only, single user; authentication and authorization deferred  
**Target duration:** 14 calendar days (adjust for actual available hours)  
**Primary language:** Vietnamese for news content/UI; English for code and internal documentation  
**Guiding principle:** Build a simple, working vertical slice first; add complexity only when it addresses a demonstrated need.

---

The [implementation plan](todos.md) contains priorities, dependencies, file-level tasks, contracts, the 14-day schedule, risks and exact acceptance checks. The [Day 2 guide](day-2-setup.md) covers implemented sessions, migrations and database/API tests. [Source evidence](source-evidence.md) records the feed-policy boundary. Implement one requested phase at a time; distinguish fixture checks from live verification.

## 1. Product vision and MVP scope

Create a Vietnamese-language news website that collects articles from a small, curated set of Vietnamese publishers' RSS feeds, extracts legally accessible content, deduplicates results, uses a LangGraph workflow with local ViT5 summarization and Gemini-powered classification/review to **summarize and categorize** articles, stores the output in managed PostgreSQL, and makes it available via a FastAPI-backed React interface.

### User-facing MVP

- Browse news cards sorted by newest first with title, publication time, source, category, preview, and a clear link to the original publisher.
- Read a Vietnamese AI-generated summary and keywords for each successfully processed article.
- Search by title and filter by source/category; paginate results.
- Show loading, empty, and error states; hide or label unapproved/incomplete summaries.
- Optional local manual collection trigger and ingestion status view for the single user; no login, roles, or authorization checks in this MVP.

### Background MVP

- Collect RSS from **three verified, permitted sources initially**; configure them in a database or seed file. Do not invent feed URLs.
- Normalize article URLs and deduplicate with a database uniqueness constraint.
- Extract usable text when permitted; fall back to RSS description where appropriate; label the source-text quality.
- Process each new article through a bounded LangGraph workflow with structured LLM output and review.
- Persist articles, summaries, category/keywords, source provenance, and ingestion job status.
- Automatically schedule ingestion every 30 minutes; also allow a local manual trigger.
- Use logs and a health endpoint for basic observability.

### Explicitly out of scope for the 14-day MVP

- Redis; Prometheus; Grafana; Jenkins; Kafka; RabbitMQ; Celery; Kubernetes; microservices.
- Authentication, authorization, public hosting, user accounts, personalized recommendations, semantic/vector search, pgvector, real-time chat, paid article bypassing, comprehensive crawling, scraping at scale, multi-agent debate, custom model training.
- Separate LangGraph deployment server, persistent graph checkpoints, or a second database.
- Fully autonomous publishing/verification claims. All summaries are **AI-generated, potentially imperfect**, and link to their sources.

---

## 2. Final technology decisions

| Concern | Selected stack | Notes |
|---|---|---|
| Frontend | React, Vite, TypeScript | SPA with article list/detail/filter screens |
| Backend API | FastAPI, Pydantic | Synchronous DB handlers; heavy model calls belong to worker |
| ORM | SQLAlchemy 2.x | Typed models and short-lived database sessions |
| Migrations | Alembic | Only one controlled migration command; no production `create_all()` |
| DB | **Supabase hosted PostgreSQL** | Single source of truth; access via SQLAlchemy/psycopg |
| Summarization | `VietAI/vit5-base-vietnews-summarization`, Transformers + PyTorch + SentencePiece | Weights/tokenizer baked into image at build time; local inference |
| Agent API | Gemini Developer API via official `google-genai` SDK, Interactions API | Structured metadata/review inside LangGraph nodes; configurable model |
| Python tooling | **uv** | Root `pyproject.toml` and committed `uv.lock`; `uv sync` / `uv run` |
| AI orchestration | LangGraph `StateGraph` | Deterministic draft/review/retry workflow |
| Optional tool-calling | SDK function calling or LangChain `create_agent` | Add only after basic graph is stable |
| RSS collection | `feedparser`, `httpx` | Limited concurrency, timeouts, retries and user-agent |
| Text extraction | Python HTML extraction library, e.g. BeautifulSoup | Fetch only publisher-allowed URLs; fallback to RSS excerpt |
| Scheduling | APScheduler **3.x** | Standalone scheduler inside worker; explicitly pin major version |
| Job coordination | PostgreSQL `ingestion_jobs` table | Lightweight polling; **not** a full distributed queue |
| Local frontend serving | Vite on host | Loopback-only dev server; proxy `/api` to FastAPI; Nginx deferred |
| Backend containers | Docker + Docker Compose | **Exactly two default Compose services: `api` and `worker`** |
| Testing and quality | pytest, Ruff, httpx test client | Frontend build/type check as appropriate |
| Basic operations | Structured logs, `GET /health` | No Prometheus/Grafana |

**Version compatibility:** Keep the existing Python 3.12 runtime, root `pyproject.toml` and `uv.lock`. The [dependency audit](todos.md#dependency-audit-and-official-references) records installed versions and unresolved checks. Retain APScheduler 3.x and Transformers 4.x; verify CPU PyTorch wheels and actual ViT5 inference before claiming model compatibility.

**Why one modular monolith?** API routes, DB models, collector, AI graph, and persistence modules live in one Python project and can be imported by both API and worker. Deployment has separate processes, not separate independently versioned services.

---

## 3. System context and architecture

### 3.1 Local runtime / service boundaries

```mermaid
flowchart TB
    Reader[Single local user / Web browser]
    Publisher[Permitted Vietnamese RSS sources]
    Provider[Gemini Developer API]
    DB[(Supabase PostgreSQL)]

    subgraph Host[Host / Container Environment]
      subgraph Compose[Docker Compose: 3 services]
        FE[frontend: Nginx + React SPA]
        API[api: FastAPI / SQLAlchemy]
        WK[worker: APScheduler + RSS + LangGraph + local ViT5]
      end
    end

    Reader -->|HTTP :5173| FE
    FE -->|Static HTML/CSS/JS| Reader
    FE -->|Internal proxy /api/*| API
    API <-->|SQLAlchemy queries| DB
    WK <-->|Jobs, articles, summaries| DB
    Publisher -->|HTTP/RSS fetch| WK
    WK <-->|Classification / keywords / review| Provider
```

**Interpretation:** Compose orchestrates three services: `frontend` (Nginx serving built React static assets and reverse-proxying `/api` to the backend), `api` (FastAPI), and `worker` (APScheduler, ViT5, and Gemini review), with `api` and `worker` sharing the backend image containing the ViT5 model. For host-based development, Vite can also run directly on the host and proxy to loopback. Supabase and Gemini remain external managed services.

### 3.2 Request path vs ingestion path

- **Read path:** Browser → Vite proxy → FastAPI → SQLAlchemy → Supabase → JSON → React.
- **Scheduled write path:** APScheduler (worker) → RSS collector → canonicalization/dedup → extract → LangGraph → SQLAlchemy → Supabase.
- **Manual write path (local user):** Unauthenticated local request → FastAPI inserts **pending job** → worker polls/claims job → same ingestion pipeline; API returns `202 Accepted` immediately.
- The browser never connects to worker, database service credentials, or the LLM provider directly.
- API and worker communicate **indirectly through PostgreSQL job and article records**, not HTTP RPC between containers.

### 3.3 Manual job sequence

```mermaid
sequenceDiagram
    participant User as Local user
    participant API as FastAPI
    participant PG as Supabase PostgreSQL
    participant WK as Worker
    participant RSS as RSS publisher
    participant Model as Local ViT5 (preloaded)
    participant LLM as Gemini API
    User->>API: POST /api/v1/ingestion-jobs
    API->>PG: Insert status=pending
    PG-->>API: job_id
    API-->>User: 202 Accepted, job_id
    loop Periodically
      WK->>PG: Atomically claim pending job
    end
    WK->>RSS: Fetch RSS/article material
    RSS-->>WK: Source content
    WK->>PG: Insert new deduplicated articles
    loop Each eligible new article
      WK->>Model: Generate Vietnamese summary
      Model-->>WK: Summary text
      WK->>LLM: Classify / keywords / review source and summary
      LLM-->>WK: Structured metadata + review
      WK->>PG: Save approved result or review status
    end
    WK->>PG: Mark job complete/failed, counts
    User->>API: GET /api/v1/ingestion-jobs/{id}
    API->>PG: Read job status
    API-->>User: Current status and counters
```

---

## 4. Two Compose services: exact responsibilities

### 4.1 Service `api`

**Runs:** `uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8000`  
**Responsibilities:** read article/search endpoints; response validation; source listing; local manual job submission without auth; job status; `/health`.  
**Does not:** run APScheduler, fetch RSS, run expensive LangGraph workflows as part of HTTP requests, or receive scheduler callbacks.

### 4.2 Service `worker`

**Runs:** `uv run --no-sync python -m app.worker` with one APScheduler 3.x `BackgroundScheduler`  
**Responsibilities:** initialize `services/summary_service.py` once at worker startup to load local ViT5 before processing jobs; one standalone APScheduler; enqueue periodic collection jobs; claim pending jobs; collect feeds; process new articles; run one LangGraph invocation per article; write status/result; bounded retries and logged failures.  
**Does not:** expose HTTP ports, serve frontend requests, or depend on API container availability.

**MVP worker behavior:** one worker replica; one processing loop at a time, separate insertion/result caps (default 20 each) and configurable collection interval of 30 minutes. Poll the jobs table every 10 seconds only when useful; idle polling is acceptable for this small workload. Avoid running overlapping ingestion cycles.

### 4.3 `compose.yaml` (Frontend, API and Worker)

```yaml
services:
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    image: vietnam-news-frontend:local
    ports:
      - "127.0.0.1:5173:80"
    depends_on:
      - api
    restart: unless-stopped

  api:
    build:
      context: .
      dockerfile: backend/Dockerfile
    image: vietnam-news-backend:local
    command: uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8000
    env_file: [.env]
    environment:
      - SUMMARIZATION_MODEL_PATH=/opt/models/vit5-base-vietnews-summarization
    ports: ["127.0.0.1:8000:8000"]
    restart: unless-stopped

  worker:
    build:
      context: .
      dockerfile: backend/Dockerfile
    image: vietnam-news-backend:local
    command: uv run --no-sync python -m app.worker
    env_file: [.env]
    environment:
      - SUMMARIZATION_MODEL_PATH=/opt/models/vit5-base-vietnews-summarization
    restart: unless-stopped
```

- `api` and `worker` use the **same backend Dockerfile/image and code**, different process entry points.
- `frontend` uses a multi-stage Dockerfile (`node:20-alpine` build + `nginx:alpine` runtime) that serves static React assets and reverse-proxies `/api/` to `http://api:8000/api/` inside the Docker network.
- Supabase is external: **no PostgreSQL container**.
- Both `127.0.0.1:5173` (frontend) and `127.0.0.1:8000` (API) are published on loopback.
- Use `docker compose config` to validate Compose and `docker compose logs -f frontend api worker` for troubleshooting.
- Run migrations separately, before relying on the services: `docker compose run --rm api uv run --no-sync alembic upgrade head`.

### 4.4 Build-time summarization model download

- Add **`download_summarization_model.py` at the repository root** when implementing this phase. The Docker build context must be the root so `backend/Dockerfile` can copy this script and the root uv dependency files.
- Install locked Python dependencies with `uv sync --locked --no-dev` before invoking `RUN uv run --no-sync python download_summarization_model.py` during the Docker build. Copy the source needed to install the existing root project before syncing, or use a dependency-only layer followed by the project sync.
- The script downloads `VietAI/vit5-base-vietnews-summarization` using `AutoTokenizer` and `AutoModelForSeq2SeqLM`, then saves both via `save_pretrained()` to `/opt/models/vit5-base-vietnews-summarization`. Include tokenizer files and model configuration, not just weights. Fail the build if the download/save fails.
- Set `SUMMARIZATION_MODEL_PATH=/opt/models/vit5-base-vietnews-summarization` in the image. Model ID/path must be available during the build through Docker `ARG`/`ENV`; Compose `env_file` supplies runtime configuration only.
- `backend/app/services/summary_service.py` loads the tokenizer and model from this path with **`local_files_only=True`**, calls `model.eval()`, and uses inference mode. Load once during process initialization, before accepting summarization work. Missing/corrupt files cause a clear startup failure; never fall back to downloading from Hugging Face at container startup.
- The worker owns inference and initializes this service at startup. FastAPI only reads saved summaries and enqueues jobs, so API server initialization does not need a second model in memory. Both containers use the image with bundled files.
- Set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` at runtime to enforce offline model loading. Gemini, RSS, and Supabase still require network access.
- Start with CPU inference for local portability; benchmark memory and latency before adding optional GPU support. Bound input tokens and generation length; use the model's documented preprocessing, with no instruction prefix. Keep long-article truncation/chunking explicit.
- Validate an actual local model load and sample generation with network access disabled. Downloads may take time during the build, and the image will be larger; Docker layer caching avoids repeating the download for unrelated code changes.

---

## 5. Persistence and database model

### 5.1 Entity-relationship diagram

Types below use **SQLAlchemy names** for the model schema. The ORM declarations are implemented; revision `0001` is implemented and reported working by the developer; the developer reports the hosted constraint tests passing. Every `DateTime` means `DateTime(timezone=True)`. `PK`, `FK`, and `UK` mean primary key, foreign key, and unique constraint.

```mermaid
erDiagram
    SOURCES ||--o{ ARTICLES : publishes
    SOURCES |o--o{ INGESTION_JOBS : optionally_scoped_to
    ARTICLES ||--o| SUMMARIES : summarized_as

    SOURCES {
      BigInteger id PK
      String name
      Text rss_url UK
      Boolean is_active
      DateTime last_fetched_at
    }
    ARTICLES {
      BigInteger id PK
      BigInteger source_id FK
      Text original_url
      Text canonical_url UK
      Text title
      Text rss_description
      Text content
      String content_origin
      String processing_status
      Text processing_error
      DateTime updated_at
      DateTime published_at
      DateTime created_at
    }
    SUMMARIES {
      BigInteger id PK
      BigInteger article_id FK,UK
      Text summary_text
      String category
      JSONB keywords
      String summarize_model_name
      String agent_model_name
      Boolean approved
      Text review_feedback
      Integer draft_attempts
      Boolean input_truncated
      DateTime updated_at
      DateTime created_at
    }
    INGESTION_JOBS {
      BigInteger id PK
      BigInteger source_id FK
      String status
      String trigger
      Integer attempts
      Integer articles_created
      Integer articles_summarized
      Integer articles_processed
      Integer articles_failed
      Integer articles_needs_review
      Text error_message
      DateTime created_at
      DateTime started_at
      DateTime finished_at
    }
```

The [database contract](todos.md#database-contract) defines field nullability, defaults, indexes and counters against the existing ORM models. Preserve these declarations. Revision `0001` creates the schema, and revision `0002` renames the summary model column to `summarize_model_name`; PostgreSQL enforcement and rename-lifecycle tests cover them.

**Database conventions:** UTC timestamps in PostgreSQL (`TIMESTAMPTZ`), serialize ISO 8601, display local Vietnam time in UI; indexed `published_at` and foreign keys; use Python StrEnum fields stored as VARCHAR with named checks; SQLAlchemy 2.x typed models; Alembic migrations. Use a single SQLAlchemy database session per small unit of work.

**Article statuses:** `pending`, `processing`, `ready`, `needs_review`, `failed` (store separately from the job lifecycle).  
**Job statuses:** `pending`, `running`, `completed`, `failed`.

**Enum implementation:** `app.models.enums` defines ProcessingStatus, ContentOrigin, Category, JobStatus and JobTrigger. Its `string_enum()` helper stores lowercase enum values using `values_callable`, `native_enum=False`, `create_constraint=True` and `validate_strings=True`. ORM reads return enum members. In ORM models, do not add duplicate manual enum checks. Revision `0001` deliberately uses VARCHAR columns and explicit named enum checks once each to avoid autogeneration duplication. Changing allowed values requires a reviewed Alembic migration. [SQLAlchemy Enum documentation](https://docs.sqlalchemy.org/en/21/core/type_basics.html#sqlalchemy.types.Enum).

**Defaults and checks:** Bigint IDs use `Identity()`. Status/boolean/counter/timestamp defaults are database-side and apply on INSERT. Article and Summary `updated_at` fields use `onupdate=func.now()` for SQLAlchemy updates; direct SQL writers must set them explicitly. Keep supplied datetimes timezone-aware and configure sessions for UTC. Explicit checks enforce nonnegative job counters, the processed-counter equality, summary draft attempts 1–2 and JSON-array keywords. The Article-ready/Summary-approved rule spans tables and belongs to atomic persistence plus read-API suppression.

**Deduplication:** derive and store normalized `canonical_url`, enforce a unique DB constraint, and use insert-on-conflict/no-op or transaction-aware handling. Normalization should remove standard tracking parameters and fragments, not blindly merge unrelated articles. Do not rely on an in-memory `set` alone.

**Schema clarification:** The `SUMMARIES.article_id` relation is one-to-one in MVP; `INGESTION_JOBS.source_id` may be `NULL` to mean “all configured sources.” `content_origin` indicates full extracted text vs RSS excerpt; readers and summary prompts should not confuse excerpts with full articles.

### 5.2 Database access rules

- Connect from **both API and worker** with SQLAlchemy (`postgresql+psycopg://...` or equivalent supported driver).
- Configure modest pool sizes and `pool_pre_ping`; keep connections short-lived; don't hold DB transactions while making HTTP/LLM requests.
- Use Supabase direct connection where reachable (typically IPv6) or the **session pooler** for a persistent backend on IPv4-only networks. Select the actual connection string from Supabase's Connect dialog; don't fabricate it. Use a migration-capable connection, preferably direct when available.
- No Supabase service-role keys or database credentials in browser code. Frontend talks **only to FastAPI**.
- Never call `Base.metadata.create_all()` in place of real Alembic migrations once schema management begins.

### 5.3 Job-claim and failure semantics

For a **single worker**, a simple transaction with an atomic claim is acceptable. Prefer a PostgreSQL statement/transaction using `SELECT ... FOR UPDATE SKIP LOCKED` and a state change to `running`. Avoid selecting a pending job then updating it in a separate unlocked transaction. Commit the claim **before** fetching articles or calling the LLM.

- At single-worker startup, fail abandoned `running` jobs and reset abandoned `processing` articles to `pending`, preserving committed counters and ready summaries. Recovery assumes the previous worker has stopped; a hung process requires restart. Do not reclaim active inference on an arbitrary timeout.
- Retry transient source/network/LLM errors with a small retry budget and backoff; record failure and error detail if exhausted.
- Do not re-summarize already successful articles unless explicitly requested.
- Never rely on exactly-once execution: make ingestion and persistence idempotent, including unique `article_id` on summaries.
- Only one worker replica is supported throughout this MVP.

---

## 6. News ingestion (ordinary deterministic Python)

**Keep collection outside LangGraph.** Fetching RSS, parsing, deduplication, and safe persistence are deterministic application logic, not tools chosen by an LLM.

1. Select enabled sources from `sources`.
2. Fetch RSS with a clear user agent, timeout, bounded retries, and modest request rate.
3. Parse entries and collect title, canonical URL, publish date, RSS description, source ID, and optional image if legitimately supplied.
4. Normalize URLs and skip existing canonical URLs using DB uniqueness.
5. Optionally fetch and extract article text from permitted public pages; do not bypass access controls, paywalls, robots restrictions, or terms of use.
6. Label whether content is complete or excerpt-only. If no adequate text is available, mark as not processable/needs review instead of inventing a summary.
7. Save article as `pending`; invoke LangGraph on eligible new or resumed pending articles. Skip ready, rejected and failed results unless explicitly reprocessed later.
8. Persist approved summary or flag `needs_review`/`failed`; record processing counters and errors.

**Source policy:** begin with three verified Vietnamese publisher RSS feeds, such as feeds *offered* by VnExpress, Tuổi Trẻ, or Thanh Niên **after checking current availability and reuse rules**. Provide attribution and links; do not mirror full articles by default or republish copyrighted text indiscriminately.

**Volume/cost control:** `JOB_MAX_ARTICLE_INSERTIONS=20` and `JOB_MAX_ARTICLE_RESULTS=20`; consume pending backlog before new processing. Bound text/tokens, HTTP retries and job backlog. Use deterministic RSS fixtures for tests.

### 6.1 Phase 3: RSS collection and usable text (Days 3–4)

RSS is a publisher-provided XML feed of recent entries: titles, original links,
optional publication dates and descriptions. A description is often only an
excerpt. Phase 3 discovers articles, stores them without duplicates, and prepares
source text with provenance and a preliminary quality decision. AI generation and
review belong to later phases.

```mermaid
flowchart LR
    Config[Validate source configuration] --> Feed[Fetch and parse RSS]
    Feed --> Insert[Normalize URLs and insert new articles]
    Insert --> Pending[Read oldest unprepared pending rows]
    Pending --> Text[Permitted HTML extraction or RSS fallback]
    Text --> Quality{At least 200 characters?}
    Quality -->|Yes| ReadyForProcessing[Save text; remain pending]
    Quality -->|No| Review[Save available text; needs_review]
```

| Step | Code entry point | Behavior |
| --- | --- | --- |
| Configure and seed | [`seed_sources.py`](../backend/app/seed_sources.py): `SourceConfig`, `ArticleExtractionPolicy`, `load_source_config()`, `seed_sources()` | Pydantic validates `config/sources.json` before DB access. `SourceConfig` holds feed/review settings; its optional extraction policy holds public path prefixes, a CSS content selector and a review note. Seed only `name`, `rss_url`, `is_active`; upsert by RSS URL. Other policy fields stay in JSON. |
| Fetch and parse | [`rss_collector.py`](../backend/app/services/rss_collector.py): `RSSCollector.collect()` → `fetch()` → `parse_feed()` | Return `FeedEntry` dataclasses. Clean title/description HTML; skip missing titles and invalid/unreviewed links. Convert known dates to UTC, otherwise NULL. Reject malformed feeds; a valid empty feed succeeds. |
| Establish identity | [`url_normalization.py`](../backend/app/services/url_normalization.py): `normalize_url()` | Lowercase scheme/host; remove default ports, fragments and known tracking parameters. Preserve path differences and identifying query parameters. Store both original and canonical URLs. |
| Insert metadata | [`ingestion.py`](../backend/app/services/ingestion.py): `ingest_entries()` → `insert_article()` | PostgreSQL canonical-URL uniqueness plus `ON CONFLICT DO NOTHING RETURNING id` makes duplicates no-ops, including concurrent inserts. Duplicates consume no insertion capacity and never overwrite existing articles. |
| Prepare text | `prepare_pending_articles()` → [`ArticleExtractor.extract()`](../backend/app/services/article_extractor.py) | Select oldest source rows with status `pending`, NULL content and NULL origin. Attempt enabled public-HTML extraction; fall back to permitted RSS descriptions when disabled, unavailable or inadequate. Remove markup/noise and retain at most 20,000 characters. |
| Persist quality | `prepare_pending_articles()` | Save `ExtractionResult.text`, origin, status and redacted reason together. At least 200 cleaned characters stays `pending`; short/missing text becomes `needs_review`. Origin is `extracted` or `rss_excerpt`, and NULL when text is absent. |

**HTTP and access rules.** Requests use an identifying user agent, a 15-second
HTTP timeout and a one-second request delay. Each feed, robots or article fetch
has at most three requests shared between redirects and retries, with bounded
backoff. Validate HTTPS/exact hosts before following redirects. Cap decoded feed
and HTML bodies at 2 MiB; robots at 256 KiB. Enabled article extraction additionally
checks public paths and current robots rules for the application user agent.
Robots rules describe crawler access; reuse and AI processing require separate
review. The RSS collector uses recorded robots-review evidence in configuration.

**Transactions and recovery.** Feed fetching finishes before the insertion
transaction. Text preparation closes its snapshot transaction before publisher
IO, then commits each result separately. Before saving, recheck source activation
and RSS identity; a conditional update requires the article still be pending,
unprepared, and have the same URL/description. Concurrently changed rows are
skipped. Committed preparation survives interruption; subsequent runs resume old
unprepared rows even if absent from today's feed. Already prepared and non-pending
rows are preserved. Insertion and preparation have separate default limits of 20,
so newly inserted rows may wait behind older backlog.

**Current boundary and verification.** The committed configuration activates
VnExpress (`article.fck_detail`) and Tuổi Trẻ (`div.detail-content`) with both
full-text article extraction and AI processing enabled (`article_extraction_allowed=true`,
`ai_processing_allowed=true`), while leaving Thanh Niên inactive. When the worker runs,
`recover_review_articles()` retries older excerpt-only `needs_review` rows (`extraction_disabled; ...`),
extracts full text, and returns them to `pending` for AI summarization. All generated summaries
are automatically marked `approved=true` and `ready` upon persistence so the reader UI
displays summarized articles without manual review.
Fixed HTTP fixtures and isolated PostgreSQL tests cover retries, redirects,
deduplication races, provenance, transaction boundaries and resumable writes.
See [Phase 3 acceptance](todos.md#phase-3--days-34-rss-and-usable-text) and
[source evidence](source-evidence.md) for remaining policy gates.

```sh
uv run --locked --env-file .env python -m app.seed_sources
uv run --locked --env-file .env python -m app.services.ingestion --source-id 1 --verify-repeat
uv run --locked --env-file .env python -m app.services.ingestion --source-id 1 --prepare-only
```

`--verify-repeat` replays only the attempted feed slice and requires zero new
insertions. `--prepare-only` skips feed collection and resumes stored text work;
after draining the backlog, repeating it prepares zero rows. Both commands report
IDs/counters; extraction logs include source/article/job IDs and fixed failure
classes without raw payloads or credentials.

---

## 7. LangGraph AI workflow (MVP)

### 7.1 Fixed graph with bounded validation loop

```mermaid
flowchart TD
    START((START)) --> Draft[Draft node: local ViT5 summary + Gemini metadata]
    Draft --> Review[Gemini review: compare summary to source]
    Review --> Gate{Approved?}
    Gate -->|Yes| Accepted((END: approved))
    Gate -->|No and attempts < 2| Draft
    Gate -->|No, retries exhausted| Manual((END: needs_review))
```

- One **graph invocation per article**; collection is outside the graph.
- The graph uses deterministic orchestration: ViT5 generates summary text locally; Gemini returns category/keywords and reviews the result. Gemini does not replace ViT5 as the summarization model.
- On a rejected draft, retry ViT5 with a bounded alternate generation strategy and recompute/review metadata. ViT5 is not a chat model: do not append Gemini feedback as instructions to the source. After the graph finishes (up to two draft attempts), `persist_summary()` auto-completes the summary (`approved=True`, `processing_status=ready`) while retaining Gemini's feedback for diagnostics.
- The review node is **not proof of factual correctness**. Never market it as independently verified news.
- Max **two draft attempts total**, not an unbounded loop; handle structured-output validation errors and provider failures at the worker boundary.
- Persist results from the worker *after* the graph returns, rather than allowing arbitrary LLM-initiated DB writes.

### 7.2 State contract

```python
from typing import TypedDict

class NewsState(TypedDict, total=False):
    article_id: int
    title: str
    source_text: str
    content_origin: str       # extracted or rss_excerpt
    inference_text: str       # exact text retained after tokenizer truncation
    input_truncated: bool
    category: str
    summary: str
    keywords: list[str]
    approved: bool
    feedback: str
    attempts: int            # starts at 0; total drafts, hard ceiling 2
    outcome: str             # approved or needs_review
```

### 7.3 Output contracts

```python
from pydantic import BaseModel, Field, StrictBool
from app.models.enums import Category

class ArticleMetadata(BaseModel):  # Gemini structured output
    category: Category
    keywords: list[str] = Field(min_length=3, max_length=5)

class NewsDraft(ArticleMetadata):  # assembled by application code
    summary: str = Field(description="Concise Vietnamese summary generated by local ViT5")

class ReviewResult(BaseModel):
    approved: StrictBool
    feedback: str = Field(max_length=1000)
```

**Draft requirements:** ViT5 generates concise Vietnamese text from the available source; configure bounded generation rather than expecting chat-style instruction following. Gemini supplies structured metadata. Review rejects invented names/dates/quotes/numbers. Record and display excerpt-only provenance; treat article text as **untrusted input** rather than instructions in Gemini prompts.

**Review requirements:** Compare summary with original available text; reject unsupported facts or critical misstatements; give actionable feedback; use only the supplied source, not unverifiable outside claims.

**Routing:** `approved=True → END`; `approved=False && attempts < 2 → draft`; otherwise `END` with `needs_review`. Use LangGraph `StateGraph`, `START`, `END`, and conditional edges with explicit mapping.

**Model configuration:** Load local ViT5 from `SUMMARIZATION_MODEL_*`. Store ViT5 and Gemini model IDs separately in summaries. Graph tests inject fake adapters; actual inference/provider tests remain separate.

**Gemini integration:** Follow the user's [getting-started guide](https://ai.google.dev/gemini-api/docs/get-started): official `google-genai`, `GEMINI_API_KEY`, and `client.interactions.create`. `services/gemini_service.py` owns the client and typed metadata/review operations; ordinary Python LangGraph nodes call it. Keep `GEMINI_MODEL` configurable and verify account access instead of copying the guide's example model ID.

Each call supplies `input` and `response_format={type: "text", mime_type: "application/json", schema: <Pydantic JSON schema>}`. Parse `interaction.output_text` with `model_validate_json`; require completed status and nonempty valid output. Local validation additionally enforces 3–5 distinct keywords and a rejection reason. [Structured-output reference](https://ai.google.dev/gemini-api/docs/structured-output).

Use independent calls with `store=False`; no conversation chaining, streaming or provider-managed background jobs. PostgreSQL retains application state. [Interactions reference](https://ai.google.dev/gemini-api/docs/interactions-overview). Specify Developer API mode, finite timeouts and at most three wire attempts per operation. The installed SDK's Interactions retry conversion needs a transport test: its `attempts` setting counts retries, so do not assume a value of 3 means three requests. Do not add worker-level retries around those calls.

### 7.4 Optional read-only tools

In this project a **Python service function** is not automatically an **LLM tool**. Do not wrap every deterministic function in `@tool`.

| Operation | Called by | Expose as agent tool? |
|---|---|---|
| `fetch_rss_feed` | Worker ingestion code | **No** |
| `extract_article_text` | Worker ingestion code | **No** |
| `normalize_url`, `is_duplicate` | Worker ingestion code | **No** |
| `save_article`, `save_summary` | Worker SQLAlchemy service | **No**, no agent DB writes |
| `get_source_article(article_id)` | Optional verification agent | **Yes**, read-only |
| `search_related_articles(keyword)` | Optional verification agent | **Yes**, read-only, tightly limited |

**Optional upgrade:** After the base graph works, add bounded function calling to the SDK review adapter, or evaluate LangChain `create_agent` with the existing `langchain-google-genai` dependency. Verify its API separately; the MVP uses the official SDK. Keep the outer retry loop deterministic.

Optional-agent safeguards: allowlist database access via application functions, bounded returned text, bounded tool calls and runtime, `LIMIT 5` on search, no arbitrary network requests, no `UPDATE`/`DELETE`/`INSERT` tools, and no trusting instructions embedded inside article text.

**Do not spend the first week on tool-calling.** The fixed graph is the core MVP; tool use is a learning enhancement, not a required ingestion dependency.

---

## 8. FastAPI API contract

Article pagination is `{items, total, page, page_size}`. The [REST contract](todos.md#rest-contract) defines fields, validation, ordering, error responses and summary suppression.

| Method | Route | Access | Purpose |
|---|---|---|---|
| `GET` | `/health` | Local, no auth | Lightweight application health check |
| `GET` | `/api/v1/articles` | Local, no auth | Paginated articles; optional `q`, `category`, `source_id`; validated page/page_size |
| `GET` | `/api/v1/articles/{article_id}` | Local, no auth | Article detail, source link, summary/status |
| `GET` | `/api/v1/sources` | Local, no auth | Enabled news source list |
| `POST` | `/api/v1/ingestion-jobs` | Local, no auth | Create pending job, return `202` with job ID |
| `GET` | `/api/v1/ingestion-jobs/{job_id}` | Local, no auth | Status, counts, timestamps, error details |

Example manual job request/response:

```http
POST /api/v1/ingestion-jobs
Content-Type: application/json

{"source_id": null}
```

```http
HTTP/1.1 202 Accepted
Content-Type: application/json

{"job_id": 42, "status": "pending"}
```

**Local-only access:** Bind published API and frontend ports to loopback, cap queued jobs and avoid overlapping ingestion. Public/shared deployment requires revisiting access controls.

**Search:** For initial MVP, case-insensitive SQL filtering (`ILIKE`) plus indexed filter/order columns is enough at this scale; advanced full-text search is optional, not necessary for this deadline.

---

## 9. React pages and UI states

**Recommended frontend routes:**

- `/` — news feed: search bar, filters, paginated latest cards.
- `/articles/:id` — article detail, Vietnamese summary, keywords, source attribution and “Read original” link.
- Optional `/ingestion` — local manual trigger and job status display, with no authentication.

Each item shows title, source, local publish time, category, summary preview (when `ready`), and link to original. A `pending` or `needs_review` article should not show an invented summary. Include loading/error/empty states; make interface usable on mobile.

**API access in development:** Vite dev proxy `/api` to `http://localhost:8000`. Use relative `/api` URLs under the local Vite origin; no direct Supabase browser connection.

---

## 10. Local execution design

- Python setup: `uv sync --locked`; use `uv run` for Python commands, migrations, pytest, and Ruff. Add dependencies through `uv add` and commit both root `pyproject.toml` and `uv.lock`.
- Terminal 1: `docker compose up --build` for backend API + worker. The image build runs `download_summarization_model.py`; container startup loads the saved model locally.
- Terminal 2: `cd frontend && npm install && npm run dev -- --host 127.0.0.1` for host Vite, proxying `/api` to the loopback API.
- Supabase PostgreSQL remains hosted; Gemini is an external API. Local-only refers to application access, not a fully offline system.
- For running Python outside Docker, first use `uv run python download_summarization_model.py` with `SUMMARIZATION_MODEL_PATH` set to a writable local directory, then reuse that path at runtime. Keep Hugging Face offline flags unset (or `0`) during this explicit download; enable them for runtime loading. Do not commit downloaded model files.
- Nginx, domains, public hosting, TLS, and authentication/authorization are future work, outside this MVP.

**No CI/CD system in this MVP:** run pytest, linting, frontend build checks and container checks manually or through a documented local `make check`/shell script. Do not introduce Jenkins or GitHub Actions without request.

---

## 11. Proposed monorepo structure

```text
vietnamese-news-summarization/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI entrypoint
│   │   ├── worker.py               # APScheduler/worker entrypoint
│   │   ├── core/
│   │   │   └── config.py           # env/configuration
│   │   ├── api/
│   │   │   ├── articles.py
│   │   │   ├── sources.py
│   │   │   └── ingestion_jobs.py
│   │   ├── db/
│   │   │   └── session.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── base.py             # single declarative Base
│   │   │   ├── enums.py            # StrEnum definitions / VARCHAR checks
│   │   │   ├── article.py
│   │   │   ├── source.py
│   │   │   ├── summary.py
│   │   │   └── ingestion_job.py
│   │   ├── schemas.py             # Pydantic REST contracts
│   │   ├── services/
│   │   │   ├── rss_collector.py
│   │   │   ├── article_extractor.py
│   │   │   ├── ingestion.py
│   │   │   ├── job_service.py
│   │   │   ├── gemini_service.py  # official SDK + JSON validation
│   │   │   └── summary_service.py          # loads bundled ViT5 once; local inference
│   │   └── agents/
│   │       ├── state.py
│   │       ├── graph.py
│   │       ├── nodes.py
│   │       ├── schemas.py
│   │       ├── prompts.py
│   │       └── tools.py            # optional read-only tools
│   ├── alembic/                  # migration environment/revisions
│   ├── alembic.ini               # backend migration/logging configuration
│   └── Dockerfile
├── config/sources.json           # reviewed source/access-policy evidence
├── tests/                       # root unit/integration/model/live tests
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── services/api.ts
│   │   └── App.tsx
│   ├── package.json
│   └── package-lock.json          # or an equivalent chosen lockfile
├── download_summarization_model.py # build-time model/tokenizer download
├── pyproject.toml                 # existing root uv project
├── uv.lock                        # committed dependency lockfile
├── compose.yaml
├── .env.example
├── .gitignore
├── README.md
└── docs/
    └── architecture.md
```

Retain the existing `backend/app` package and root uv configuration (`module-name="app"`, `module-root="backend"`). Root tests already exist. Add modules as needed rather than creating empty files.

Avoid premature abstraction: consolidate neighboring modules if they end up being one tiny function. The structure is a guide, not a requirement to produce empty files.

---

## 12. Environment and configuration

`.env.example` (placeholders only, **no real secrets**):

```dotenv
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME
GEMINI_API_KEY=REPLACE_ME
GEMINI_MODEL=REPLACE_WITH_A_SUPPORTED_GEMINI_MODEL
SUMMARIZATION_MODEL_ID=VietAI/vit5-base-vietnews-summarization
SUMMARIZATION_MODEL_PATH=/opt/models/vit5-base-vietnews-summarization
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
COLLECTION_INTERVAL_MINUTES=30
WORKER_POLL_INTERVAL_SECONDS=10
JOB_MAX_ARTICLE_INSERTIONS=20
JOB_MAX_ARTICLE_RESULTS=20
MAX_JOB_BACKLOG=5
MAX_GRAPH_DRAFT_ATTEMPTS=2
LOG_LEVEL=INFO
```

Actual connection strings/keys come from the user's Supabase and Gemini accounts; never commit `.env`. Also prepare a `.dockerignore` so secrets, local virtual environments, caches and `node_modules` aren't included in image builds. Error logs should not leak secrets or raw sensitive payloads.

---

## 13. Implementation order

The [14-day implementation checklist](todos.md) assigns files, dependencies, tests and daily acceptance checks. Health/settings/models, sessions, migrations, read APIs, source configuration, D3 collection/deduplication and D4 text preparation are implemented. Fixed feed/fictional HTML tests cover parsing, permitted extraction, fallback and HTTP boundaries. Isolated PostgreSQL tests cover repeat/concurrent inserts, provenance, resumable preparation and status guards with no publisher IO inside transactions. Current live sources use permitted RSS excerpts; publisher article extraction and AI remain disabled. See the [Day 4 guide](day-4-extraction.md). Day 5 adds verified offline CPU ViT5 generation, Gemini metadata and the typed draft node using fictional source text; see the [Day 5 guide](day-5-model.md). Day 6 adds the bounded source-review graph, explicit single-article processing and atomic candidate/status persistence with replay and REST-visibility coverage; see the [Day 6 guide](day-6-review.md). Day 7 adds durable job submission/polling, atomic claims/counters, startup recovery and standalone scheduling, including a live job completed while the API was stopped; see the [Day 7 guide](day-7-worker.md).

1. **First slice:** migrated PostgreSQL → one clearly labeled fixture source/article → source/list/detail read APIs.
2. **Ingestion:** reviewed feeds → extraction/provenance → idempotent article persistence.
3. **AI:** saved article → local ViT5 → Gemini metadata/review → atomic summary persistence → read API.
4. **Jobs:** local POST → durable pending job → worker → result counters; then add the scheduler.
5. **Reader and packaging:** React → API → saved results; shared model image, two Compose services and host Vite.

The next coding milestone is Day 8: frontend setup and the reader UI. Read routes, Day 6 review/persistence and Day 7 jobs/worker/scheduling are implemented. Optional ingestion UI and tool-calling review follow core acceptance.

---

## 14. Verification and acceptance

The [testing matrix](todos.md#testing-matrix) separates fixture/fake tests, real PostgreSQL integration, actual local model tests and opt-in live publisher/Gemini checks. The [acceptance checks](todos.md#exact-acceptance-checks) specify commands and expected results; unchecked or skipped live checks do not establish completion.

Required gates: migrated schema and enforced uniqueness; three dated permitted feeds; repeat ingestion without duplicates; real ViT5/Gemini output; at most two drafts and hidden rejected summaries; durable manual/scheduled jobs and restart recovery; correct REST/UI behavior; exactly two loopback backend services; successful network-disabled model generation and deliberate missing-model failure; locked setup and reproducible README.

---

## 15. Risks, mitigations and conscious trade-offs

| Risk | Mitigation |
|---|---|
| 14 days is short for an unfamiliar stack | Implement vertical slices; postpone optional agents, UI polish and infrastructure |
| Publisher feed changes/unavailable | Verify URLs; keep source adapters simple; use fixtures in tests |
| Access/copyright restrictions | Link and attribute sources; don't bypass paywalls or indiscriminately republish full text |
| LLM hallucinations | Source-only prompts, review gate, bounded attempts, visible AI-generated label |
| RSS excerpt too short | Store `content_origin`; refrain from overstating summary certainty; skip unusable texts |
| LLM cost/rate limits | Batch cap, truncate large inputs, configure timeouts/retries and per-job limits |
| Duplicate jobs or articles | DB unique constraints, atomic claim, idempotent writes, one worker |
| Worker crash mid-job | Fail abandoned jobs and reset processing articles at single-worker startup; preserve committed results; no automatic job retry |
| Supabase connection issues | Use correct direct/session-pooler endpoint; small SQLAlchemy pool; `pool_pre_ping` |
| Unauthenticated local endpoints | Keep API and Vite on loopback for one user; defer public/shared access |
| Model download timeout / large image | Download at build time, cache layer, fail build on errors |
| CPU inference latency / RAM usage | One preloaded worker model, bounded tokens/batches, benchmark local hardware |
| Scope creep | Explicit out-of-scope list; require approval to add technology |

**Learning trade-offs:** PostgreSQL is used as a small job coordination mechanism because we purposely removed Redis/queue infrastructure. This is acceptable for the specified low-volume, single-worker MVP; it isn't an unbounded high-throughput queue. Gemini review of ViT5 output is a quality-control heuristic, not independent journalistic fact-checking.

---

## 16. Official documentation to consult when implementing

- ViT5 model card and preprocessing: https://huggingface.co/VietAI/vit5-base-vietnews-summarization
- Transformers offline/local loading: https://huggingface.co/docs/transformers/installation#offline-mode
- Gemini getting started (primary integration guide): https://ai.google.dev/gemini-api/docs/get-started
- Gemini Interactions API: https://ai.google.dev/gemini-api/docs/interactions-overview
- Gemini structured outputs: https://ai.google.dev/gemini-api/docs/structured-output
- uv Docker integration: https://docs.astral.sh/uv/guides/integration/docker/
- LangGraph `StateGraph`: https://reference.langchain.com/python/langgraph/graph/state/StateGraph
- LangGraph conditional edges: https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges
- LangChain `create_agent` (optional tool reviewer): https://reference.langchain.com/python/langchain/agents/factory/create_agent
- APScheduler 3.x `BackgroundScheduler`: https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/background.html
- APScheduler 3.x `add_job` options: https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/base.html
- Supabase connection guidance: https://supabase.com/docs/guides/database/connecting-to-postgres
- uv CPU PyTorch configuration: https://docs.astral.sh/uv/guides/integration/pytorch/

Use these as **reference starting points**, not a substitute for checking current package versions and APIs in the actual project environment.

