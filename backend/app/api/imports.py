import uuid
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, File, Query, UploadFile

from app.api.deps import DB, Now, Settings
from app.config import get_config
from app.errors import ValidationFailed
from app.importer import service
from app.models.enums import ImportRecordStatus
from app.schemas.common import Page
from app.schemas.imports import ImportBatchOut, ImportRecordOut, ImportReport

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("/focus-sessions", response_model=ImportReport)
async def import_focus_sessions(
    db: DB,
    now: Now,
    settings: Settings,
    file: UploadFile = File(...),
    dry_run: bool = True,
    default_timezone: str | None = None,
    duration_unit: Literal["auto", "seconds", "milliseconds", "minutes"] = "auto",
):
    limit = get_config().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ValidationFailed(f"file is larger than {get_config().max_upload_mb} MB")
    if not data.strip():
        raise ValidationFailed("file is empty")
    if default_timezone:
        try:
            ZoneInfo(default_timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValidationFailed(f"unknown timezone: {default_timezone}") from exc
    return service.import_focus_sessions(
        db,
        data,
        file.filename or "upload.csv",
        now,
        settings,
        default_timezone=default_timezone,
        duration_unit=duration_unit,
        dry_run=dry_run,
    )


@router.get("", response_model=list[ImportBatchOut])
def list_imports(db: DB):
    return service.list_batches(db)


@router.get("/{batch_id}", response_model=ImportBatchOut)
def get_import(db: DB, batch_id: uuid.UUID):
    return service.get_batch(db, batch_id)


@router.get("/{batch_id}/records", response_model=Page[ImportRecordOut])
def import_records(
    db: DB,
    batch_id: uuid.UUID,
    status: ImportRecordStatus | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    items, total = service.list_records(db, batch_id, status, limit, offset)
    return {"items": items, "total": total}


@router.delete("/{batch_id}", response_model=ImportBatchOut)
def rollback_import(db: DB, now: Now, batch_id: uuid.UUID):
    return service.rollback(db, batch_id, now)
