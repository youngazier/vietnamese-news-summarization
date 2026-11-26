# MVP container and crash-recovery verification

**Date** 2026-11-26 · **Branch** `chore/mvp-runtime-verification` · [Deployment](../specs/deployment.md) · [Backend](../specs/backend.md)

## Goal

Rehearse the README’s Compose setup, measure ViT5 on CPU and verify that the API and worker can operate independently through a crash and a real schedule tick.

## What changed

- The backend image uses the published uv 0.12.15 Python 3.12 Trixie tag and includes the reviewed source configuration needed at worker startup. The frontend build uses Node 22 to match the locked dependencies.
- The worker integration test injects an HTTPX read timeout and malformed XML for one source and checks that the other source’s feed still completes.
- Runtime checks used the combined Priority 0 checkout so the image included structured logs and the publication gate.

## Verification

- `docker compose config --services` listed API, frontend and worker. Both images built and the configured Compose database reported Alembic revision `0004 (head)`.
- The `docker run --network none` smoke generated 20 tokens from a 179-token Vietnamese fixture. One CPU sample took 1.65 s for inference and 7.36 s for load plus inference, with peak RSS of 1,300 MiB. With `SUMMARIZATION_MODEL_PATH=/missing`, the command exited 1 in 0.44 s. The missing-file probe also blocked socket operations and verified that PyTorch, Transformers and Hugging Face Hub were never imported.
- Importing the API inside the backend image loaded neither the worker nor the model modules. The running API mapped no PyTorch libraries. The worker Python process reported about 1,349 MiB resident after startup. The API’s Docker memory snapshot was about 70 MiB.
- Playwright rendered the reader and opened a real article detail through Nginx at 1,366 px and 390 px with no same-origin errors. At 390 px the existing 1,024 px minimum document width caused horizontal scrolling. Mobile layout remains tracked in P4.3.
- The timeout and malformed RSS simulations passed against PostgreSQL in disposable schemas. The timeout reached the three-request cap and the malformed feed stopped after one request. In both cases the healthy source updated its fetch timestamp and the job completed with partial-failure detail.
- Runtime versions were Docker Engine 29.10.1, Compose v5.8.0, Python 3.12.14, uv 0.12.15, Node 22 in the frontend build and Nginx 1.31.10. CPU measurements used an Intel Core i5-10300H.

## Live jobs

- The Compose API accepted a manual job with 202. A SIGKILL during a committed article claim left the running job abandoned. On restart the worker marked it failed, reset the article to pending and loaded ViT5 once. The replacement job processed the same article and recorded a failed result.
- The worker’s JSON logs contained event names and numeric identifiers. The redaction check looked for publisher URLs, credential patterns and query tokens. The unit test also supplied a raw article payload and verified that the formatter discarded it.
- The two standalone live Gemini tests failed. A separate authored-fixture request from the worker container returned HTTP 503 with `Retry-After: 30`. This prevented verifying successful live Gemini metadata and review.
- The replacement job recorded five processed articles, all failed, with zero summarized or pending-review results. Its counter stopped advancing while the provider returned 503. Both worker startups logged exactly one model load each.
- With the API stopped, the worker enqueued a scheduled job 1,800.43 s after startup. The scheduled job stayed pending with no start timestamp while the replacement job was running. This verified the real schedule tick, API independence for enqueueing and no overlapping claims at the tick. Scheduled completion remains open.
- A second worker-container probe after the tick still returned HTTP 503. All three CLI entrypoints displayed their help from the packaged image with networking disabled.

## Follow-ups

- Re-run the live manual and scheduled jobs when Gemini is reachable. The Compose completion and full restart/scheduling checklist items remain open. The interrupted manual job will go through normal recovery on the next worker startup, and the scheduled job remains queued.
