"""User routes — thin controller, delegates to UserService. Ids are GUIDs."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.schemas.user import UserRead, UserUpdate
from app.services import user as user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "",
    response_model=List[UserRead],
    summary="List all users",
    response_description="Paginated list of user accounts",
)
def list_users(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> List[User]:
    """Return a paginated list of all user accounts. Requires authentication."""
    return user_service.list_users(db, skip, limit)


@router.get(
    "/{user_id}",
    response_model=UserRead,
    summary="Get a user by ID",
    response_description="The requested user account",
    responses={404: {"description": "User not found"}},
)
def get_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> User:
    """Fetch a single user account by their numeric ID."""
    return user_service.get_or_404(db, user_id)


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    summary="Update a user",
    response_description="The updated user account",
    responses={
        403: {"description": "Cannot modify another user's account (patients only)"},
        404: {"description": "User not found"},
    },
)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Partially update a user account. Only send the fields you want to change.

    - **Patients** can only update their own account.
    - **Doctors** can update any account.
    """
    user_service.require_self_or_doctor(current_user, user_id)
    return user_service.update_user(db, user_id, payload)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user",
    responses={
        403: {"description": "Cannot delete another user's account (patients only)"},
        404: {"description": "User not found"},
    },
)
def delete_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Delete a user account and all related data (cascades to patient/doctor profile).

    - **Patients** can only delete their own account.
    - **Doctors** can delete any account.
    """
    user_service.require_self_or_doctor(current_user, user_id)
    user_service.delete_user(db, user_id)
