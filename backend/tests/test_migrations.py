"""The Alembic migrations must produce exactly the schema the models describe."""

import os

import pytest
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


@pytest.mark.skipif(bool(os.environ.get("TIMEOS_TEST_DATABASE_URL")), reason="uses its own database")
def test_upgrade_matches_models_and_downgrades(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    command.upgrade(_alembic(url), "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(
            MigrationContext.configure(conn, opts={"render_as_batch": True}), Base.metadata
        )
    assert diff == []
    command.downgrade(_alembic(url), "base")
    engine.dispose()
