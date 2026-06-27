"""
Authentication routes: signup (patient / doctor), login, and "who am I".

Signup is split into two endpoints because patients and doctors carry different
extra fields. Both create ONE user_account row (the shared login identity) plus
ONE profile row (patient_detail or doctor) in a single database transaction —
so a half-made account can never exist.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.base import get_db
from app.models.ailment import Ailment
from app.models.doctor import Doctor
from app.models.patient import PatientDetail
from app.models.user import User, UserRole
from app.schemas.auth import DoctorSignup, PatientSignup, Token
from app.schemas.user import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


def _ensure_email_free(db: Session, email: str) -> None:
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )


@router.post("/signup/patient", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def signup_patient(payload: PatientSignup, db: Session = Depends(get_db)) -> User:
    _ensure_email_free(db, payload.email)

    user = User(
        email=payload.email,
        password=hash_password(payload.password),  # store the HASH, never the plain text
        role=UserRole.PATIENT,
        first_name=payload.first_name,
        last_name=payload.last_name,
        dob=payload.dob,
        gender=payload.gender,
        phone_number=payload.phone_number,
    )
    db.add(user)
    db.flush()  # assigns user.id without committing yet

    patient = PatientDetail(
        user_id=user.id,
        nickname=payload.nickname,
        avatar_id=payload.avatar_id,
    )
    # Link the chosen ailments (skip any ids that don't exist).
    if payload.ailment_ids:
        patient.ailments = list(
            db.scalars(select(Ailment).where(Ailment.id.in_(payload.ailment_ids))).all()
        )
    db.add(patient)

    db.commit()
    db.refresh(user)
    return user


@router.post("/signup/doctor", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def signup_doctor(payload: DoctorSignup, db: Session = Depends(get_db)) -> User:
    _ensure_email_free(db, payload.email)

    user = User(
        email=payload.email,
        password=hash_password(payload.password),
        role=UserRole.DOCTOR,
        first_name=payload.first_name,
        last_name=payload.last_name,
        dob=payload.dob,
        gender=payload.gender,
        phone_number=payload.phone_number,
    )
    db.add(user)
    db.flush()

    doctor = Doctor(
        user_id=user.id,
        qualification=payload.qualification,
        bio=payload.bio,
        address=payload.address,
        photo_url=payload.photo_url,
    )
    db.add(doctor)

    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    """
    Validate email + password and return a bearer token.

    Uses OAuth2PasswordRequestForm, so the request is a FORM with fields
    `username` (put the email here) and `password`. This is what makes the
    "Authorize" button in /docs work out of the box.
    """
    user = db.scalar(select(User).where(User.email == form_data.username))
    if user is None or not verify_password(form_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(subject=user.id)
    return Token(access_token=token)


@router.get("/me", response_model=UserRead)
def read_me(current_user: User = Depends(get_current_user)) -> User:
    """Return the currently logged-in user (proves the token works)."""
    return current_user
