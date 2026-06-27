"""User service — all user CRUD business logic."""

from typing import List

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.schemas.user import UserUpdate


def get_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def require_self_or_doctor(current_user: User, target_id: int) -> None:
    if current_user.id != target_id and current_user.role != UserRole.DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only modify your own account",
        )


def list_users(db: Session, skip: int, limit: int) -> List[User]:
    return list(db.scalars(select(User).offset(skip).limit(limit)).all())


def update_user(db: Session, user_id: int, payload: UserUpdate) -> User:
    user = get_or_404(db, user_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: int) -> None:
    user = get_or_404(db, user_id)
    db.delete(user)
    db.commit()
