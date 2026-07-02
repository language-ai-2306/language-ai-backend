"""GUID helpers — resolve public GUIDs to internal rows.

Convention: the API speaks GUIDs (every request/response id field is a `guid`).
Integer `id` is internal only (FKs, joins). Services use these helpers to turn an
incoming GUID into an ORM row, and read `.guid` when serialising responses.
"""

import uuid
from typing import Optional, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import AbstractEntity

_M = TypeVar("_M", bound=AbstractEntity)


def parse_guid(value) -> Optional[uuid.UUID]:
    """Coerce a value to a UUID, or None if it isn't a valid GUID."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def get_by_guid(db: Session, model: Type[_M], guid) -> Optional[_M]:
    """Fetch one row of `model` by its GUID, or None (invalid GUID → None)."""
    g = parse_guid(guid)
    if g is None:
        return None
    return db.scalar(select(model).where(model.guid == g))
