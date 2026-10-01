from datetime import datetime
from typing import Any

from app.models.enums import ActionSource
from app.schemas.common import ORMModel


class AuditEntryOut(ORMModel):
    id: int
    at: datetime
    action: str
    source: ActionSource
    entity_type: str
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None
