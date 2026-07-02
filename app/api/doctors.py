"""Doctor directory + patient's request-a-doctor routes (patient-facing).

`doctor_id` (path) and all response ids are GUIDs.
"""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_patient, get_current_user
from app.db.base import get_db
from app.models.patient import PatientDetail
from app.models.user import User
from app.schemas.care_team import DoctorPage, RequestCreateResponse
from app.services import care_team

router = APIRouter(prefix="/doctors", tags=["doctors"])


@router.get(
    "",
    response_model=DoctorPage,
    summary="List doctors (paginated, 10 per page)",
    response_description="A page of doctors the patient can request",
)
def list_doctors(
    page: int = Query(default=1, ge=1, description="1-indexed page number"),
    size: int = Query(default=10, ge=1, le=50, description="Items per page (max 50)"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DoctorPage:
    """Browse the doctor directory. Available to any authenticated user."""
    return care_team.list_doctors(db, page, size)


@router.post(
    "/{doctor_id}/request",
    response_model=RequestCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request to be linked to a doctor",
    responses={
        404: {"description": "Doctor not found"},
        409: {"description": "Already linked to a doctor, or a pending request exists"},
    },
)
def request_doctor(
    doctor_id: uuid.UUID,
    db: Session = Depends(get_db),
    patient: PatientDetail = Depends(get_current_patient),
) -> RequestCreateResponse:
    """Send a link request to a doctor. Stays PENDING until the doctor approves."""
    req = care_team.create_request(db, patient, doctor_id)
    # doctor_id echoes the requested doctor GUID; request_id is the request's GUID.
    return RequestCreateResponse(request_id=req.guid, doctor_id=doctor_id, status=req.status.value)
