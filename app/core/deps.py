"""
FastAPI dependencies for authentication.

`get_current_user` is the gatekeeper: put it on any endpoint and FastAPI will
require a valid `Authorization: Bearer <token>` header, decode it, load the
matching User from the database, and hand it to your function. If anything is
wrong it raises 401 Unauthorized automatically.

`require_role(...)` builds a dependency that additionally checks the user is a
patient or a doctor — use it to protect role-specific endpoints.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.base import get_db
from app.models.user import User, UserRole

# tokenUrl points at the login endpoint; it tells the interactive API docs
# (/docs) where to get a token so you can click "Authorize" and try things.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user_id = decode_access_token(token)
    if user_id is None:
        raise credentials_error

    user = db.get(User, user_id)
    if user is None:
        raise credentials_error
    return user


def require_role(*allowed_roles: UserRole):
    """Build a dependency that allows only the given role(s)."""

    def _checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return _checker
