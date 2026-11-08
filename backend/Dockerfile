FROM ghcr.io/astral-sh/uv:0.12.15-python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

ARG SUMMARIZATION_MODEL_ID=VietAI/vit5-base-vietnews-summarization
ENV SUMMARIZATION_MODEL_ID=${SUMMARIZATION_MODEL_ID} \
    SUMMARIZATION_MODEL_PATH=/opt/models/vit5-base-vietnews-summarization

# Install dependencies without project root to maximize layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Download and bake summarization model into the image
COPY download_summarization_model.py ./
COPY backend/app/__init__.py ./backend/app/__init__.py
COPY backend/app/core/ ./backend/app/core/
COPY backend/app/services/model_artifacts.py ./backend/app/services/model_artifacts.py
RUN PYTHONPATH=backend uv run --no-sync python download_summarization_model.py

# Copy application source and install project
COPY README.md ./
COPY backend/ ./backend/
RUN uv sync --locked --no-dev --no-editable

# Enforce offline flags at runtime
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

