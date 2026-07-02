"""SLP dashboard API — doctor-facing analytics over patients, plans and attempts.

Three tiers:
  GET /v1/doctor/patients                       — caseload overview (triage)
  GET /v1/doctor/patients/{patient_id}          — one patient's full analytics
  GET /v1/doctor/patients/{patient_id}/attempts — that patient's attempts (paged)
  GET /v1/doctor/attempts/{attempt_id}          — a single attempt (clinical review)

All ids are GUIDs. Every route requires a doctor and only exposes that doctor's
linked patients.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_doctor
from app.db.base import get_db
from app.models.doctor import Doctor
from app.schemas.slp import (
    AttemptDetail,
    AttemptListResponse,
    CaseloadResponse,
    PatientDetailResponse,
)
from app.services import slp_dashboard as service

router = APIRouter(prefix="/v1/doctor", tags=["doctor-dashboard"])


@router.get("/patients", response_model=CaseloadResponse,
            summary="Caseload overview — every linked patient with triage metrics")
def caseload(db: Session = Depends(get_db), doctor: Doctor = Depends(get_current_doctor)):
    return service.get_caseload(db, doctor)


@router.get("/patients/{patient_id}", response_model=PatientDetailResponse,
            summary="One patient's full dashboard (metrics, trends, adherence, sounds)")
def patient_detail(patient_id: uuid.UUID, db: Session = Depends(get_db),
                   doctor: Doctor = Depends(get_current_doctor)):
    return service.get_patient_detail(db, doctor, patient_id)


@router.get("/patients/{patient_id}/attempts", response_model=AttemptListResponse,
            summary="A patient's attempts, newest first (paged)")
def patient_attempts(
    patient_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    doctor: Doctor = Depends(get_current_doctor),
):
    return service.list_attempts(db, doctor, patient_id, limit, offset)


@router.get("/attempts/{attempt_id}", response_model=AttemptDetail,
            summary="A single attempt — transcript, disfluency events, scores, audio")
def attempt_detail(attempt_id: uuid.UUID, db: Session = Depends(get_db),
                   doctor: Doctor = Depends(get_current_doctor)):
    return service.get_attempt(db, doctor, attempt_id)
