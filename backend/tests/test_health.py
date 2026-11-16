from fastapi.testclient import TestClient

import app.main
from app.main import app as fastapi_app

client = TestClient(fastapi_app)


def test_health_when_database_is_up(monkeypatch):
    monkeypatch.setattr(app.main, "database_is_up", lambda: True)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_when_database_is_down(monkeypatch):
    monkeypatch.setattr(app.main, "database_is_up", lambda: False)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "unavailable"}
