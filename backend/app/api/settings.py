from typing import Any

from fastapi import APIRouter, Body, Query

from app.api.deps import DB
from app.schemas.audit import AuditEntryOut
from app.schemas.settings import UserSettings
from app.services import audit
from app.services.settings import get_settings, update_settings

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=UserSettings)
def read_settings(db: DB):
    return get_settings(db)


@router.put("/settings", response_model=UserSettings)
def write_settings(db: DB, body: dict[str, Any] = Body(..., description="Partial UserSettings; deep-merged")):
    return update_settings(db, body)


@router.get("/audit", response_model=list[AuditEntryOut])
def read_audit(
    db: DB,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
):
    return audit.list_entries(db, entity_type=entity_type, entity_id=entity_id, action=action, limit=limit)
