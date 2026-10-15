"""Exercise the timer without waiting for wall-clock intervals."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event
from unittest.mock import MagicMock, Mock

import pytest
from app.core.config import Settings
from app.models import JobTrigger
from app.services.job_service import JobSubmissionError
from app.worker import build_scheduler, scheduled_tick
from sqlalchemy.exc import OperationalError


def test_interval_utc_coalescing_and_single_instance():
    stop = Event()
    factory = Mock()
    scheduler = build_scheduler(factory, Settings(_env_file=None), stop)
    job = scheduler.get_job("collection")
    assert str(scheduler.timezone) == "UTC"
    assert job.coalesce is True and job.max_instances == 1
    assert job.trigger.interval == timedelta(minutes=30)
    now = datetime(2026, 10, 15, tzinfo=UTC)
    assert job.trigger.get_next_fire_time(now, now) == now + timedelta(minutes=30)
    assert job.args == (factory, Settings(_env_file=None), stop)
    factory.assert_not_called()


def test_injected_ticks_use_distinct_sessions_and_only_enqueue(monkeypatch):
    sessions = []

    @contextmanager
    def factory():
        session = Mock()
        session.begin.return_value.__enter__ = Mock(return_value=None)
        session.begin.return_value.__exit__ = Mock(return_value=False)
        sessions.append(session)
        yield session

    enqueue = Mock()
    monkeypatch.setattr("app.worker.enqueue_job", enqueue)
    stop = Event()
    for _ in range(2):
        scheduled_tick(factory, Settings(_env_file=None), stop)
    assert len(sessions) == 2 and sessions[0] is not sessions[1]
    assert enqueue.call_count == 2
    for call, session in zip(enqueue.call_args_list, sessions, strict=True):
        assert call.args == (session,)
        assert call.kwargs == {"trigger": JobTrigger.SCHEDULED, "max_backlog": 5}


@pytest.mark.parametrize(
    "error",
    [
        JobSubmissionError(429, "job_backlog_full", "full"),
        OperationalError("private-db-url", {}, Exception("secret")),
    ],
)
def test_tick_redacts_failures_and_rolls_back(monkeypatch, caplog, error):
    factory = MagicMock()
    session = factory.return_value.__enter__.return_value
    monkeypatch.setattr("app.worker.enqueue_job", Mock(side_effect=error))
    scheduled_tick(factory, Settings(_env_file=None), Event())
    assert session.begin.return_value.__exit__.call_args.args[0] is type(error)
    assert "secret" not in caplog.text and "private-db-url" not in caplog.text


def test_stopped_tick_does_not_open_session():
    stop = Event()
    stop.set()
    factory = Mock()
    scheduled_tick(factory, Settings(_env_file=None), stop)
    factory.assert_not_called()


def test_interval_can_be_configured():
    scheduler = build_scheduler(
        Mock(), Settings(_env_file=None, COLLECTION_INTERVAL_MINUTES=45), Event()
    )
    assert scheduler.get_job("collection").trigger.interval == timedelta(minutes=45)
