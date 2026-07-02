"""Doctor-facing tailored-plan routes — build and review a patient's treatment course.

All ids in paths / query / body are GUIDs (plan_id, item_id, patient_id).
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_doctor
from app.db.base import get_db
from app.models.doctor import Doctor
from app.models.practice_plan import PlanStatus
from app.schemas.practice_plan import (
    PlanCreate,
    PlanItemCreate,
    PlanItemRead,
    PlanItemUpdate,
    PlanListItem,
    PlanProgressResponse,
    PlanRead,
    PlanUpdate,
)
from app.services import practice_plan as service

router = APIRouter(prefix="/v1/plans", tags=["plans"])


@router.post("", response_model=PlanRead, status_code=status.HTTP_201_CREATED,
             summary="Create a tailored plan for a patient")
def create_plan(
    payload: PlanCreate,
    db: Session = Depends(get_db),
    doctor: Doctor = Depends(get_current_doctor),
):
    return service.create_plan(db, doctor, payload)


@router.get("", response_model=List[PlanListItem], summary="List a patient's plans")
def list_plans(
    patient_id: Optional[uuid.UUID] = Query(default=None, description="patient user GUID"),
    status_filter: Optional[PlanStatus] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    doctor: Doctor = Depends(get_current_doctor),
):
    return service.list_plans(db, doctor, patient_id, status_filter)


@router.get("/{plan_id}", response_model=PlanRead, summary="Get a plan with its items")
def get_plan(plan_id: uuid.UUID, db: Session = Depends(get_db), doctor: Doctor = Depends(get_current_doctor)):
    return service.get_plan(db, doctor, plan_id)


@router.patch("/{plan_id}", response_model=PlanRead, summary="Update a plan (status, dates, title)")
def update_plan(
    plan_id: uuid.UUID,
    payload: PlanUpdate,
    db: Session = Depends(get_db),
    doctor: Doctor = Depends(get_current_doctor),
):
    return service.update_plan(db, doctor, plan_id, payload)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a plan (and its items + attempt history)")
def delete_plan(
    plan_id: uuid.UUID,
    db: Session = Depends(get_db),
    doctor: Doctor = Depends(get_current_doctor),
):
    service.delete_plan(db, doctor, plan_id)


@router.post("/{plan_id}/items", response_model=PlanItemRead, status_code=status.HTTP_201_CREATED,
             summary="Add an exercise to a plan")
def add_item(
    plan_id: uuid.UUID,
    payload: PlanItemCreate,
    db: Session = Depends(get_db),
    doctor: Doctor = Depends(get_current_doctor),
):
    return service.add_item(db, doctor, plan_id, payload)


@router.patch("/{plan_id}/items/{item_id}", response_model=PlanItemRead,
              summary="Edit / advance / hold a plan item")
def update_item(
    plan_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: PlanItemUpdate,
    db: Session = Depends(get_db),
    doctor: Doctor = Depends(get_current_doctor),
):
    return service.update_item(db, doctor, plan_id, item_id, payload)


@router.delete("/{plan_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Remove a plan item")
def delete_item(
    plan_id: uuid.UUID,
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    doctor: Doctor = Depends(get_current_doctor),
):
    service.delete_item(db, doctor, plan_id, item_id)


@router.get("/{plan_id}/progress", response_model=PlanProgressResponse,
            summary="Review a plan's progress per item")
def get_progress(plan_id: uuid.UUID, db: Session = Depends(get_db), doctor: Doctor = Depends(get_current_doctor)):
    return service.get_progress(db, doctor, plan_id)
