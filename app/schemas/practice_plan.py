"""Schemas for tailored practice plans (doctor-authored treatment courses).

Public API speaks GUIDs: every id field (plan_id, item_id, patient_id, doctor_id)
is a UUID. Integer ids stay internal.
"""

import uuid
from datetime import date, datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from app.models.disfluency import Difficulty
from app.models.practice_plan import PlanItemStatus, PlanStatus


# --- create / update ----------------------------------------------------------
class PlanItemCreate(BaseModel):
    exercise_type: str
    target_phoneme: Optional[str] = Field(default=None, max_length=16)  # RAM / READ_IT_LOUD only
    difficulty: Optional[Difficulty] = None                             # required except TALK_WITH_OLLIE
    sequence: int = 0
    # Scheduling
    frequency: str = "DAILY"                    # DAILY / WEEKLY / MONTHLY / CUSTOM
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=120)
    # {"days_of_week": ["MON","WED"], "days_of_month": [1, 15]}
    schedule: dict[str, Any] = Field(default_factory=dict)
    dosage: dict[str, Any] = Field(default_factory=dict)
    advancement: dict[str, Any] = Field(default_factory=dict)


class PlanCreate(BaseModel):
    patient_id: uuid.UUID  # patient user's GUID (from GET /v1/patient)
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    status: PlanStatus = PlanStatus.DRAFT
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    items: List[PlanItemCreate] = Field(default_factory=list)


class PlanUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    status: Optional[PlanStatus] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class PlanItemUpdate(BaseModel):
    target_phoneme: Optional[str] = Field(default=None, max_length=16)
    difficulty: Optional[Difficulty] = None
    sequence: Optional[int] = None
    frequency: Optional[str] = None
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=120)
    schedule: Optional[dict[str, Any]] = None
    dosage: Optional[dict[str, Any]] = None
    advancement: Optional[dict[str, Any]] = None
    status: Optional[PlanItemStatus] = None


# --- read (all ids are GUIDs) -------------------------------------------------
class PlanItemRead(BaseModel):
    item_id: uuid.UUID
    sequence: int
    exercise_type: str
    target_phoneme: Optional[str] = None
    difficulty: Optional[Difficulty] = None
    frequency: str
    duration_minutes: Optional[int] = None
    schedule: dict[str, Any]
    dosage: dict[str, Any]
    advancement: dict[str, Any]
    status: PlanItemStatus


class PlanRead(BaseModel):
    plan_id: uuid.UUID
    patient_id: uuid.UUID              # patient user's GUID
    doctor_id: Optional[uuid.UUID] = None  # doctor user's GUID
    title: str
    description: Optional[str] = None
    status: PlanStatus
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    items: List[PlanItemRead]


class PlanListItem(BaseModel):
    plan_id: uuid.UUID
    title: str
    status: PlanStatus
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    item_count: int
    items: List[PlanItemRead]


# --- patient: my plan ---------------------------------------------------------
class MyPlanItem(BaseModel):
    item_id: uuid.UUID
    plan_id: uuid.UUID          # which (active) plan this item belongs to
    plan_title: str
    exercise_type: str
    target_phoneme: Optional[str] = None
    difficulty: Optional[Difficulty] = None
    frequency: str
    duration_minutes: Optional[int] = None
    dosage: dict[str, Any]
    status: PlanItemStatus
    attempts_today: int
    due: bool


class MyPlanResponse(BaseModel):
    # Items aggregated across ALL of the patient's active plans.
    items: List[MyPlanItem] = Field(default_factory=list)


class DashboardWeekItem(BaseModel):
    item_id: uuid.UUID
    plan_id: uuid.UUID
    plan_title: str
    exercise_type: str
    target_phoneme: Optional[str] = None
    difficulty: Optional[Difficulty] = None
    frequency: str
    duration_minutes: Optional[int] = None
    # Weekdays this week the item runs, e.g. ["MON","WED"].
    scheduled_days: List[str]


class PatientDashboardResponse(BaseModel):
    # Aggregated across ALL of the patient's active plans.
    today: List[MyPlanItem] = Field(default_factory=list)       # due-today items
    weekly: List[DashboardWeekItem] = Field(default_factory=list)


# --- doctor: progress review --------------------------------------------------
class ItemProgress(BaseModel):
    item_id: uuid.UUID
    exercise_type: str
    target_phoneme: Optional[str] = None
    difficulty: Optional[Difficulty] = None
    status: PlanItemStatus
    total_attempts: int
    avg_fluency: Optional[float] = None
    last_attempt_at: Optional[datetime] = None


class PlanProgressResponse(BaseModel):
    plan_id: uuid.UUID
    title: str
    items: List[ItemProgress]
