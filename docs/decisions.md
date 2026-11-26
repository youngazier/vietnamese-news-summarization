# Decisions

Short record of key design decisions. Details live in the linked [specs](architecture.md#specs). Dates are when the decision was recorded in docs or git; earlier ones come from the original plan (see [archived architecture](archived/architecture-long-2026-11-25.md)).

| Date | Decision | Why | Alternatives rejected |
| --- | --- | --- | --- |
| 2026-10-12 | Use a PostgreSQL `ingestion_jobs` table as the job queue; worker claims with `FOR UPDATE SKIP LOCKED` | Low volume, one worker; reuses the existing database; durable and easy to inspect | Redis, Celery, RabbitMQ, Kafka |
| 2026-10-12 | Run exactly one worker replica (scheduler + inference in one process) | One model in memory (~1.3 GiB), no duplicate scheduled jobs, simple recovery | Multiple workers; scheduler inside the API |
| 2026-10-12 | Summaries come from local ViT5; Gemini only does category/keywords and review | Vietnamese news model runs offline on CPU at no per-call cost; Gemini adds metadata and a quality check | Gemini-written summaries; fine-tuning a model |
| 2026-10-15 | Call Gemini through the official `google-genai` SDK (Interactions API, `store=False`) | Official, direct API with schema-validated output; fewer layers to debug | `langchain-google-genai` wrapper |
| 2026-11-07 | Auto-approve every completed summary (`approved=True`, status `ready`) | Personal daily reader: show every completed summary without a manual step; the manual-review feature was removed on 2026-11-08 (see [logs/2026-11-07-auto-approve-summaries.md](logs/2026-11-07-auto-approve-summaries.md)). | Manual approval UI; showing only Gemini-approved drafts |
| 2026-11-08 | Bake the ViT5 model into the backend Docker image; runtime is offline | Reproducible builds, no runtime downloads, fast startup | Downloading at container start; mounting a host model folder |
| 2026-10-12 | No authentication; all ports bind to `127.0.0.1` | Single local user, no shared access | Auth/accounts; public hosting |
| 2026-10-14 | Keep Thanh Niên inactive | Its footer forbids copying without written consent; reuse terms unresolved | Activating it based on feed availability alone |
| 2026-11-26 | Run locked backend and frontend checks on pushes and pull requests | Catch regressions before merging. Run integration, model and live checks separately because they require PostgreSQL, local weights or provider access | Manual quality checks alone |
| 2026-11-26 | Publish only graph-approved summaries and keep rejected drafts in `needs_review` | Preserve rejection evidence while filtering rejected articles from the reader and counting them as needs review. Drop the unused `human_review_*` columns in P2.2 | Automatic approval of every completed draft |
| 2026-11-26 | Gate inference on extracted full text and preserve raw publisher metadata in JSONB | Preserve provenance and repeated tags for later category mapping while rejecting excerpt-only and media inputs deterministically | Character-only gate; a separate publisher request for metadata |

See [source evidence](specs/source-evidence.md), [summarization](specs/summarization.md), [backend](specs/backend.md) and [deployment](specs/deployment.md) for the current behavior.
