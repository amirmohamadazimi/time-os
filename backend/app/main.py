"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from app import __version__
from app.api import focus, health, projects, sessions, settings, tasks
from app.api.deps import require_token
from app.config import Config, get_config
from app.db import make_engine, make_session_factory
from app.errors import DomainError

log = logging.getLogger("timeos")
BACKEND_DIR = Path(__file__).resolve().parent.parent


def run_migrations(url: str) -> None:
    from alembic import command
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details}})


def create_app(config: Config | None = None, engine: Engine | None = None) -> FastAPI:
    config = config or get_config()
    engine = engine or make_engine(config.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if config.auto_migrate and engine.url.database not in (None, ":memory:"):
            run_migrations(config.database_url)
        yield

    app = FastAPI(
        title="Time OS",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError):
        return _error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return _error(422, "validation_error", "request validation failed", details)

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException):
        code = {401: "unauthorized", 404: "not_found"}.get(exc.status_code, "http_error")
        return _error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(OperationalError)
    async def _db_down(_: Request, exc: OperationalError):
        log.error("database error: %s", exc)
        return _error(503, "unavailable", "database is unavailable")

    app.include_router(health.router, prefix="/api")
    protected = [Depends(require_token)]
    for module in (projects, tasks, focus, sessions, settings):
        app.include_router(module.router, prefix="/api", dependencies=protected)
    return app

