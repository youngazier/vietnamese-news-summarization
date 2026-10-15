"""Download once; runtime inference never contacts Hugging Face."""

import os
import tempfile
from pathlib import Path

from app.core.config import Settings
from app.services.model_artifacts import ModelArtifactError, validate_artifacts, write_manifest


def download_model(settings: Settings) -> Path:
    if any(
        os.environ.get(flag, "").upper() in {"1", "TRUE", "YES", "ON"}
        for flag in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
    ):
        raise ModelArtifactError("Disable HF_HUB_OFFLINE and TRANSFORMERS_OFFLINE for download.")

    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    target = Path(settings.SUMMARIZATION_MODEL_PATH).resolve()
    model_id = settings.SUMMARIZATION_MODEL_ID
    if target.exists():
        validate_artifacts(target, model_id)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    # Only publish the directory once all files and their manifest validate.
    with tempfile.TemporaryDirectory(prefix=f".{target.name}-", dir=target.parent) as temporary:
        staging = Path(temporary) / "artifacts"
        # The configured ViT5 repository is public; avoid implicit cached HF credentials.
        tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=False, token=False)
        model = AutoModelForSeq2SeqLM.from_pretrained(model_id, token=False).to("cpu")
        tokenizer.save_pretrained(staging)
        model.save_pretrained(staging, safe_serialization=True)
        write_manifest(staging, model_id, getattr(model.config, "_commit_hash", None))
        staging.rename(target)
    return target


def main() -> int:
    try:
        path = download_model(Settings())
    except ModelArtifactError as exc:
        print(f"Model download failed: {exc}")
        return 1
    except (OSError, ValueError, RuntimeError):
        # Provider exception messages can contain credential-bearing URLs.
        print("Model download failed. Check connectivity, offline flags, model ID and artifacts.")
        return 1
    print(f"Complete local model saved at {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
