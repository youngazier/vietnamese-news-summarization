import pytest
from app.core.config import Settings
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def clear_settings_environment(monkeypatch):
    # Prevent the developer's exported settings from affecting tests.
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)


def test_defaults_without_env_file():
    cfg = Settings(_env_file=None)

    assert cfg.DATABASE_URL == ""
    assert cfg.COLLECTION_INTERVAL_MINUTES == 30
    assert cfg.WORKER_POLL_INTERVAL_SECONDS == 10
    assert cfg.JOB_MAX_ARTICLE_INSERTIONS == 20
    assert cfg.JOB_MAX_ARTICLE_RESULTS == 20
    assert cfg.MAX_JOB_BACKLOG == 5
    assert cfg.MAX_GRAPH_DRAFT_ATTEMPTS == 2
    assert cfg.SUMMARIZATION_CPU_THREADS == 4


def test_env_file_loading(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "WORKER_POLL_INTERVAL_SECONDS=15\nCOLLECTION_INTERVAL_MINUTES=45\n",
        encoding="utf-8",
    )

    cfg = Settings(_env_file=env_file)

    assert cfg.WORKER_POLL_INTERVAL_SECONDS == 15
    assert cfg.COLLECTION_INTERVAL_MINUTES == 45


def test_environment_overrides_env_file(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "WORKER_POLL_INTERVAL_SECONDS=15\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKER_POLL_INTERVAL_SECONDS", "25")

    cfg = Settings(_env_file=env_file)

    assert cfg.WORKER_POLL_INTERVAL_SECONDS == 25


@pytest.mark.parametrize(
    "name",
    [
        "COLLECTION_INTERVAL_MINUTES",
        "WORKER_POLL_INTERVAL_SECONDS",
        "JOB_MAX_ARTICLE_INSERTIONS",
        "JOB_MAX_ARTICLE_RESULTS",
        "MAX_JOB_BACKLOG",
    ],
)
@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_invalid_positive_limits(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("value", ["0", "-1", "3", "invalid"])
def test_invalid_graph_attempts(monkeypatch, value):
    monkeypatch.setenv("MAX_GRAPH_DRAFT_ATTEMPTS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("value", ["0", "-1", "33", "invalid"])
def test_invalid_model_cpu_threads(monkeypatch, value):
    monkeypatch.setenv("SUMMARIZATION_CPU_THREADS", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
