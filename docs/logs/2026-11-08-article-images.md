# Article images

Article images are optional publisher metadata, independent of AI approval. The API returns `image_url` on both article lists and details. The frontend renders that URL in featured stories, cards, and the reader, retaining a neutral placeholder if it is absent or fails to load.

## Collection

The RSS collector captures Media RSS thumbnails/image content, image enclosures, and images in description HTML **before** converting the description to plain text. Images may be hosted on a publisher CDN rather than its article hostname. Only public HTTPS URLs without credentials or unusual ports are retained; image files are not downloaded by the backend.

When full-text extraction is already permitted, the existing HTML response also supplies `og:image`, Twitter image metadata, or an image inside the reviewed article container. Existing RSS images take precedence. Image collection does not enable full-text extraction or AI processing for disabled sources.

Migration `0003` adds nullable `articles.image_url`; existing articles initially retain `NULL`. Use the normal migration workflow:

```sh
uv run --locked alembic upgrade head
```

## Existing articles

From the repository root:

```sh
# Inspect current RSS metadata without saving anything.
uv run --locked python -m app.backfill_article_images

# Older articles may no longer appear in today's feeds. Read their public page
# metadata with the existing host, robots, request-delay and response-size limits.
uv run --locked python -m app.backfill_article_images --from-pages

# Save only missing image URLs on existing articles.
uv run --locked python -m app.backfill_article_images --from-pages --apply
```

The default batch limit is 100 (`--limit` supports 1–1000). The operation is repeatable: it only fills `NULL` image URLs and never inserts articles, overwrites existing images, generates summaries, or changes review decisions. Publisher requests happen outside database transactions. Source activity and article identity are checked again before each save. Unavailable or robots-blocked metadata leaves the image missing.

The browser loads images directly from their supplied hosts with `referrerPolicy="no-referrer"`. Publishers may remove images or block embedding; these cases use the same placeholder.

## Validation of this change

- Migration `0003` applied to the configured Supabase development database.
- Backfilled all 41 existing articles; a repeat run examined/saved zero rows.
- Before/after hashes matched for stored article content, publication metadata, processing statuses/errors, and summary text/approval/feedback/category.
- Backend unit suite: 273 passed, four opt-in model/live checks skipped (FastAPI TestClient requires local socket access).
- PostgreSQL tests: 63 passed across migration lifecycle, image persistence, API, ingestion, and existing persistence constraints, all using disposable fixture schemas.
- Frontend lint and production build passed.
- Playwright at 1440×900 and 1024×768: all 41 images loaded; no horizontal overflow; source links, search/category filtering, empty reset, and deliberately failed-image fallback passed. Normal page loads had no browser warnings or errors.
- Ruff passed for changed Python files with `EXE002` excluded (this filesystem reports files as executable); formatting checks passed. The full-repository check also reports existing issues in unrelated files.
