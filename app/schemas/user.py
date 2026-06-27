"""
Pydantic schemas for users.

Schemas are the SHAPE of data going in and out of the API. FastAPI uses them to:
  * validate incoming JSON (reject bad emails, short passwords, etc.) BEFORE
    your code runs, returning a clear 422 error automatically;
  * serialize database objects into safe JSON going out (note UserRead has NO
    password field, so the hash is never leaked).

`EmailStr` enforces a valid email format. `Field(min_length=8)` enforces the
password rule. These are exactly the "specific format" / "at least 8 chars"
rules from your table design — enforced here, at the edge.
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserBase(BaseModel):
    """Fields shared by both patients and doctors (the common account info)."""

    email: EmailStr
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    dob: date
    gender: str = Field(min_length=1, max_length=1)  # 'M', 'F', 'O'
    phone_number: Optional[str] = Field(default=None, max_length=20)


class UserRead(BaseModel):
    """What we send BACK about a user. No password, ever."""

    model_config = ConfigDict(from_attributes=True)  # allow building from a DB object

    id: int
    email: EmailStr
    role: UserRole
    first_name: str
    last_name: str
    dob: date
    gender: str
    phone_number: Optional[str]
    created_at: datetime


class UserUpdate(BaseModel):
    """Fields a user is allowed to change. All optional — only send what changes."""

    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    dob: Optional[date] = None
    gender: Optional[str] = Field(default=None, min_length=1, max_length=1)
    phone_number: Optional[str] = Field(default=None, max_length=20)
