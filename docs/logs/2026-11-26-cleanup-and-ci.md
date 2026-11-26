# Codebase cleanup, structured logs and CI

**Date** 2026-11-26 · **Branch** `chore/cleanup-and-ci` · [Backend](../specs/backend.md) · [Ingestion](../specs/ingestion.md) · [Testing](../specs/testing.md)

## Goal

Establish consistent local and CI checks and make API, worker and CLI logs safe to inspect.

## What changed

- Moved source policy and validation to `app.core.source_config` and maintenance commands to `app.cli`.
- Removed the unused Gemini wrapper and refreshed the locked Soup Sieve version to replace a yanked release.
- Configured Ruff and applied the baseline fixes. Added GitHub Actions backend and frontend jobs and a README badge.
- Added one-line JSON logging with configured severity, fixed events and numeric job, source, article and timing fields. Worker events distinguish feed transport failures from parse failures. Logs omit raw messages, arguments and tracebacks.

## Verification

- Locked Ruff check and format passed. The locked CI pytest selection passed with 275 tests. The broader non-integration selection passed before the two added logging tests, with four opt-in checks skipped.
- Frontend lockfile install, lint and build passed. npm reported an existing ESLint deprecation and dependency audit findings during installation.
- Verified the former manual-review module and active documentation section are absent.

- Hosted GitHub Actions passed both jobs. [Workflow run](https://github.com/youngazier/vietnamese-news-summarization/actions/runs/45781105293).
