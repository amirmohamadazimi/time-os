"""Import focus-session exports into the session database (dry run, commit, rollback)."""

import hashlib
import statistics
import uuid
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError, ValidationFailed
from app.importer.focus_csv import (
    DurationUnit,
    ImportOptions,
    ParsedRow,
    ParseResult,
    SessionIndex,
    parse_file,
)
from app.models import FocusSession, ImportBatch, ImportRecord
from app.models.enums import (
    ActionSource,
    EndReason,
    ImportRecordStatus,
    SessionSource,
    SessionState,
    SessionType,
)
from app.schemas.imports import ImportIssue, ImportReport, ImportSummary
from app.schemas.settings import UserSettings
from app.services import audit

MAX_ISSUES_IN_REPORT = 500


def _status(row: ParsedRow) -> ImportRecordStatus:
    if not row.valid:
        return ImportRecordStatus.invalid
    if row.duplicate_of:
        return ImportRecordStatus.duplicate
    return ImportRecordStatus.imported


def _mark_existing_duplicates(db: Session, rows: list[ParsedRow], tolerance_s: int) -> None:
    candidates = [r for r in rows if r.valid and not r.duplicate_of]
    if not candidates:
        return
    ids = [r.external_id for r in candidates if r.external_id]
    known_ids: set[str] = set()
    for chunk in range(0, len(ids), 500):
        known_ids |= set(
            db.scalars(
                select(FocusSession.external_id).where(
                    FocusSession.source == SessionSource.import_,
                    FocusSession.external_id.in_(ids[chunk : chunk + 500]),
                )
            )
        )
    lo = min(r.start_utc for r in candidates) - timedelta(seconds=tolerance_s)
    hi = max(r.start_utc for r in candidates) + timedelta(seconds=tolerance_s)
    index = SessionIndex(tolerance_s)
    for s in db.scalars(
        select(FocusSession).where(
            FocusSession.voided_at.is_(None),
            FocusSession.state == SessionState.finished,
            FocusSession.start_time.between(lo, hi),
        )
    ):
        index.add(s.start_time, s.end_time, s.active_duration_s, s.type.value, f"existing session {s.id}")
    for row in candidates:
        if row.external_id and row.external_id in known_ids:
            row.duplicate_of = "previously imported (same id)"
            continue
        match = index.find(row.start_utc, row.end_utc, row.active_s, row.type)
        if match:
            row.duplicate_of = f"{match} (same start and duration)"


def _code(message: str) -> str:
    return message.split(":", 1)[0]


def _summary(parsed: ParseResult, previously: bool) -> ImportSummary:
    rows = parsed.rows
    new = [r for r in rows if _status(r) == ImportRecordStatus.imported]
    counted = [r for r in new if not r.exclude_from_stats]
    work = [r.active_s for r in counted if r.type == "work"]
    rest = [r.active_s for r in counted if r.type == "rest"]
    starts = [r.start_utc for r in new]
    warnings = Counter(_code(w) for r in rows if r.valid for w in r.warnings)
    errors = Counter(_code(e) for r in rows for e in r.errors)
    return ImportSummary(
        rows_read=len(rows),
        valid=len(new),
        duplicates=sum(1 for r in rows if _status(r) == ImportRecordStatus.duplicate),
        invalid=sum(1 for r in rows if not r.valid),
        flagged=sum(1 for r in new if r.quality_flags),
        excluded_from_stats=sum(1 for r in new if r.exclude_from_stats),
        work_sessions=sum(1 for r in new if r.type == "work"),
        rest_sessions=sum(1 for r in new if r.type == "rest"),
        total_focus_hours=round(sum(work) / 3600, 2),
        total_rest_hours=round(sum(rest) / 3600, 2),
        avg_work_session_minutes=round(statistics.fmean(work) / 60, 1) if work else None,
        median_work_session_minutes=round(statistics.median(work) / 60, 1) if work else None,
        first_session=min(starts) if starts else None,
        last_session=max(starts) if starts else None,
        duration_unit=parsed.duration_unit,
        duration_meaning=parsed.duration_meaning,
        sections=parsed.sections,
        assumed_timezone_rows=warnings.get("assumed_timezone", 0),
        columns_detected=parsed.columns,
        warnings_by_code=dict(warnings),
        errors_by_code=dict(errors),
        file_previously_imported=previously,
    )


def _issues(rows: list[ParsedRow]) -> list[ImportIssue]:
    out = []
    for row in rows:
        status = _status(row)
        warnings = list(row.warnings)
        if row.duplicate_of:
            warnings.insert(0, f"duplicate: of {row.duplicate_of}")
        if row.errors or warnings:
            out.append(
                ImportIssue(
                    row_number=row.row_number,
                    status=status,
                    errors=row.errors,
                    warnings=warnings,
                    raw=row.raw,
                )
            )
        if len(out) >= MAX_ISSUES_IN_REPORT:
            break
    return out


def import_focus_sessions(
    db: Session,
    data: bytes,
    filename: str,
    now: datetime,
    settings: UserSettings,
    *,
    default_timezone: str | None = None,
    duration_unit: DurationUnit = "auto",
    dry_run: bool = True,
) -> ImportReport:
    rules = settings.import_rules
    options = ImportOptions(
        default_timezone=default_timezone or settings.timezone,
        duration_unit=duration_unit,
        long_active_minutes=rules.long_active_minutes,
        long_pause_minutes=rules.long_pause_minutes,
        implausible_elapsed_hours=rules.implausible_elapsed_hours,
        duplicate_tolerance_seconds=rules.duplicate_tolerance_seconds,
        short_session_seconds=rules.short_session_seconds,
    )
    parsed = parse_file(data, options)
    if parsed.file_errors:
        raise ValidationFailed(
            "file cannot be imported",
            details={"errors": parsed.file_errors, "columns_detected": parsed.columns},
        )
    sha = hashlib.sha256(data).hexdigest()
    previously = (
        db.scalar(
            select(func.count())
            .select_from(ImportBatch)
            .where(ImportBatch.file_sha256 == sha, ImportBatch.rolled_back_at.is_(None))
        )
        or 0
    ) > 0
    _mark_existing_duplicates(db, parsed.rows, options.duplicate_tolerance_seconds)
    summary = _summary(parsed, previously)
    report = ImportReport(batch_id=None, dry_run=dry_run, summary=summary, issues=_issues(parsed.rows))
    if dry_run:
        return report

    batch = ImportBatch(
        id=uuid.uuid4(),
        filename=filename[:500],
        file_sha256=sha,
        options={"default_timezone": options.default_timezone, "duration_unit": duration_unit},
        summary=summary.model_dump(mode="json"),
        created_at=now,
    )
    db.add(batch)
    db.flush()
    for row in parsed.rows:
        status = _status(row)
        session_id = None
        if status == ImportRecordStatus.imported:
            session = FocusSession(
                id=uuid.uuid4(),
                type=SessionType(row.type),
                state=SessionState.finished,
                source=SessionSource.import_,
                start_time=row.start_utc,
                end_time=row.end_utc,
                tz_offset_minutes=row.tz_offset_minutes,
                planned_duration_s=row.planned_s,
                active_duration_s=row.active_s,
                paused_duration_s=row.paused_s,
                pause_count=row.pause_count,
                end_reason=EndReason(row.end_reason),
                notes=row.notes,
                tags=row.tags,
                external_id=row.external_id,
                import_batch_id=batch.id,
                quality_flags=row.quality_flags,
                exclude_from_stats=row.exclude_from_stats,
            )
            db.add(session)
            session_id = session.id
        warnings = ([f"duplicate: of {row.duplicate_of}"] if row.duplicate_of else []) + row.warnings
        db.add(
            ImportRecord(
                batch_id=batch.id,
                row_number=row.row_number,
                raw=row.raw,
                status=status,
                errors=row.errors,
                warnings=warnings,
                session_id=session_id,
            )
        )
    audit.record(
        db,
        action="import.committed",
        source=ActionSource.import_,
        entity_type="import_batch",
        entity_id=batch.id,
        after={
            "filename": filename,
            **summary.model_dump(mode="json", include={"rows_read", "valid", "duplicates", "invalid"}),
        },
    )
    db.commit()
    return report.model_copy(update={"batch_id": batch.id})


def get_batch(db: Session, batch_id: uuid.UUID) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise NotFoundError(f"import {batch_id} not found")
    return batch


def list_batches(db: Session) -> list[ImportBatch]:
    return list(db.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc())))


def list_records(
    db: Session, batch_id: uuid.UUID, status: ImportRecordStatus | None, limit: int, offset: int
) -> tuple[list[ImportRecord], int]:
    get_batch(db, batch_id)
    stmt = select(ImportRecord).where(ImportRecord.batch_id == batch_id)
    if status:
        stmt = stmt.where(ImportRecord.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(ImportRecord.row_number).limit(limit).offset(offset))
    return list(rows), total


def rollback(
    db: Session, batch_id: uuid.UUID, now: datetime, source: ActionSource = ActionSource.user
) -> ImportBatch:
    """Void every session the batch created. Raw records stay for reference."""
    batch = get_batch(db, batch_id)
    if batch.rolled_back_at is not None:
        raise ConflictError("import has already been rolled back")
    sessions = db.scalars(select(FocusSession).where(FocusSession.import_batch_id == batch_id)).all()
    voided = 0
    for s in sessions:
        if s.voided_at is None:
            s.voided_at = now
            voided += 1
        s.external_id = None  # free the id so the file can be imported again
    batch.rolled_back_at = now
    audit.record(
        db,
        action="import.rolled_back",
        source=source,
        entity_type="import_batch",
        entity_id=batch.id,
        before={"sessions": len(sessions)},
        after={"voided": voided},
    )
    db.commit()
    return batch
