from fastapi.testclient import TestClient
from app.main import app
import socket


def test_health_returns_ok_without_external_services(monkeypatch, tmp_path):
    """"""
    # Use an empty directory so the project's .env cannot be loaded.
    monkeypatch.chdir(tmp_path)

    for name in (
        "DATABASE_URL",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "SUMMARIZATION_MODEL_ID",
        "SUMMARIZATION_MODEL_PATH",
    ):
        monkeypatch.delenv(name, raising=False)

    def prohibit_network(*args, **kwargs):
            raise AssertionError("Health must not access external services")

    monkeypatch.setattr(socket.socket, "connect", prohibit_network)
    monkeypatch.setattr(socket.socket, "connect_ex", prohibit_network)
    monkeypatch.setattr(socket, "create_connection", prohibit_network)
    monkeypatch.setattr(socket, "getaddrinfo", prohibit_network)

    # Import after removing settings and prohibiting networking.
    from app.main import app

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
