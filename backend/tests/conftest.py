import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.deps import get_now
from app.config import Config
from app.db import Base, make_session_factory
from app.main import create_app

# Stored secrets (calendar links) are encrypted with this key instead of a generated key file.
os.environ.setdefault("TIMEOS_SECRET_KEY", "test-only-secret-key")

# Set TIMEOS_TEST_DATABASE_URL=postgresql+psycopg://... to run the suite against PostgreSQL.
TEST_DB_URL = os.environ.get("TIMEOS_TEST_DATABASE_URL")


class FakeClock:
    def __init__(self, start: datetime):
        self.now = start

    def advance(self, **kwargs) -> datetime:
        self.now = self.now + timedelta(**kwargs)
        return self.now

    def set(self, value: datetime) -> datetime:
        self.now = value
        return value


@pytest.fixture
def engine():
    if TEST_DB_URL:
        eng = create_engine(TEST_DB_URL)
        Base.metadata.drop_all(eng)
    else:
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(eng, "connect")
        def _fk(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db(engine):
    session = make_session_factory(engine)()
    yield session
    session.close()


@pytest.fixture
def clock():
    return FakeClock(datetime(2026, 10, 1, 8, 0, tzinfo=UTC))


@pytest.fixture
def client(engine, clock):
    application = create_app(Config(auto_migrate=False, api_token=None), engine=engine)
    application.dependency_overrides[get_now] = lambda: clock.now
    with TestClient(application) as c:
        yield c


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None
