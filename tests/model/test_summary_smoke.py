"""Real saved ViT5, explicitly selected with `pytest -m model`."""

import json
import resource
import socket

import pytest
from app.core.config import Settings
from app.services.summary_service import (
    MAX_INPUT_TOKENS,
    MAX_NEW_TOKENS,
    SMOKE_TEXT,
    SummaryService,
)

pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def service(request):
    if request.config.getoption("markexpr").strip() != "model":
        pytest.skip("Explicitly select -m model to run actual local inference")
    import torch

    assert torch.version.cuda is None, "Install the locked CPU Torch wheel"
    with pytest.MonkeyPatch.context() as patch:

        def deny_network(*args, **kwargs):
            raise AssertionError("Local model check attempted network access")

        patch.setattr(socket.socket, "connect", deny_network)
        patch.setattr(socket, "create_connection", deny_network)
        patch.setenv("HF_HUB_OFFLINE", "1")
        patch.setenv("TRANSFORMERS_OFFLINE", "1")
        yield SummaryService(Settings())


def test_real_vietnamese_generation(service, record_property):
    result = service.summarize(SMOKE_TEXT)
    assert result.summary and any(ord(character) > 127 for character in result.summary)
    assert result.input_tokens <= MAX_INPUT_TOKENS
    assert 0 < result.generated_tokens <= MAX_NEW_TOKENS
    assert not result.input_truncated
    assert service.model.training is False
    assert str(next(service.model.parameters()).device) == "cpu"
    ids = service.tokenizer.encode(SMOKE_TEXT)
    assert ids[-1] == service.tokenizer.eos_token_id
    assert ids.count(service.tokenizer.eos_token_id) == 1
    metrics = {
        "model_id": service.model_id,
        "summary": result.summary,
        "latency_seconds": result.latency_seconds,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    }
    record_property("model_metrics", json.dumps(metrics, ensure_ascii=False))
    print(json.dumps(metrics, ensure_ascii=False))


def test_real_long_source_truncation_and_model_reuse(service):
    tokenizer_id, model_id = id(service.tokenizer), id(service.model)
    result = service.summarize(SMOKE_TEXT * 12)
    assert result.summary and result.input_truncated
    assert result.input_tokens == 1024 and result.generated_tokens <= 256
    assert result.inference_text and len(result.inference_text) < len(SMOKE_TEXT * 12)
    assert (id(service.tokenizer), id(service.model)) == (tokenizer_id, model_id)
