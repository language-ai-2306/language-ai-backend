"""Schemas for the care-team (patient↔doctor linking) endpoints.

Items are built from JOINed rows in the service (not straight ORM objects), so
these are plain field models — the service passes dicts that Pydantic validates.
"""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel


# --- Doctor directory (#1) ----------------------------------------------------
class DoctorListItem(BaseModel):
    doctor_id: int
    first_name: str
    last_name: str
    qualification: str
    bio: str
    photo_url: Optional[str] = None


class DoctorPage(BaseModel):
    items: List[DoctorListItem]
    page: int
    size: int
    total: int
    total_pages: int


# --- Approved patients (#2) ---------------------------------------------------
class PatientListItem(BaseModel):
    patient_id: int          # PatientDetail.id
    user_id: int             # User.id — the id every other feature keys on
    first_name: str
    last_name: str
    nickname: str


class PatientPage(BaseModel):
    items: List[PatientListItem]
    page: int
    size: int
    total: int
    total_pages: int


# --- Pending requests (#3) ----------------------------------------------------
class RequestListItem(BaseModel):
    request_id: int
    patient_id: int
    user_id: int
    first_name: str
    last_name: str
    nickname: str
    requested_at: datetime


# --- Create a request (#5 / signup) ------------------------------------------
class RequestCreateResponse(BaseModel):
    request_id: int
    doctor_id: int
    status: str


# --- Approve / reject (#4) ----------------------------------------------------
class RequestAction(BaseModel):
    request_id: int
    action: Literal["APPROVE", "REJECT"]


class RequestActionResponse(BaseModel):
    request_id: int
    status: str
    responded_at: Optional[datetime] = None
