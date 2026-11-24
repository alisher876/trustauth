import pytest
from fastapi.testclient import TestClient

import app.main
from app.main import app as fastapi_app

client = TestClient(fastapi_app)


@pytest.mark.parametrize(
    ("database_up", "redis_up", "expected"),
    [
        (True, True, {"status": "ok", "database": "ok", "redis": "ok"}),
        (False, True, {"status": "ok", "database": "unavailable", "redis": "ok"}),
        (True, False, {"status": "ok", "database": "ok", "redis": "unavailable"}),
    ],
)
def test_health_reports_each_service(monkeypatch, database_up, redis_up, expected):
    monkeypatch.setattr(app.main, "database_is_up", lambda: database_up)
    monkeypatch.setattr(app.main, "redis_is_up", lambda: redis_up)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == expected


def test_redis_is_up_is_false_when_redis_cannot_be_reached(monkeypatch):
    import redis

    from app.core import redis_store

    def refuse():
        raise redis.ConnectionError("no redis here")

    monkeypatch.setattr(redis_store.client, "ping", refuse)
    assert redis_store.redis_is_up() is False
