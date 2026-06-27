"""
User CRUD routes.

Create is handled by the signup endpoints in auth.py (because creating a user
also creates a patient/doctor profile). This file covers Read, Update, Delete.

Permission rule used here (simple and safe): you can always act on YOUR OWN
account; doctors may additionally read/modify others. Adjust as your product
needs grow.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.base import get_db
from app.models.user import User, UserRole
from app.schemas.user import UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _require_self_or_doctor(current_user: User, target_id: int) -> None:
    if current_user.id != target_id and current_user.role != UserRole.DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only modify your own account",
        )


@router.get("", response_model=List[UserRead])
def list_users(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[User]:
    """List users (paginated). Requires being logged in."""
    return list(db.scalars(select(User).offset(skip).limit(limit)).all())


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    return _get_user_or_404(db, user_id)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    _require_self_or_doctor(current_user, user_id)
    user = _get_user_or_404(db, user_id)

    # Apply only the fields that were actually sent (exclude_unset).
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    _require_self_or_doctor(current_user, user_id)
    user = _get_user_or_404(db, user_id)
    # Deleting the user cascades to patient_detail/doctor via ondelete=CASCADE.
    db.delete(user)
    db.commit()
