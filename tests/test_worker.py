"""Process ownership, cancellation and startup without external dependencies."""

import subprocess
import sys
from contextlib import contextmanager
from threading import Event
from unittest.mock import MagicMock, Mock

import pytest
from app.core.config import Settings
from app.services.job_service import JobClaim
from app.worker import Worker, serve


@pytest.fixture
def worker():
    return Worker(
        MagicMock(),
        Settings(_env_file=None),
        [],
        Mock(),
        Mock(),
        Mock(),
        summarize_model_name="fixture/vit5",
        agent_model_name="fixture/gemini",
        stop=Event(),
    )


def test_claim_transaction_closes_before_processing(worker, monkeypatch):
    active = False
    session = Mock()

    @contextmanager
    def begin():
        nonlocal active
        active = True
        yield
        active = False

    session.begin = begin

    @contextmanager
    def factory():
        yield session

    worker.factory = factory
    claim = JobClaim(1, None)
    monkeypatch.setattr("app.worker.claim_job", Mock(return_value=claim))

    def process(value):
        assert value == claim and not active

    worker.run_job = process
    assert worker.run_once() is True


def test_idle_polling_uses_configured_interruptible_wait(worker):
    worker.run_once = Mock(return_value=False)
    worker.stop = Mock()
    worker.stop.is_set.side_effect = [False, True]
    worker.run_forever()
    worker.run_once.assert_called_once()
    worker.stop.wait.assert_called_once_with(10)


def test_busy_loop_does_not_sleep_between_jobs(worker):
    worker.run_once = Mock(return_value=True)
    worker.stop = Mock()
    worker.stop.is_set.side_effect = [False, True]
    worker.run_forever()
    worker.stop.wait.assert_not_called()


def test_stop_prevents_new_claim(worker):
    worker.stop.set()
    assert worker.run_once() is False
    worker.factory.assert_not_called()


def test_fatal_pipeline_error_marks_failed_and_propagates(worker, monkeypatch):
    worker._run_job = Mock(side_effect=RuntimeError("private prompt"))
    finish = Mock()
    monkeypatch.setattr("app.worker.finish_job", finish)
    with pytest.raises(RuntimeError):
        worker.run_job(JobClaim(12, None))
    assert finish.call_args.args[1] == 12
    assert finish.call_args.kwargs == {
        "failed": True,
        "message": "Job failed: database or pipeline error",
    }


def test_startup_loads_model_once_recovers_and_closes_resources(monkeypatch):
    # Patch at the dependency modules so serve still executes its real lazy imports.
    summarizer, provider = Mock(), Mock()
    load = Mock(return_value=summarizer)
    create_provider = Mock(return_value=provider)
    graph = Mock()
    monkeypatch.setattr("app.services.summary_service.get_summary_service", load)
    monkeypatch.setattr("app.services.gemini_service.GeminiService", create_provider)
    monkeypatch.setattr("app.agents.graph.build_news_graph", Mock(return_value=graph))
    factory = MagicMock()
    recover = Mock()
    monkeypatch.setattr("app.worker.recover_abandoned_work", recover)
    scheduler = Mock()
    monkeypatch.setattr("app.worker.build_scheduler", Mock(return_value=scheduler))
    loop = Mock()
    monkeypatch.setattr("app.worker.Worker.run_forever", loop)
    stop = Event()
    serve(
        factory,
        Settings(_env_file=None, GEMINI_API_KEY="fixture", GEMINI_MODEL="fixture"),
        [],
        stop,
    )
    load.assert_called_once_with()
    create_provider.assert_called_once()
    recover.assert_called_once()
    scheduler.start.assert_called_once_with()
    loop.assert_called_once_with()
    scheduler.shutdown.assert_called_once_with(wait=True)
    provider.close.assert_called_once_with()
    assert stop.is_set()


def test_worker_requires_provider_settings_before_loading_model(monkeypatch):
    load = Mock()
    monkeypatch.setattr("app.services.summary_service.get_summary_service", load)
    with pytest.raises(ValueError, match="requires"):
        serve(Mock(), Settings(_env_file=None, GEMINI_API_KEY="", GEMINI_MODEL=""), [], Event())
    load.assert_not_called()


def test_api_import_does_not_import_worker_or_model():
    # A fresh interpreter catches accidental transitive imports hidden by pytest.
    program = (
        "import sys; import app.main; "
        "assert not {'app.worker', 'app.services.summary_service', 'torch', 'transformers', "
        "'apscheduler', 'app.services.gemini_service'} & sys.modules.keys()"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
