from fastapi.testclient import TestClient

from app.config import Config, get_config
from app.main import create_app
from tests.conftest import ok


def test_settings_defaults_and_partial_merge(client):
    s = ok(client.get("/api/settings"))
    assert s["scheduling_mode"] == "suggest" and s["calendar_mode"] == "read_only"
    assert s["personalization"]["min_samples"] == 5
    s = ok(
        client.put("/api/settings", json={"timezone": "Europe/Berlin", "personalization": {"min_samples": 8}})
    )
    assert s["timezone"] == "Europe/Berlin"
    assert s["personalization"] == {**s["personalization"], "min_samples": 8, "strong_samples": 20}
    assert client.put("/api/settings", json={"timezone": "Mars/Base"}).status_code == 422
    assert client.put("/api/settings", json={"scheduling_mode": "yolo"}).status_code == 422
    assert ok(client.get("/api/audit?action=settings.updated"))[0]["after"]["timezone"] == "Europe/Berlin"


def test_api_token_required_when_configured(engine, monkeypatch):
    monkeypatch.setenv("TIMEOS_API_TOKEN", "s3cret")
    get_config.cache_clear()
    try:
        app = create_app(Config(auto_migrate=False), engine=engine)
        with TestClient(app) as c:
            assert c.get("/api/health").status_code == 200
            r = c.get("/api/tasks")
            assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
            assert c.get("/api/tasks", headers={"Authorization": "Bearer wrong"}).status_code == 401
            assert c.get("/api/tasks", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    finally:
        get_config.cache_clear()


def test_not_found_shape(client):
    r = client.get("/api/tasks/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
