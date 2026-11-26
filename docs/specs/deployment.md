# Deployment spec (Docker and local runtime)

← Back to [architecture](../architecture.md)

Local-only, single user. Supabase and Gemini are external; there is no database container.

## Compose services

| Service | Image | Command | Ports |
| --- | --- | --- | --- |
| `frontend` | `vietnam-news-frontend:local` (Node 22 build → `nginx:alpine`) | Nginx serves the SPA and proxies `/api/` to `api:8000` | `127.0.0.1:5173:80` |
| `api` | `vietnam-news-backend:local` | `uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8000` | `127.0.0.1:8000:8000` |
| `worker` | `vietnam-news-backend:local` (same image) | `uv run --no-sync python -m app.worker` | none |

- `api` and `worker` share a Python 3.12 Debian Trixie image. The worker reads `/app/config/sources.json`, which is copied into the image.
- All published ports bind to loopback. `env_file: .env` supplies runtime config.
- See [compose.yaml](../../compose.yaml), [backend/Dockerfile](../../backend/Dockerfile), [frontend/Dockerfile](../../frontend/Dockerfile), [frontend/nginx.conf](../../frontend/nginx.conf).

## Model baked into the backend image

- Build context is the repo root. The Dockerfile installs locked deps (`uv sync --locked --no-dev`), then runs `download_summarization_model.py` with offline flags off to save tokenizer + model + manifest to `/opt/models/vit5-base-vietnews-summarization`.
- Build fails if the download or validation fails.
- Runtime sets `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`; the model loads only from local files.
- Docker layer caching avoids re-downloading for code-only changes.

## Commands

```sh
docker compose config --services
docker compose build
docker compose run --rm api uv run --no-sync alembic upgrade head   # migrations first
docker compose up -d
docker compose logs -f frontend api worker

# Offline model check and deliberate missing-model failure:
docker run --rm --network none --entrypoint uv vietnam-news-backend:local \
  run --no-sync python -m app.services.summary_service --smoke-test
docker run --rm --network none -e SUMMARIZATION_MODEL_PATH=/missing --entrypoint uv \
  vietnam-news-backend:local run --no-sync python -m app.services.summary_service --smoke-test
```

## Running without Docker

```sh
uv sync --locked --python 3.12
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked --env-file .env python -m app.worker
cd frontend && npm run dev -- --host 127.0.0.1
```

First download the model to a local path (offline flags off for this step only):

```sh
export SUMMARIZATION_MODEL_PATH="$PWD/.models/vit5-base-vietnews-summarization"
HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 uv run --locked --env-file .env python download_summarization_model.py
```

Never commit model files. GitHub Actions runs code quality checks. Build and start the deployment manually (see the [testing spec](testing.md)). Public hosting, TLS and authentication are out of scope.
