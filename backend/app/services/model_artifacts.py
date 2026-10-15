"""Shared download/runtime validation for a complete, identified local model."""

import hashlib
import json
from pathlib import Path

MANIFEST_NAME = "model_manifest.json"


class ModelArtifactError(RuntimeError):
    """Local model files are absent, incomplete, or do not match configuration."""


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_manifest(path: Path, model_id: str, revision: str | None) -> None:
    files = {
        file.name: {"size": file.stat().st_size, "sha256": _digest(file)}
        for file in sorted(path.iterdir())
        if file.is_file() and file.name != MANIFEST_NAME
    }
    (path / MANIFEST_NAME).write_text(
        json.dumps(
            {"version": 1, "model_id": model_id, "revision": revision, "files": files},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    validate_artifacts(path, model_id)


def validate_artifacts(path: Path, model_id: str) -> None:
    """Validate identity and file hashes before Transformers can load anything."""
    try:
        manifest = json.loads((path / MANIFEST_NAME).read_text(encoding="utf-8"))
        if manifest["version"] != 1 or manifest["model_id"] != model_id:
            raise ValueError("Model manifest identity mismatch")
        files = manifest["files"]
        if (
            not isinstance(files, dict)
            or not {"config.json", "tokenizer_config.json"} <= files.keys()
        ):
            raise ValueError("Missing model/tokenizer configuration")
        if not {"spiece.model", "tokenizer.json"} & files.keys():
            raise ValueError("Missing tokenizer vocabulary")
        if not any(name.endswith(".safetensors") for name in files):
            raise ValueError("Missing model weights")
        for name, expected in files.items():
            if Path(name).name != name or name in {".", ".."}:
                raise ValueError("Invalid model filename")
            file = path / name
            if file.stat().st_size != expected["size"] or expected["size"] <= 0:
                raise ValueError("Incomplete model file")
            if _digest(file) != expected["sha256"]:
                raise ValueError("Corrupt model file")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ModelArtifactError(
            f"Missing, corrupt, or mismatched local model artifacts in {path}. "
            "Run download_summarization_model.py with offline flags disabled."
        ) from exc
