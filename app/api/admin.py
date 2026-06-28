"""Admin configuration endpoints — doctor-only.

GET  /v1/admin/config           → list all config entries
GET  /v1/admin/config/{key}     → single entry
PUT  /v1/admin/config/{key}     → update a value

All endpoints require the DOCTOR role. Patients cannot read or change
runtime configuration.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import require_role
from app.db.base import get_db
from app.models.app_config import AppConfig
from app.models.user import User, UserRole
from app.schemas.app_config import AppConfigEntry, AppConfigUpdate
from app.services import config_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get(
    "/config",
    response_model=list[AppConfigEntry],
    summary="List all runtime configuration entries",
)
def list_config(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.DOCTOR)),
) -> list[AppConfig]:
    return db.query(AppConfig).order_by(AppConfig.key).all()


@router.get(
    "/config/{key}",
    response_model=AppConfigEntry,
    summary="Get a single config entry by key",
)
def get_config(
    key: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.DOCTOR)),
) -> AppConfig:
    row = db.query(AppConfig).filter(AppConfig.key == key).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    return row


@router.put(
    "/config/{key}",
    response_model=AppConfigEntry,
    summary="Update a config value",
    responses={
        400: {"description": "Value cannot be parsed as the declared type"},
        403: {"description": "Config key is read-only"},
        404: {"description": "Config key not found"},
    },
)
def update_config(
    key: str,
    payload: AppConfigUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.DOCTOR)),
) -> AppConfig:
    try:
        return config_service.set_value(key, payload.value, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
