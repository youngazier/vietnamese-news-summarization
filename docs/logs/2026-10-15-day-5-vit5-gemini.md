# Day 5: local ViT5 and Gemini metadata

Day 5 implements the downloader, local summarizer, metadata schemas, stateless Gemini
adapter and draft node. The review graph, approved-summary persistence and worker are
Day 6–7 tasks. Publisher AI/extraction flags remain disabled; feasibility checks use
authored fictional Vietnamese text, without reading publisher content or writing articles.

## Setup and model download

Run from the repository root with Python 3.12:

```sh
uv sync --locked --python 3.12
uv pip check
uv run --locked python -c 'import torch; print(torch.__version__); assert torch.version.cuda is None'
```

The explicit `pytorch-cpu` index supplies only Torch. The lock now selects
`torch==2.14.1+cpu` on Linux/Python 3.12; Transformers 4.57.6, SentencePiece 0.2.2,
LangGraph 1.2.14 and google-genai 2.29.0 remain compatible. The CPU change removes
the previous CUDA dependencies. No unrelated dependency upgrade was requested.

```sh
export SUMMARIZATION_MODEL_ID=VietAI/vit5-base-vietnews-summarization
export SUMMARIZATION_MODEL_PATH="$PWD/.models/vit5-base-vietnews-summarization"
HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 uv run --locked --env-file .env python download_summarization_model.py
```

The [VietAI model card](https://huggingface.co/VietAI/vit5-base-vietnews-summarization)
specifies no instruction prefix. The downloader uses anonymous access to the public
repository, so stale cached Hugging Face credentials do not break public downloads.
It saves both the slow SentencePiece tokenizer and safetensors weights into a temporary
sibling directory, writes `model_manifest.json`, validates every file, then atomically
publishes the target directory. This needs approximately 863 MiB for saved artifacts,
plus the Hugging Face download cache. The model directory is ignored by Git.

The manifest records the configured model ID, upstream revision, file sizes and SHA-256
hashes. Repeating the command reuses an already valid directory. An incomplete or
mismatched existing directory fails validation: move it aside or remove that model
directory before retrying. The downloader does not replace an existing invalid directory.

## Offline inference

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked --env-file .env python -m app.services.summary_service --smoke-test
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked --env-file .env pytest -m model tests/model/test_summary_smoke.py -q -s

# Expected failure, exit 1; never falls back to a download:
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 SUMMARIZATION_MODEL_PATH=/missing uv run --locked --env-file .env python -m app.services.summary_service --smoke-test
```

`SummaryService` validates manifest identity/integrity before loading with
`local_files_only=True`, moves weights to CPU and calls `eval()`. Generation runs in
`torch.inference_mode()`. `get_summary_service()` caches one instance for later worker
startup and reuse. API imports and requests do not initialize ViT5.

Input accepts cleaned text up to 20,000 characters. It retains at most 1,023 content
tokens and adds exactly one trailing EOS, giving a 1,024-token encoder bound. No
instruction prefix or review feedback is appended. Each result records the decoded
retained text, truncation, token counts and elapsed inference time. Generation is
deterministic, capped at 256 new tokens, with four beams on the first attempt and two
beams/a shorter length penalty on the second. `SUMMARIZATION_CPU_THREADS=4` limits
thread overhead on the development machine; use 1–32 according to available hardware.

The real model tests prohibit socket connections during loading and generation and
verify ordinary Vietnamese output, EOS, CPU/eval mode, long-input truncation and reuse.
The smoke CLI reports inference/total latency and process peak RSS (MiB, Linux),
including model-loading memory. These are single-process observations, not a batch
throughput guarantee.

## Gemini metadata and draft node

Configure root `.env` privately:

```dotenv
GEMINI_API_KEY=your-private-key
GEMINI_MODEL=gemini-3.8-flash
```

```sh
uv run --locked pytest tests/test_ai_schemas.py tests/test_gemini_service.py tests/test_draft_node.py tests/test_summary_service.py -q
uv run --locked --env-file .env pytest -m live tests/live/test_gemini.py -q -s
```

The configured development account verified `gemini-3.8-flash` on 2026-10-15 through
the real Developer API. Other accounts must run the live check themselves. Each call
uses explicit `vertexai=False`, `client.interactions.create`, `store=False`, no tools
or previous interaction ID, and the Pydantic JSON schema as `response_format`.
See the official [Interactions guide](https://ai.google.dev/gemini-api/docs/interactions)
and [structured-output guide](https://ai.google.dev/gemini-api/docs/structured-output).

The request timeout is 30 seconds per HTTP attempt. In locked google-genai 2.29.0,
`HttpRetryOptions.attempts=2` means two retries for Interactions, allowing at most three
wire requests. Retryable statuses are 429/500/502/503/504; client errors such as 400/401
stop immediately. There is no application retry loop. Tests exercise the actual SDK
through `httpx.MockTransport`, including timeout, recovery on the third request,
terminal HTTP failures, stateless calls and malformed metadata. Provider exception
payloads are replaced with a fixed error message; schema failures do not become drafts.

The source/title are JSON data separated from the metadata system instruction.
Metadata is restricted to a known category and 3–5 distinct, trimmed Vietnamese
keywords, each at most 80 characters. Duplicate detection normalizes Unicode/case.
Unknown fields, including provider-written summary text, are rejected. `NewsDraft`
is assembled in Python from ViT5 output and validated metadata. `NewsState` requires
article inputs and permits partial output updates. `make_draft_node()` increments
the successful draft count, resets approval/feedback and stops calls after two drafts.
Model/provider failures propagate to the future worker boundary. No Day 6 review
or graph routing is claimed here.

## Verification — 2026-10-15

| Check | Result |
| --- | --- |
| Dependency sync/imports | Python 3.12, CPU Torch 2.14.1+cpu; `torch.version.cuda is None`; ViT5 classes, LangGraph and SDK import |
| Dependency consistency | `uv pip check`: 90 installed packages compatible |
| Unit regression | 187 passed; 3 external/model cases skipped; 60 PostgreSQL cases deselected |
| Real Gemini | 1 passed; category `society`; four Vietnamese keywords; model `gemini-3.8-flash` |
| Real ViT5 | 2 passed with sockets blocked; short/long generation, EOS, truncation and reuse; 53.32 s total |
| Short-fixture inference | 3.33 s; peak process RSS 1,301.76 MiB (about 1.27 GiB), four CPU threads |
| Standalone offline smoke CLI | Exit 0; 179 input/20 generated tokens; inference 1.48 s, total 10.48 s, peak RSS 1,283.39 MiB |
| Missing local model CLI | Exit 1 with an actionable artifact error |
| Build | `uv build --offline` produced sdist and wheel |

The real Gemini keywords were `thư viện Bình Minh`, `kỹ năng số`,
`dịch vụ công trực tuyến`, `người cao tuổi`. Unit transport results are fake-provider
checks and do not establish account access; the live result above does.

Focused Ruff checks/formatting pass for all Day 5 Python files. Checks ignore the
existing `EXE002` mount-permission issue (files appear executable). Repository-wide
lint and formatting still report pre-existing issues in migrations and older modules.
PostgreSQL tests were not rerun for this change: no schema or database behavior changed.

If the default uv cache is read-only in an agent environment, prefix commands with
`UV_CACHE_DIR=/tmp/vietnam-news-uv-cache`. Model/live tests are opt-in using the exact
`-m model` or `-m live` selectors above; normal unit runs do not contact external services.
