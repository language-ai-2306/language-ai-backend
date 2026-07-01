"""Care-team service — patient↔doctor linking (request / approve / reject).

The confirmed link lives on `PatientDetail.doctor_id` (unchanged). This service
manages the PENDING→APPROVED/REJECTED workflow in `patient_doctor_request` and,
on approval, sets that column in the same transaction.

Functions take a `db: Session` and raise HTTPException on rule violations, so the
routers stay thin.
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.doctor import Doctor
from app.models.patient import PatientDetail
from app.models.patient_doctor_request import PatientDoctorRequest, RequestStatus
from app.models.user import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp_page(page: int, size: int) -> tuple[int, int, int]:
    """Return (page, size, offset) with sane bounds (size capped at 50)."""
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
            "doctor_id": d.id,
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
    doctor_id: int,
    *,
    commit: bool = True,
) -> PatientDoctorRequest:
    """Create (or re-open) a PENDING request from a patient to a doctor.

    commit=True for the standalone endpoint; commit=False when called inside
    /auth/signup so the account + request share one transaction.
    """
    if db.get(Doctor, doctor_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found")

    # Rule 1: one doctor per patient — block if already linked.
    if patient_detail.doctor_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You are already linked to a doctor")

    # Rules 1/2: block a second pending request (to any doctor).
    pending = db.scalar(
        select(PatientDoctorRequest).where(
            PatientDoctorRequest.patient_detail_id == patient_detail.id,
            PatientDoctorRequest.status == RequestStatus.PENDING,
        )
    )
    if pending is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have a pending request")

    # Re-use a prior row for this exact pair (unique constraint) — e.g. a
    # previously REJECTED request being sent again.
    req = db.scalar(
        select(PatientDoctorRequest).where(
            PatientDoctorRequest.patient_detail_id == patient_detail.id,
            PatientDoctorRequest.doctor_id == doctor_id,
        )
    )
    if req is not None:
        req.status = RequestStatus.PENDING
        req.responded_at = None
    else:
        req = PatientDoctorRequest(
            patient_detail_id=patient_detail.id,
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
        select(func.count()).select_from(PatientDetail).where(PatientDetail.doctor_id == doctor.id)
    ) or 0
    rows = db.execute(
        select(PatientDetail, User)
        .join(User, PatientDetail.user_id == User.id)
        .where(PatientDetail.doctor_id == doctor.id)
        .order_by(PatientDetail.id)
        .offset(offset)
        .limit(size)
    ).all()
    items = [
        {
            "patient_id": p.id,
            "user_id": u.id,
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
        select(PatientDoctorRequest, PatientDetail, User)
        .join(PatientDetail, PatientDoctorRequest.patient_detail_id == PatientDetail.id)
        .join(User, PatientDetail.user_id == User.id)
        .where(
            PatientDoctorRequest.doctor_id == doctor.id,
            PatientDoctorRequest.status == RequestStatus.PENDING,
        )
        .order_by(PatientDoctorRequest.created_at.desc())
    ).all()
    return [
        {
            "request_id": r.id,
            "patient_id": p.id,
            "user_id": u.id,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "nickname": p.nickname,
            "requested_at": r.created_at,
        }
        for r, p, u in rows
    ]


# --- #4 approve / reject ------------------------------------------------------
def _owned_pending(db: Session, doctor: Doctor, request_id: int) -> PatientDoctorRequest:
    req = db.get(PatientDoctorRequest, request_id)
    # 404 (not 403) when it isn't this doctor's request — don't reveal others exist.
    if req is None or req.doctor_id != doctor.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    if req.status != RequestStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Request has already been responded to")
    return req


def approve_request(db: Session, doctor: Doctor, request_id: int) -> PatientDoctorRequest:
    req = _owned_pending(db, doctor, request_id)
    patient = db.get(PatientDetail, req.patient_detail_id)

    req.status = RequestStatus.APPROVED
    req.responded_at = _now()
    patient.doctor_id = doctor.id  # the confirmed 1:1 link

    # One doctor per patient → auto-reject any other pending requests they made.
    others = db.scalars(
        select(PatientDoctorRequest).where(
            PatientDoctorRequest.patient_detail_id == req.patient_detail_id,
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


def reject_request(db: Session, doctor: Doctor, request_id: int) -> PatientDoctorRequest:
    req = _owned_pending(db, doctor, request_id)
    req.status = RequestStatus.REJECTED
    req.responded_at = _now()
    db.commit()
    db.refresh(req)
    return req
