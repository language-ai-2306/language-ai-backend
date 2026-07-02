"""Auth service — signup and login business logic."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.models.ailment import Ailment
from app.models.doctor import Doctor
from app.models.patient import PatientDetail
from app.models.user import User, UserRole
from app.schemas.auth import DoctorSignup, PatientSignup, SignupPayload, Token
from app.services import care_team


def ensure_email_free(db: Session, email: str) -> None:
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )


def signup(db: Session, payload: SignupPayload) -> User:
    ensure_email_free(db, payload.email)

    user = User(
        email=payload.email,
        password=hash_password(payload.password),
        role=UserRole(payload.role),
        first_name=payload.first_name,
        last_name=payload.last_name,
        dob=payload.dob,
        gender=payload.gender,
        phone_number=payload.phone_number,
    )
    db.add(user)
    db.flush()

    if isinstance(payload, PatientSignup):
        patient = PatientDetail(
            user_id=user.id,
            nickname=payload.nickname,
            avatar_id=payload.avatar_id,
            guardian_name=payload.guardian_name,
            guardian_relationship=payload.guardian_relationship,
            guardian_email=payload.guardian_email,
        )
        if payload.ailment_ids:
            patient.ailments = list(
                db.scalars(select(Ailment).where(Ailment.id.in_(payload.ailment_ids))).all()
            )
        db.add(patient)

        # Optional: request a doctor during signup. commit=False so the account
        # and the request commit together; an invalid doctor_id raises 404 and
        # the whole signup rolls back.
        if payload.doctor_id is not None:
            db.flush()  # assign patient.id before creating the request
            care_team.create_request(db, patient, payload.doctor_id, commit=False)
    else:
        assert isinstance(payload, DoctorSignup)
        db.add(Doctor(
            user_id=user.id,
            qualification=payload.qualification,
            bio=payload.bio,
            address=payload.address,
            photo_url=payload.photo_url,
        ))

    db.commit()
    db.refresh(user)
    return user


def login(db: Session, username: str, password: str) -> Token:
    user = db.scalar(select(User).where(User.email == username))
    if user is None or not verify_password(password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(subject=user.id))
