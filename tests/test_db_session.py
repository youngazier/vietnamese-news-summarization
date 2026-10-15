"""D2.3 unit tests: no credentials or live PostgreSQL connection required."""

import subprocess
import sys
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.db import session as db_session


@pytest.fixture(autouse=True)
def isolate_database_configuration(monkeypatch):
    """Forget cached objects and replace settings so .env is never read."""
    cached_engine = db_session.get_engine
    cached_factory = db_session.get_session_factory
    cached_engine.cache_clear()
    cached_factory.cache_clear()
    monkeypatch.setattr(
        db_session,
        "get_settings",
        lambda: SimpleNamespace(
            DATABASE_URL="postgresql+psycopg://user:password@localhost/news?sslmode=require"
        ),
    )
    yield
    cached_factory.cache_clear()
    cached_engine.cache_clear()


def test_import_does_not_load_settings_or_create_engine():
    # A fresh interpreter proves behavior on the first import, not a cached import.
    script = """
from unittest.mock import patch

with patch('app.core.config.get_settings', side_effect=AssertionError('settings loaded')), \\
     patch('sqlalchemy.create_engine', side_effect=AssertionError('engine created')):
    import app.db.session
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("database_url", "error_type", "message"),
    [
        ("", ValueError, "DATABASE_URL is not set"),
        (
            "not-a-url-with-private-password",
            RuntimeError,
            "Invalid DATABASE_URL format",
        ),
        (
            "postgresql+psycopg2://user:password@localhost/news?sslmode=require",
            RuntimeError,
            "driver",
        ),
        ("postgresql+psycopg://user:password@localhost/news", RuntimeError, "sslmode"),
        (
            "postgresql+psycopg://user:password@localhost/news?sslmode=prefer",
            RuntimeError,
            "sslmode",
        ),
        (
            "postgresql+psycopg://user:password@localhost/news?sslmode=disable",
            RuntimeError,
            "sslmode",
        ),
    ],
)
def test_invalid_configuration_rejected_before_engine_creation(
    monkeypatch, database_url, error_type, message
):
    monkeypatch.setattr(
        db_session, "get_settings", lambda: SimpleNamespace(DATABASE_URL=database_url)
    )
    create_engine = Mock()
    monkeypatch.setattr(db_session, "create_engine", create_engine)

    with pytest.raises(error_type, match=message) as caught:
        db_session.get_engine()

    create_engine.assert_not_called()
    assert "private-password" not in str(caught.value)
    assert "user:password" not in str(caught.value)


@pytest.mark.parametrize("sslmode", ["require", "verify-ca", "verify-full"])
def test_engine_configuration_and_cache(monkeypatch, sslmode):
    monkeypatch.setattr(
        db_session,
        "get_settings",
        lambda: SimpleNamespace(
            DATABASE_URL=f"postgresql+psycopg://user:password@localhost/news?sslmode={sslmode}"
        ),
    )
    engine = object()
    create_engine = Mock(return_value=engine)
    monkeypatch.setattr(db_session, "create_engine", create_engine)

    assert db_session.get_engine() is engine
    assert db_session.get_engine() is engine
    create_engine.assert_called_once()
    args, options = create_engine.call_args
    assert args[0].drivername == "postgresql+psycopg"
    assert args[0].query["sslmode"] == sslmode
    assert options == {
        "pool_size": 2,
        "max_overflow": 1,
        "pool_pre_ping": True,
        "connect_args": {
            "connect_timeout": 5,
            "options": "-c statement_timeout=10000 -c timezone=UTC",
        },
    }


def test_factory_is_cached_but_sessions_are_separate(monkeypatch):
    engine = Mock()
    monkeypatch.setattr(db_session, "get_engine", Mock(return_value=engine))

    factory = db_session.get_session_factory()
    assert db_session.get_session_factory() is factory
    db_session.get_engine.assert_called_once()

    with factory() as first, factory() as second:
        assert first is not second
        assert first.get_bind() is engine
        assert second.get_bind() is engine
        assert first.expire_on_commit is False
        assert second.expire_on_commit is False


@pytest.mark.parametrize("outcome", ["success", "exception", "cancelled"])
def test_dependency_closes_session(monkeypatch, outcome):
    session = Mock()

    @contextmanager
    def open_session():
        try:
            yield session
        finally:
            session.close()

    factory = Mock(side_effect=open_session)
    monkeypatch.setattr(db_session, "get_session_factory", lambda: factory)

    dependency = db_session.get_db()
    factory.assert_not_called()
    assert next(dependency) is session
    session.close.assert_not_called()

    if outcome == "success":
        with pytest.raises(StopIteration):
            next(dependency)
    elif outcome == "exception":
        with pytest.raises(RuntimeError, match="request failed"):
            dependency.throw(RuntimeError("request failed"))
    else:
        dependency.close()

    factory.assert_called_once_with()
    session.close.assert_called_once_with()
    session.commit.assert_not_called()
