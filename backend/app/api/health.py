from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.api.deps import DB

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: DB):
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except SQLAlchemyError:
        db_status = "down"
    return {"status": "ok" if db_status == "ok" else "degraded", "db": db_status, "version": __version__}
