"""Patient-facing plan route — the child's active plan and today's due exercises."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_patient
from app.db.base import get_db
from app.models.patient import PatientDetail
from app.schemas.practice_plan import MyPlanResponse, PatientDashboardResponse
from app.services import practice_plan as service

router = APIRouter(tags=["my-plan"])


@router.get(
    "/v1/patient/dashboard",
    response_model=PatientDashboardResponse,
    summary="Patient home dashboard: today's due items + this week's schedule",
)
def patient_dashboard(
    db: Session = Depends(get_db),
    patient: PatientDetail = Depends(get_current_patient),
) -> PatientDashboardResponse:
    """`today` = items scheduled for today (with attempts_today + due). `this_week`
    = each active item and the weekdays it runs this week. Empty if no active plan."""
    return service.get_dashboard(db, patient)


@router.get(
    "/v1/my-plan",
    response_model=MyPlanResponse,
    summary="The patient's active plan and today's due exercises",
)
def my_plan(
    db: Session = Depends(get_db),
    patient: PatientDetail = Depends(get_current_patient),
) -> MyPlanResponse:
    """Returns the patient's ACTIVE plan with its active items, each annotated with
    today's attempt count and whether it's still due (per its dosage). Empty if the
    patient has no active plan."""
    return service.get_my_plan(db, patient)
