import json
import logging
import subprocess
import sys

from app.core.logging import JsonLogFormatter, LogEvent


def test_formatter_keeps_only_safe_event_and_numeric_context():
    record = logging.LogRecord(
        "app.worker", logging.INFO, __file__, 1, LogEvent.JOB_COMPLETED, (), None
    )
    record.job_id = 7
    record.source_id = "https://example.com?token=secret"
    record.latency_ms = 32
    record.exc_text = "private article body"
    line = JsonLogFormatter().format(record)

    assert len(line.splitlines()) == 1
    fields = json.loads(line)
    assert fields.pop("ts")
    assert fields == {
        "level": "INFO",
        "logger": "app.worker",
        "event": "job_completed",
        "job_id": 7,
        "source_id": None,
        "article_id": None,
        "latency_ms": 32,
    }


def test_log_level_and_redaction_in_a_fresh_process(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import logging
from app.core.config import LogSettings
from app.core.logging import LogEvent, configure_logging

configure_logging(LogSettings().LOG_LEVEL)
logging.getLogger("app.worker").info(LogEvent.WORKER_READY)
try:
    raise ValueError("PRIVATE_ARTICLE_BODY")
except ValueError:
    logging.getLogger("httpx").exception("https://example.com/api?token=%s", "SECRET")
""",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    (line,) = result.stderr.splitlines()
    assert json.loads(line)["event"] == "external_log"
    assert "example.com" not in line
    assert "SECRET" not in line
    assert "PRIVATE_ARTICLE_BODY" not in line
