from datetime import UTC, datetime
from typing import Annotated, Any, Generic, TypeVar

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict

MAX_TAGS = 30
MAX_TAG_LEN = 50


def normalize_tags(tags: list[str] | None) -> list[str]:
    """Strip whitespace and leading '#', drop empties, de-duplicate case-insensitively (keeping order)."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        tag = raw.strip().lstrip("#").strip()
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        if len(tag) > MAX_TAG_LEN:
            raise ValueError(f"tag longer than {MAX_TAG_LEN} characters: {tag[:20]}...")
        seen.add(key)
        out.append(tag)
    if len(out) > MAX_TAGS:
        raise ValueError(f"at most {MAX_TAGS} tags allowed")
    return out


Tags = Annotated[list[str], AfterValidator(normalize_tags)]


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


# Request timestamps must carry an offset (naive values are rejected) and are normalised to UTC.
UTCDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
