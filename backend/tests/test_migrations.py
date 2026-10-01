"""The Alembic migrations must produce exactly the schema the models describe."""

import os

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config as AlembicConfig
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

import app.models  # noqa: F401
from app.db import Base
from app.main import BACKEND_DIR


def _alembic(url: str) -> AlembicConfig:
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_upgrade_matches_models_and_downgrades(tmp_path):
    # On PostgreSQL this runs in the test database, which is empty between tests.
    url = os.environ.get("TIMEOS_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'm.db'}"
    command.upgrade(_alembic(url), "head")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            opts = {"render_as_batch": True} if url.startswith("sqlite") else {}
            diff = compare_metadata(MigrationContext.configure(conn, opts=opts), Base.metadata)
        assert diff == []
    finally:
        command.downgrade(_alembic(url), "base")
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        engine.dispose()
