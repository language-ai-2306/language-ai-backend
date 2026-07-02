"""
Schemas for signup and login.

Single signup schema using a discriminated union on `role`:
  role="PATIENT" → validates patient-specific fields (nickname, avatar, ailments)
  role="DOCTOR"  → validates doctor-specific fields (qualification, bio, ...)

Both branches share the common account fields from UserBase.
"""

import uuid
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from app.schemas.user import UserBase


class PatientSignup(UserBase):
    role: Literal["PATIENT"]
    password: str = Field(min_length=8, max_length=128)
    nickname: str = Field(min_length=1, max_length=100)
    avatar_id: Optional[int] = None
    ailment_ids: List[int] = Field(default_factory=list)
    # Optional: request a doctor during signup (doctor's user GUID). Creates a PENDING
    # link request (the doctor must still approve). Invalid guid → 404, signup rolls back.
    doctor_id: Optional[uuid.UUID] = None
    # Guardian details — required by the UI for minors; optional here.
    guardian_name: Optional[str] = Field(default=None, max_length=100)
    guardian_relationship: Optional[str] = Field(default=None, max_length=32)
    guardian_email: Optional[str] = Field(default=None, max_length=320)


class DoctorSignup(UserBase):
    role: Literal["DOCTOR"]
    password: str = Field(min_length=8, max_length=128)
    qualification: str = Field(min_length=1, max_length=255)
    bio: str = Field(min_length=1)
    address: Optional[str] = Field(default=None, max_length=500)
    photo_url: Optional[str] = Field(default=None, max_length=500)


SignupPayload = Annotated[
    Union[PatientSignup, DoctorSignup],
    Field(discriminator="role"),
]


class Token(BaseModel):
    """What the login endpoint returns."""

    access_token: str
    token_type: str = "bearer"
