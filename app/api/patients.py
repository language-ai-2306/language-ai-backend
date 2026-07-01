"""Doctor-facing patient management: pending requests, approve/reject, and the
approved-patients list.

These live on two different path prefixes (`/patient/...` and `/v1/patient`), so
this router is declared without a prefix and each route sets its full path.
"""

from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_doctor
from app.db.base import get_db
from app.models.doctor import Doctor
from app.schemas.care_team import (
    PatientPage,
    RequestAction,
    RequestActionResponse,
    RequestListItem,
)
from app.services import care_team

router = APIRouter(tags=["patients"])


@router.get(
    "/patient/request",
    response_model=List[RequestListItem],
    summary="List this doctor's pending patient requests",
)
def list_requests(
    db: Session = Depends(get_db),
    doctor: Doctor = Depends(get_current_doctor),
) -> List[RequestListItem]:
    """All PENDING requests addressed to the logged-in doctor, newest first."""
    return care_team.list_pending_requests(db, doctor)


@router.post(
    "/patient/request",
    response_model=RequestActionResponse,
    summary="Approve or reject a patient request",
    responses={
        404: {"description": "Request not found (or not addressed to you)"},
        409: {"description": "Request already responded to"},
    },
)
def respond_to_request(
    payload: RequestAction,
    db: Session = Depends(get_db),
    doctor: Doctor = Depends(get_current_doctor),
) -> RequestActionResponse:
    """Approve (links the patient) or reject a pending request. Action is in the body."""
    if payload.action == "APPROVE":
        req = care_team.approve_request(db, doctor, payload.request_id)
    else:
        req = care_team.reject_request(db, doctor, payload.request_id)
    return RequestActionResponse(
        request_id=req.id, status=req.status.value, responded_at=req.responded_at
    )


@router.get(
    "/v1/patient",
    response_model=PatientPage,
    summary="List this doctor's approved patients (paginated)",
)
def list_patients(
    page: int = Query(default=1, ge=1, description="1-indexed page number"),
    size: int = Query(default=10, ge=1, le=50, description="Items per page (max 50)"),
    db: Session = Depends(get_db),
    doctor: Doctor = Depends(get_current_doctor),
) -> PatientPage:
    """The doctor's confirmed (approved) patients."""
    return care_team.list_doctor_patients(db, doctor, page, size)
