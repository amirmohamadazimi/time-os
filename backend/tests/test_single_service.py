"""One-process deployment: the API also serves the built frontend, and hosted Postgres URLs work."""

from fastapi.testclient import TestClient

from app.config import Config
from app.main import create_app


def test_hosted_postgres_urls_use_psycopg():
    neon = "postgres://u:p@ep-x.neon.tech/timeos?sslmode=require"
    assert (
        Config(database_url=neon).database_url
        == "postgresql+psycopg://u:p@ep-x.neon.tech/timeos?sslmode=require"
    )
    assert Config(database_url="postgresql://u:p@h/db").database_url == "postgresql+psycopg://u:p@h/db"
    assert (
        Config(database_url="postgresql+psycopg://u:p@h/db").database_url == "postgresql+psycopg://u:p@h/db"
    )
    assert Config(database_url="sqlite:///./data/t.db").database_url == "sqlite:///./data/t.db"


def test_serves_frontend_build(tmp_path, engine):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>Time OS</html>")
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("private")
    app = create_app(Config(auto_migrate=False, api_token=None, static_dir=str(tmp_path)), engine=engine)
    with TestClient(app) as c:
        home = c.get("/")
        assert home.status_code == 200 and "Time OS" in home.text
        assert home.headers["cache-control"] == "no-cache"
        assert home.headers["x-frame-options"] == "DENY"
        assert "Time OS" in c.get("/tasks").text  # client-side route falls back to index.html
        assert c.head("/tasks").status_code == 200
        asset = c.get("/assets/app-abc123.js")
        assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
        assert "private" not in c.get("/..%2Fsecret.txt").text  # no escaping the build directory
        missing = c.get("/api/does-not-exist")
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
        assert c.post("/api/does-not-exist").status_code == 404  # not a 405 from the UI route
        assert c.delete("/api/settings").status_code == 405
        assert c.get("/api/health").json()["status"] == "ok"
