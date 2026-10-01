import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.enums import ImportRecordStatus
from app.schemas.common import ORMModel


class ImportSummary(BaseModel):
    rows_read: int
    valid: int
    duplicates: int
    invalid: int
    flagged: int
    excluded_from_stats: int
    work_sessions: int
    rest_sessions: int
    total_focus_hours: float
    total_rest_hours: float
    avg_work_session_minutes: float | None
    median_work_session_minutes: float | None
    first_session: datetime | None
    last_session: datetime | None
    duration_unit: str
    assumed_timezone_rows: int
    columns_detected: dict[str, str]
    warnings_by_code: dict[str, int]
    errors_by_code: dict[str, int]
    file_previously_imported: bool = False


class ImportIssue(BaseModel):
    row_number: int
    status: ImportRecordStatus
    errors: list[str]
    warnings: list[str]
    raw: dict[str, Any]


class ImportReport(BaseModel):
    batch_id: uuid.UUID | None
    dry_run: bool
    summary: ImportSummary
    issues: list[ImportIssue]


class ImportBatchOut(ORMModel):
    id: uuid.UUID
    kind: str
    filename: str
    file_sha256: str
    options: dict[str, Any]
    summary: dict[str, Any]
    created_at: datetime
    rolled_back_at: datetime | None


class ImportRecordOut(ORMModel):
    id: int
    row_number: int
    raw: dict[str, Any]
    status: ImportRecordStatus
    errors: list[str]
    warnings: list[str]
    session_id: uuid.UUID | None
