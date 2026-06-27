"""
Schemas for signup and login.

Two SEPARATE signup schemas (your chosen design): a patient signup carries
patient-only fields (nickname, avatar, ailments); a doctor signup carries
doctor-only fields (qualification, bio, ...). Both extend UserBase so they
share the common account fields, and both add the password with the >= 8 rule.
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.user import UserBase


class PatientSignup(UserBase):
    password: str = Field(min_length=8, max_length=128)
    nickname: str = Field(min_length=1, max_length=100)
    avatar_id: Optional[int] = None
    # The ailment ids this patient practices (many-to-many). Optional at signup.
    ailment_ids: List[int] = Field(default_factory=list)


class DoctorSignup(UserBase):
    password: str = Field(min_length=8, max_length=128)
    qualification: str = Field(min_length=1, max_length=255)
    bio: str = Field(min_length=1)
    address: Optional[str] = Field(default=None, max_length=500)
    photo_url: Optional[str] = Field(default=None, max_length=500)


class Token(BaseModel):
    """What the login endpoint returns."""

    access_token: str
    token_type: str = "bearer"
