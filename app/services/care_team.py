"""Care-team service — patient↔doctor linking (request / approve / reject).

Every person is referenced by their `user.id`. `patient_doctor_request.patient_id`
and `.doctor_id`, and the confirmed link `PatientDetail.doctor_id`, are all user ids.
`doctor` args below are Doctor (doctor_details) rows resolved by `get_current_doctor`;
we compare against `doctor.user_id`.
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.guid import get_by_guid
from app.models.doctor import Doctor
from app.models.patient import PatientDetail
from app.models.patient_doctor_request import PatientDoctorRequest, RequestStatus
from app.models.user import User, UserRole


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp_page(page: int, size: int) -> tuple[int, int, int]:
    page = max(page, 1)
    size = min(max(size, 1), 50)
    return page, size, (page - 1) * size


def _page(items: list[dict[str, Any]], page: int, size: int, total: int) -> dict[str, Any]:
    total_pages = (total + size - 1) // size if size else 0
    return {"items": items, "page": page, "size": size, "total": total, "total_pages": total_pages}


# --- #1 doctor directory ------------------------------------------------------
def list_doctors(db: Session, page: int = 1, size: int = 10) -> dict[str, Any]:
    page, size, offset = _clamp_page(page, size)
    total = db.scalar(select(func.count()).select_from(Doctor)) or 0
    rows = db.execute(
        select(Doctor, User)
        .join(User, Doctor.user_id == User.id)
        .order_by(Doctor.id)
        .offset(offset)
        .limit(size)
    ).all()
    items = [
        {
            "doctor_id": u.guid,  # user GUID of the doctor
            "first_name": u.first_name,
            "last_name": u.last_name,
            "qualification": d.qualification,
            "bio": d.bio,
            "photo_url": d.photo_url,
        }
        for d, u in rows
    ]
    return _page(items, page, size, int(total))


# --- #5 / signup: create a request --------------------------------------------
def create_request(
    db: Session,
    patient_detail: PatientDetail,
    doctor_guid,  # the doctor's user GUID
    *,
    commit: bool = True,
) -> PatientDoctorRequest:
    """Create (or re-open) a PENDING request from a patient to a doctor.

    commit=True for the standalone endpoint; commit=False when called inside
    /auth/signup so the account + request share one transaction.
    """
    patient_user_id = patient_detail.user_id

    doctor_user = get_by_guid(db, User, doctor_guid)
    if doctor_user is None or doctor_user.role != UserRole.DOCTOR:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found")
    doctor_id = doctor_user.id  # internal user.id

    # Rule 1: one doctor per patient — block if already linked.
    if patient_detail.doctor_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You are already linked to a doctor")

    # Rule 2: block a second pending request (to any doctor).
    pending = db.scalar(
        select(PatientDoctorRequest).where(
            PatientDoctorRequest.patient_id == patient_user_id,
            PatientDoctorRequest.status == RequestStatus.PENDING,
        )
    )
    if pending is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have a pending request")

    # Re-use a prior row for this exact pair (a previously REJECTED request resent).
    req = db.scalar(
        select(PatientDoctorRequest).where(
            PatientDoctorRequest.patient_id == patient_user_id,
            PatientDoctorRequest.doctor_id == doctor_id,
        )
    )
    if req is not None:
        req.status = RequestStatus.PENDING
        req.responded_at = None
    else:
        req = PatientDoctorRequest(
            patient_id=patient_user_id,
            doctor_id=doctor_id,
            status=RequestStatus.PENDING,
        )
        db.add(req)

    if commit:
        db.commit()
        db.refresh(req)
    else:
        db.flush()
    return req


# --- #2 approved patients -----------------------------------------------------
def list_doctor_patients(db: Session, doctor: Doctor, page: int = 1, size: int = 10) -> dict[str, Any]:
    page, size, offset = _clamp_page(page, size)
    total = db.scalar(
        select(func.count()).select_from(PatientDetail).where(PatientDetail.doctor_id == doctor.user_id)
    ) or 0
    rows = db.execute(
        select(PatientDetail, User)
        .join(User, PatientDetail.user_id == User.id)
        .where(PatientDetail.doctor_id == doctor.user_id)
        .order_by(PatientDetail.id)
        .offset(offset)
        .limit(size)
    ).all()
    items = [
        {
            "patient_id": u.guid,  # user GUID of the patient
            "first_name": u.first_name,
            "last_name": u.last_name,
            "nickname": p.nickname,
        }
        for p, u in rows
    ]
    return _page(items, page, size, int(total))


# --- #3 pending requests ------------------------------------------------------
def list_pending_requests(db: Session, doctor: Doctor) -> list[dict[str, Any]]:
    rows = db.execute(
        select(PatientDoctorRequest, User, PatientDetail)
        .join(User, PatientDoctorRequest.patient_id == User.id)
        .join(PatientDetail, PatientDetail.user_id == User.id)
        .where(
            PatientDoctorRequest.doctor_id == doctor.user_id,
            PatientDoctorRequest.status == RequestStatus.PENDING,
        )
        .order_by(PatientDoctorRequest.created_at.desc())
    ).all()
    return [
        {
            "request_id": r.guid,
            "patient_id": u.guid,  # user GUID of the patient
            "first_name": u.first_name,
            "last_name": u.last_name,
            "nickname": p.nickname,
            "requested_at": r.created_at,
        }
        for r, u, p in rows
    ]


# --- #4 approve / reject ------------------------------------------------------
def _owned_pending(db: Session, doctor: Doctor, request_guid) -> PatientDoctorRequest:
    req = get_by_guid(db, PatientDoctorRequest, request_guid)
    # 404 (not 403) when it isn't this doctor's request — don't reveal others exist.
    if req is None or req.doctor_id != doctor.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    if req.status != RequestStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Request has already been responded to")
    return req


def approve_request(db: Session, doctor: Doctor, request_guid) -> PatientDoctorRequest:
    req = _owned_pending(db, doctor, request_guid)
    patient = db.scalar(select(PatientDetail).where(PatientDetail.user_id == req.patient_id))

    req.status = RequestStatus.APPROVED
    req.responded_at = _now()
    if patient is not None:
        patient.doctor_id = doctor.user_id  # confirmed link (doctor's user.id)

    # One doctor per patient → auto-reject the patient's other pending requests.
    others = db.scalars(
        select(PatientDoctorRequest).where(
            PatientDoctorRequest.patient_id == req.patient_id,
            PatientDoctorRequest.id != req.id,
            PatientDoctorRequest.status == RequestStatus.PENDING,
        )
    ).all()
    for other in others:
        other.status = RequestStatus.REJECTED
        other.responded_at = _now()

    db.commit()
    db.refresh(req)
    return req


def reject_request(db: Session, doctor: Doctor, request_guid) -> PatientDoctorRequest:
    req = _owned_pending(db, doctor, request_guid)
    req.status = RequestStatus.REJECTED
    req.responded_at = _now()
    db.commit()
    db.refresh(req)
    return req
