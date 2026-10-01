from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import get_config
from app.errors import ValidationFailed
from app.models import AppSettings
from app.models.enums import ActionSource
from app.schemas.settings import UserSettings
from app.services import audit


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def get_settings(db: Session) -> UserSettings:
    row = db.get(AppSettings, 1)
    data = dict(row.data) if row else {}
    data.setdefault("timezone", get_config().default_timezone)
    return UserSettings.model_validate(data)


def update_settings(db: Session, patch: dict[str, Any], source: ActionSource = ActionSource.user) -> UserSettings:
    current = get_settings(db)
    merged = _deep_merge(current.model_dump(mode="json"), patch)
    try:
        updated = UserSettings.model_validate(merged)
    except ValidationError as exc:
        raise ValidationFailed("invalid settings", details=exc.errors(include_url=False, include_context=False))
    row = db.get(AppSettings, 1)
    data = updated.model_dump(mode="json")
    if row is None:
        db.add(AppSettings(id=1, data=data))
    else:
        row.data = data
    before, after = audit.diff(current.model_dump(mode="json"), data)
    if after:
        audit.record(
            db, action="settings.updated", source=source, entity_type="settings", entity_id=1,
            before=before, after=after,
        )
    db.commit()
    return updated
