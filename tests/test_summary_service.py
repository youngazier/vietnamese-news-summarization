import json
import runpy
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.core.config import Settings
from app.services import summary_service
from app.services.model_artifacts import (
    MANIFEST_NAME,
    ModelArtifactError,
    validate_artifacts,
    write_manifest,
)
from app.services.summary_service import SummaryService

MODEL_ID = "fixture/vit5"


def write_files(path):
    path.mkdir(parents=True, exist_ok=True)
    for name in ["config.json", "tokenizer_config.json", "spiece.model", "model.safetensors"]:
        (path / name).write_bytes(b"fixture data")


@pytest.fixture
def artifacts(tmp_path):
    path = tmp_path / "model"
    write_files(path)
    write_manifest(path, MODEL_ID, "fixture-revision")
    return path


@pytest.mark.parametrize("problem", ["missing", "identity", "truncated", "corrupt", "vocab"])
def test_incomplete_and_corrupt_artifacts_fail(artifacts, problem):
    if problem == "missing":
        (artifacts / MANIFEST_NAME).unlink()
    elif problem == "identity":
        manifest = json.loads((artifacts / MANIFEST_NAME).read_text())
        manifest["model_id"] = "another/model"
        (artifacts / MANIFEST_NAME).write_text(json.dumps(manifest))
    elif problem == "truncated":
        (artifacts / "model.safetensors").write_bytes(b"short")
    elif problem == "corrupt":
        (artifacts / "model.safetensors").write_bytes(b"changed data")
    else:
        (artifacts / "spiece.model").unlink()
    with pytest.raises(ModelArtifactError, match="local model artifacts"):
        validate_artifacts(artifacts, MODEL_ID)


def test_manifest_rejects_path_traversal(artifacts):
    manifest = json.loads((artifacts / MANIFEST_NAME).read_text())
    manifest["files"]["../outside"] = {"size": 1, "sha256": "invalid"}
    (artifacts / MANIFEST_NAME).write_text(json.dumps(manifest))
    with pytest.raises(ModelArtifactError):
        validate_artifacts(artifacts, MODEL_ID)


def test_missing_model_fails_before_transformers_import(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "transformers", None)
    with pytest.raises(ModelArtifactError, match="download_summarization_model.py"):
        SummaryService(
            Settings(
                _env_file=None,
                SUMMARIZATION_MODEL_ID=MODEL_ID,
                SUMMARIZATION_MODEL_PATH=str(tmp_path / "missing"),
            )
        )


@pytest.fixture
def fake_runtime(monkeypatch):
    tokenizer = Mock(eos_token_id=1)
    tokenizer.encode.return_value = [3, 4, 5]
    tokenizer.decode.side_effect = lambda ids, **_: (
        "Bản tóm tắt tiếng Việt." if ids == [0, 9, 1] else "Nguồn được giữ lại"
    )
    model = Mock()
    model.to.return_value = model
    model.generate.return_value = [[0, 9, 1]]
    tokenizer_class = Mock()
    tokenizer_class.from_pretrained.return_value = tokenizer
    model_class = Mock()
    model_class.from_pretrained.return_value = model
    torch = SimpleNamespace(
        set_num_threads=Mock(),
        long="long",
        inference_mode=nullcontext,
        tensor=lambda data, **_: SimpleNamespace(data=data, shape=(1, len(data[0]))),
        ones_like=lambda _: "attention-mask",
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(
            AutoTokenizer=tokenizer_class,
            AutoModelForSeq2SeqLM=model_class,
        ),
    )
    return tokenizer, model, tokenizer_class, model_class, torch


def load_service(artifacts):
    return SummaryService(
        Settings(
            _env_file=None,
            SUMMARIZATION_MODEL_ID=MODEL_ID,
            SUMMARIZATION_MODEL_PATH=str(artifacts),
        )
    )


def test_cpu_local_load_and_reuse_with_exactly_one_eos(artifacts, fake_runtime):
    tokenizer, model, tokenizer_class, model_class, _ = fake_runtime
    service = load_service(artifacts)
    first = service.summarize("Nguồn tiếng Việt")
    tokenizer.encode.return_value = [3, 4, 5, 1]
    second = service.summarize("Nguồn khác</s>", attempt=2)
    tokenizer_class.from_pretrained.assert_called_once_with(
        artifacts,
        local_files_only=True,
        use_fast=False,
    )
    model_class.from_pretrained.assert_called_once_with(artifacts, local_files_only=True)
    model.to.assert_called_once_with("cpu")
    model.eval.assert_called_once()
    assert first.summary == second.summary == "Bản tóm tắt tiếng Việt."
    assert not first.input_truncated and first.input_tokens == 4
    assert first.generated_tokens == 2
    for call in model.generate.call_args_list:
        assert call.kwargs["input_ids"].data == [[3, 4, 5, 1]]
        assert call.kwargs["max_new_tokens"] == 256
        assert call.kwargs["do_sample"] is False
        assert call.kwargs["no_repeat_ngram_size"] == 3
    assert (
        model.generate.call_args_list[0].kwargs["num_beams"]
        != model.generate.call_args_list[1].kwargs["num_beams"]
    )
    assert model.generate.call_args_list[0].kwargs["length_penalty"] == 1.0
    assert model.generate.call_args_list[1].kwargs["length_penalty"] == 0.8
    assert tokenizer.encode.call_args_list[0].args == ("Nguồn tiếng Việt",)


def test_long_input_truncates_before_eos_and_records_retained_text(artifacts, fake_runtime):
    tokenizer, model, *_ = fake_runtime
    tokenizer.encode.return_value = list(range(3, 2003))
    result = load_service(artifacts).summarize("Nguồn dài")
    assert result.input_truncated and result.input_tokens == 1024
    ids = model.generate.call_args.kwargs["input_ids"].data[0]
    assert len(ids) == 1024 and ids[-1] == 1
    tokenizer.decode.assert_any_call(list(range(3, 1026)), skip_special_tokens=True)
    assert result.inference_text == "Nguồn được giữ lại"


@pytest.mark.parametrize(
    "text,attempt",
    [("", 1), (" ", 1), ("x" * 20001, 1), ("text", 3), ("text", True), ("text", 1.0)],
)
def test_invalid_input_never_generates(artifacts, fake_runtime, text, attempt):
    service = load_service(artifacts)
    with pytest.raises(ValueError):
        service.summarize(text, attempt=attempt)
    fake_runtime[1].generate.assert_not_called()


def test_corrupt_transformers_files_fail_startup(artifacts, fake_runtime):
    fake_runtime[3].from_pretrained.side_effect = OSError("broken weights")
    with pytest.raises(ModelArtifactError, match="Cannot load"):
        load_service(artifacts)


def test_cached_service_initializes_once(monkeypatch):
    constructor = Mock()
    monkeypatch.setattr(summary_service, "SummaryService", constructor)
    monkeypatch.setattr(summary_service, "get_settings", lambda: Settings(_env_file=None))
    summary_service.get_summary_service.cache_clear()
    try:
        assert summary_service.get_summary_service() is summary_service.get_summary_service()
        constructor.assert_called_once()
    finally:
        summary_service.get_summary_service.cache_clear()


def test_downloader_publishes_complete_artifacts_atomically(tmp_path, fake_runtime, monkeypatch):
    for flag in ["HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"]:
        monkeypatch.setenv(flag, "0")
    tokenizer, model, *_ = fake_runtime
    tokenizer.save_pretrained.side_effect = write_files
    model.config._commit_hash = "fixture-revision"
    download = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "download_summarization_model.py")
    )["download_model"]
    target = tmp_path / "downloaded"
    settings = Settings(
        _env_file=None, SUMMARIZATION_MODEL_ID=MODEL_ID, SUMMARIZATION_MODEL_PATH=str(target)
    )
    assert download(settings) == target
    validate_artifacts(target, MODEL_ID)
    assert download(settings) == target
    assert tokenizer.save_pretrained.call_count == 1


def test_failed_download_never_publishes_partial_model(tmp_path, fake_runtime, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "0")
    fake_runtime[1].save_pretrained.side_effect = OSError("disk error")
    download = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "download_summarization_model.py")
    )["download_model"]
    target = tmp_path / "downloaded"
    with pytest.raises(OSError):
        download(
            Settings(
                _env_file=None,
                SUMMARIZATION_MODEL_ID=MODEL_ID,
                SUMMARIZATION_MODEL_PATH=str(target),
            )
        )
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []
