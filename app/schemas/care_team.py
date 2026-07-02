"""Schemas for the care-team (patient↔doctor linking) endpoints.

Public API speaks GUIDs: doctor_id / patient_id are user GUIDs, request_id is the
request's GUID. Items are built from JOINed rows in the service (dicts validated here).
"""

import uuid
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel


# --- Doctor directory (#1) ----------------------------------------------------
class DoctorListItem(BaseModel):
    doctor_id: uuid.UUID     # user GUID of the doctor
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
    patient_id: uuid.UUID    # user GUID of the patient
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
    request_id: uuid.UUID
    patient_id: uuid.UUID    # user GUID of the patient
    first_name: str
    last_name: str
    nickname: str
    requested_at: datetime


# --- Create a request (#5 / signup) ------------------------------------------
class RequestCreateResponse(BaseModel):
    request_id: uuid.UUID
    doctor_id: uuid.UUID     # user GUID of the doctor
    status: str


# --- Approve / reject (#4) ----------------------------------------------------
class RequestAction(BaseModel):
    request_id: uuid.UUID
    action: Literal["APPROVE", "REJECT"]


class RequestActionResponse(BaseModel):
    request_id: uuid.UUID
    status: str
    responded_at: Optional[datetime] = None
