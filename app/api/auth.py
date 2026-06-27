"""Auth routes — thin controller, delegates to AuthService."""

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.schemas.auth import SignupPayload, Token
from app.schemas.user import UserRead
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/signup",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
    response_description="The newly created user account",
    responses={409: {"description": "Email already registered"}},
)
def signup(payload: SignupPayload, db: Session = Depends(get_db)) -> User:
    """
    Create a patient or doctor account in a single request.

    Set **`role`** to choose the account type:
    - `PATIENT` — requires `nickname`; optionally `avatar_id` and `ailment_ids`
    - `DOCTOR` — requires `qualification` and `bio`
    """
    return auth_service.signup(db, payload)


@router.post(
    "/login",
    response_model=Token,
    summary="Log in and get a Bearer token",
    response_description="JWT access token (valid for the configured TTL)",
    responses={401: {"description": "Incorrect email or password"}},
)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    """
    Authenticate with **email + password** (form-encoded).

    Returns a Bearer token — use it in the `Authorization: Bearer <token>` header
    on all protected endpoints. In Swagger UI, click **Authorize** and paste the token.

    > Note: the `username` field takes the email address (OAuth2 standard).
    """
    return auth_service.login(db, form_data.username, form_data.password)


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get the current user",
    response_description="The logged-in user's account details",
    responses={401: {"description": "Missing or invalid token"}},
)
def read_me(current_user: User = Depends(get_current_user)) -> User:
    """Return the account of the currently authenticated user."""
    return current_user
