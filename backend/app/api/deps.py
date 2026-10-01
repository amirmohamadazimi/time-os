import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_config
from app.schemas.settings import UserSettings
from app.services.settings import get_settings


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def get_now() -> datetime:
    """The request's notion of 'now'. Overridden in tests with a fixed clock."""
    return datetime.now(UTC)


def get_user_settings(db: Annotated[Session, Depends(get_db)]) -> UserSettings:
    return get_settings(db)


def require_token(request: Request) -> None:
    token = get_config().api_token
    if not token:
        return
    header = request.headers.get("authorization", "")
    scheme, _, supplied = header.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(supplied.strip(), token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing API token")


DB = Annotated[Session, Depends(get_db)]
Now = Annotated[datetime, Depends(get_now)]
Settings = Annotated[UserSettings, Depends(get_user_settings)]
