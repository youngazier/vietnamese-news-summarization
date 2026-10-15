"""Job HTTP errors stay independent of a live database."""

import pytest
from app.db.session import get_db
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("post", "/api/v1/ingestion-jobs", {"json": {}}),
        ("get", "/api/v1/ingestion-jobs/1", {}),
    ],
)
def test_job_database_outage_returns_redacted_503(method, path, kwargs):
    def unavailable():
        raise OperationalError("private database URL", {}, Exception("private password"))
        yield  # pragma: no cover -- preserve the dependency's generator shape.

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = unavailable
    try:
        with TestClient(app) as client:
            response = client.request(method, path, **kwargs)
        assert response.status_code == 503
        assert response.json() == {
            "detail": {
                "code": "database_unavailable",
                "message": "Database is temporarily unavailable.",
            }
        }
        assert "private" not in response.text
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
