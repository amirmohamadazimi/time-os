"""Append-only audit log for destructive, automatic and AI-initiated actions."""

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.models import AuditEntry
from app.models.enums import ActionSource


def jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [jsonable(v) for v in value]
    return value


def snapshot(obj: Any, exclude: tuple[str, ...] = ("created_at", "updated_at")) -> dict[str, Any]:
    """Column values of an ORM object as JSON-safe data."""
    mapper = inspect(obj).mapper
    return {
        attr.key: jsonable(getattr(obj, attr.key)) for attr in mapper.column_attrs if attr.key not in exclude
    }


def diff(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    keys = [k for k in after if before.get(k) != after.get(k)]
    return {k: before.get(k) for k in keys}, {k: after[k] for k in keys}


def record(
    db: Session,
    *,
    action: str,
    source: ActionSource,
    entity_type: str,
    entity_id: Any = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AuditEntry:
    entry = AuditEntry(
        action=action,
        source=source,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=jsonable(before) if before is not None else None,
        after=jsonable(after) if after is not None else None,
        reason=reason,
    )
    db.add(entry)
    return entry


def list_entries(
    db: Session,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    limit: int = 100,
) -> list[AuditEntry]:
    stmt = select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)
    if entity_type:
        stmt = stmt.where(AuditEntry.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditEntry.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditEntry.action == action)
    return list(db.scalars(stmt))
