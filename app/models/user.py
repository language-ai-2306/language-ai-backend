"""
User — a login account. Could be a patient or a doctor.

IMPORTANT about the password: we NEVER store the real password. We store a
*hash* of it (a scrambled, one-way version). The "at least 8 characters" rule
and the email format check are enforced in the API layer with Pydantic
(see the schemas you'll add later), because those are validation rules about
the *input*, not the storage. The column just holds the resulting hash.
"""

import enum
from datetime import date
from typing import Optional

from sqlalchemy import Date, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AbstractEntity


class UserRole(str, enum.Enum):
    """Which kind of account this is. Decides which profile table holds the
    role-specific data (patient_detail vs doctor)."""

    PATIENT = "PATIENT"
    DOCTOR = "DOCTOR"


class User(AbstractEntity):
    __tablename__ = "user"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)

    # PATIENT or DOCTOR. Set at signup based on which endpoint was used.
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role_enum"),
        nullable=False,
    )

    # Stores the HASHED password, not the plain text. 255 chars fits bcrypt/argon2.
    password: Mapped[str] = mapped_column(String(255), nullable=False)

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)

    dob: Mapped[date] = mapped_column(Date, nullable=False)

    # A single character, e.g. 'M', 'F', 'O'.
    gender: Mapped[str] = mapped_column(String(1), nullable=False)

    # Optional -> nullable=True.
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
