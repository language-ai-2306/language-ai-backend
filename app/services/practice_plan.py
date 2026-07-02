"""Practice-plan service — CRUD, ownership, validation, and "today's due".

Ownership: a doctor may only touch plans for their APPROVED patients — i.e. a
PatientDetail whose doctor_id equals the doctor's id (the care-team link).
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.guid import get_by_guid
from app.models.disfluency import Difficulty
from app.models.doctor import Doctor
from app.models.exercise import ExerciseType
from app.models.patient import PatientDetail
from app.models.practice_attempt import PracticeAttempt
from app.models.practice_plan import (
    PlanItem,
    PlanItemSession,
    PlanItemSessionStatus,
    PlanItemStatus,
    PlanStatus,
    PracticePlan,
)
from app.models.user import User

_PHONEME_GAMES = {ExerciseType.REPEAT_AFTER_ME.value, ExerciseType.READ_IT_LOUD.value}
_NO_DIFFICULTY_GAMES = {ExerciseType.TALK_WITH_OLLIE.value}
_VALID_GAMES = {e.value for e in ExerciseType}

_DEFAULT_DOSAGE = {"reps_per_session": 1}
_DEFAULT_ADVANCEMENT = {"mode": "AUTO", "metric": "fluency_score", "threshold": 80, "window": 3}


# --- GUID serialisation (public ids are GUIDs; internal ids stay integer) ------
def _user_guid(db: Session, user_id: Optional[int]):
    if user_id is None:
        return None
    u = db.get(User, user_id)
    return u.guid if u else None


def _serialize_item(item: PlanItem) -> dict[str, Any]:
    return {
        "item_id": item.guid,
        "sequence": item.sequence,
        "exercise_type": item.exercise_type,
        "target_phoneme": item.target_phoneme,
        "difficulty": item.difficulty,
        "frequency": item.frequency,
        "duration_minutes": item.duration_minutes,
        "schedule": item.schedule,
        "dosage": item.dosage,
        "advancement": item.advancement,
        "status": item.status,
    }


def _serialize_plan(db: Session, plan: PracticePlan) -> dict[str, Any]:
    return {
        "plan_id": plan.guid,
        "patient_id": _user_guid(db, plan.patient_id),
        "doctor_id": _user_guid(db, plan.doctor_id),
        "title": plan.title,
        "description": plan.description,
        "status": plan.status,
        "start_date": plan.start_date,
        "end_date": plan.end_date,
        "items": [_serialize_item(i) for i in plan.items],
    }

_FREQUENCIES = {"DAILY", "WEEKLY", "MONTHLY", "CUSTOM"}
_WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]  # index = date.weekday()
_WEEKDAY_SET = set(_WEEKDAYS)


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime.combine(now.date(), time.min, tzinfo=timezone.utc)


def _validate_schedule(frequency: Optional[str], schedule: Optional[dict]) -> None:
    freq = (frequency or "DAILY").upper()
    if freq not in _FREQUENCIES:
        raise HTTPException(422, f"frequency must be one of {sorted(_FREQUENCIES)}")
    sched = schedule or {}
    dow = sched.get("days_of_week") or []
    dom = sched.get("days_of_month") or []
    if not all(d in _WEEKDAY_SET for d in dow):
        raise HTTPException(422, f"days_of_week must be from {_WEEKDAYS}")
    if not all(isinstance(d, int) and 1 <= d <= 31 for d in dom):
        raise HTTPException(422, "days_of_month must be integers 1-31")
    if freq == "WEEKLY" and not dow:
        raise HTTPException(422, "WEEKLY frequency requires schedule.days_of_week")
    if freq == "MONTHLY" and not dom:
        raise HTTPException(422, "MONTHLY frequency requires schedule.days_of_month")
    if freq == "CUSTOM" and not dow and not dom:
        raise HTTPException(422, "CUSTOM frequency requires days_of_week and/or days_of_month")


def _scheduled_today(frequency: str, schedule: dict, today: date) -> bool:
    freq = (frequency or "DAILY").upper()
    sched = schedule or {}
    if freq == "DAILY":
        return True
    dow_ok = _WEEKDAYS[today.weekday()] in (sched.get("days_of_week") or [])
    dom_ok = today.day in (sched.get("days_of_month") or [])
    if freq == "WEEKLY":
        return dow_ok
    if freq == "MONTHLY":
        return dom_ok
    return dow_ok or dom_ok  # CUSTOM


# --- validation & ownership ---------------------------------------------------
def _validate_item(exercise_type: str, phoneme: Optional[str], difficulty: Optional[Difficulty]) -> None:
    if exercise_type not in _VALID_GAMES:
        raise HTTPException(422, f"Unknown exercise_type '{exercise_type}'. Valid: {sorted(_VALID_GAMES)}")
    if phoneme and exercise_type not in _PHONEME_GAMES:
        raise HTTPException(422, "target_phoneme is only allowed for REPEAT_AFTER_ME and READ_IT_LOUD")
    if exercise_type not in _NO_DIFFICULTY_GAMES and difficulty is None:
        raise HTTPException(422, f"difficulty is required for {exercise_type}")


def _owned_patient(db: Session, doctor: Doctor, patient_user_id: int) -> PatientDetail:
    """Resolve the PatientDetail for a patient user id and confirm it's the
    doctor's approved patient (PatientDetail.doctor_id == the doctor's user.id)."""
    pd = db.scalar(select(PatientDetail).where(PatientDetail.user_id == patient_user_id))
    if pd is None or pd.doctor_id != doctor.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found among your patients")
    return pd


def _owned_plan(db: Session, doctor: Doctor, plan_guid) -> PracticePlan:
    plan = get_by_guid(db, PracticePlan, plan_guid)
    if plan is None or plan.doctor_id != doctor.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
    return plan


# NOTE: a patient may have MANY plans, including multiple ACTIVE ones — no
# uniqueness constraint on active plans.


def _build_item(payload, index: int) -> PlanItem:
    _validate_item(payload.exercise_type, payload.target_phoneme, payload.difficulty)
    _validate_schedule(payload.frequency, payload.schedule)
    return PlanItem(
        sequence=payload.sequence if payload.sequence is not None else index,
        exercise_type=payload.exercise_type,
        target_phoneme=payload.target_phoneme,
        difficulty=payload.difficulty,
        frequency=(payload.frequency or "DAILY").upper(),
        duration_minutes=payload.duration_minutes,
        schedule=payload.schedule or {},
        dosage=payload.dosage or dict(_DEFAULT_DOSAGE),
        advancement=payload.advancement or dict(_DEFAULT_ADVANCEMENT),
        status=PlanItemStatus.ACTIVE,
    )


# --- CRUD (public args are GUIDs) ---------------------------------------------
def create_plan(db: Session, doctor: Doctor, payload) -> dict[str, Any]:
    patient_user = get_by_guid(db, User, payload.patient_id)  # patient user GUID
    if patient_user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found among your patients")
    pd = _owned_patient(db, doctor, patient_user.id)

    plan = PracticePlan(
        patient_id=pd.user_id,
        doctor_id=doctor.user_id,
        title=payload.title,
        description=payload.description,
        status=payload.status,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    for i, item in enumerate(payload.items):
        plan.items.append(_build_item(item, i))
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _serialize_plan(db, plan)


def list_plans(db: Session, doctor: Doctor, patient_id, status_filter: Optional[PlanStatus]) -> list[dict[str, Any]]:
    q = select(PracticePlan).where(PracticePlan.doctor_id == doctor.user_id)
    if patient_id is not None:  # patient user GUID
        patient_user = get_by_guid(db, User, patient_id)
        q = q.where(PracticePlan.patient_id == (patient_user.id if patient_user else -1))
    if status_filter is not None:
        q = q.where(PracticePlan.status == status_filter)
    plans = db.scalars(q.order_by(PracticePlan.created_at.desc())).all()
    return [
        {
            "plan_id": p.guid,
            "title": p.title,
            "status": p.status,
            "start_date": p.start_date,
            "end_date": p.end_date,
            "item_count": len(p.items),
            "items": [_serialize_item(i) for i in p.items],
        }
        for p in plans
    ]


def get_plan(db: Session, doctor: Doctor, plan_guid) -> dict[str, Any]:
    return _serialize_plan(db, _owned_plan(db, doctor, plan_guid))


def update_plan(db: Session, doctor: Doctor, plan_guid, payload) -> dict[str, Any]:
    plan = _owned_plan(db, doctor, plan_guid)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(plan, field, value)
    db.commit()
    db.refresh(plan)
    return _serialize_plan(db, plan)


def delete_plan(db: Session, doctor: Doctor, plan_guid) -> None:
    """Hard-delete a plan. Cascades to its items and their attempt logs."""
    plan = _owned_plan(db, doctor, plan_guid)
    db.delete(plan)
    db.commit()


def add_item(db: Session, doctor: Doctor, plan_guid, payload) -> dict[str, Any]:
    plan = _owned_plan(db, doctor, plan_guid)
    item = _build_item(payload, len(plan.items))
    item.plan_id = plan.id
    db.add(item)
    db.commit()
    db.refresh(item)
    return _serialize_item(item)


def update_item(db: Session, doctor: Doctor, plan_guid, item_guid, payload) -> dict[str, Any]:
    plan = _owned_plan(db, doctor, plan_guid)
    item = next((i for i in plan.items if str(i.guid) == str(item_guid)), None)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan item not found")
    data = payload.model_dump(exclude_unset=True)
    # Re-validate the resulting combination.
    _validate_item(
        item.exercise_type,
        data.get("target_phoneme", item.target_phoneme),
        data.get("difficulty", item.difficulty),
    )
    if "frequency" in data or "schedule" in data:
        _validate_schedule(
            data.get("frequency", item.frequency),
            data.get("schedule", item.schedule),
        )
        if data.get("frequency"):
            data["frequency"] = data["frequency"].upper()
    for field, value in data.items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return _serialize_item(item)


def delete_item(db: Session, doctor: Doctor, plan_guid, item_guid) -> None:
    plan = _owned_plan(db, doctor, plan_guid)
    item = next((i for i in plan.items if str(i.guid) == str(item_guid)), None)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan item not found")
    db.delete(item)
    db.commit()


# --- progress (doctor) --------------------------------------------------------
def get_progress(db: Session, doctor: Doctor, plan_guid) -> dict[str, Any]:
    plan = _owned_plan(db, doctor, plan_guid)
    items = []
    for item in plan.items:
        agg = db.execute(
            select(
                func.count(PracticeAttempt.id),
                func.avg(PracticeAttempt.fluency_score),
                func.max(PracticeAttempt.created_at),
            )
            .join(PlanItemSession, PracticeAttempt.plan_item_session_id == PlanItemSession.id)
            .where(PlanItemSession.plan_item_id == item.id)
        ).first()
        total, avg_fluency, last_at = agg if agg else (0, None, None)

        # Adherence: sessions started vs completed for this occurrence-based item.
        sess = db.execute(
            select(
                func.count(PlanItemSession.id),
                func.count(PlanItemSession.id).filter(
                    PlanItemSession.status == PlanItemSessionStatus.COMPLETED
                ),
            ).where(PlanItemSession.plan_item_id == item.id)
        ).first()
        sessions_total, sessions_completed = sess if sess else (0, 0)

        items.append(
            {
                "item_id": item.guid,
                "exercise_type": item.exercise_type,
                "target_phoneme": item.target_phoneme,
                "difficulty": item.difficulty,
                "status": item.status,
                "total_attempts": int(total or 0),
                "avg_fluency": round(float(avg_fluency), 1) if avg_fluency is not None else None,
                "last_attempt_at": last_at,
                "sessions_total": int(sessions_total or 0),
                "sessions_completed": int(sessions_completed or 0),
            }
        )
    return {"plan_id": plan.guid, "title": plan.title, "items": items}


# --- my plan (patient) --------------------------------------------------------
def _active_plans(db: Session, patient: PatientDetail) -> list[PracticePlan]:
    return list(
        db.scalars(
            select(PracticePlan).where(
                PracticePlan.patient_id == patient.user_id,
                PracticePlan.status == PlanStatus.ACTIVE,
            )
        ).all()
    )


def _today_session(db: Session, item_id: int, today: date) -> Optional[PlanItemSession]:
    """Today's occurrence for this item, if one has been opened."""
    return db.scalar(
        select(PlanItemSession).where(
            PlanItemSession.plan_item_id == item_id,
            PlanItemSession.occurrence_date == today,
        )
    )


def _completed_count(db: Session, item_id: int, dates: list[date]) -> int:
    """How many COMPLETED sessions this item has on any of the given dates.

    Uses the range (not the exact scheduled weekday) so completing a weekly item a
    day early/late still counts as done for the week.
    """
    if not dates:
        return 0
    return int(
        db.scalar(
            select(func.count(PlanItemSession.id)).where(
                PlanItemSession.plan_item_id == item_id,
                PlanItemSession.occurrence_date.in_(dates),
                PlanItemSession.status == PlanItemSessionStatus.COMPLETED,
            )
        )
        or 0
    )


def _today_progress(session: Optional[PlanItemSession]) -> tuple[int, bool]:
    """(attempts_today, due) for a scheduled item, from today's session.

    An item is DUE until its session is explicitly COMPLETED (via /end). No
    session yet, or a session still IN_PROGRESS → still due.
    """
    attempts_today = session.attempts_count if session is not None else 0
    done = session is not None and session.status == PlanItemSessionStatus.COMPLETED
    return attempts_today, not done


def get_my_plan(db: Session, patient: PatientDetail) -> dict[str, Any]:
    """Today's due items aggregated across ALL of the patient's active plans."""
    today_dt = _today_start()
    today = today_dt.date()
    items = []
    for plan in _active_plans(db, patient):
        for item in plan.items:
            if item.status != PlanItemStatus.ACTIVE:
                continue
            if not _scheduled_today(item.frequency, item.schedule, today):
                continue
            session = _today_session(db, item.id, today)
            # Finished today's occurrence → drop it from the list.
            if session is not None and session.status == PlanItemSessionStatus.COMPLETED:
                continue
            attempts_today, due = _today_progress(session)
            items.append(
                {
                    "item_id": item.guid,
                    "plan_id": plan.guid,
                    "plan_title": plan.title,
                    "exercise_type": item.exercise_type,
                    "target_phoneme": item.target_phoneme,
                    "difficulty": item.difficulty,
                    "frequency": item.frequency,
                    "duration_minutes": item.duration_minutes,
                    "dosage": item.dosage,
                    "status": item.status,
                    "attempts_today": attempts_today,
                    "due": due,
                }
            )
    return {"items": items}


def mark_item_done(db: Session, patient: PatientDetail, item_guid) -> dict[str, Any]:
    """Patient marks a plan item done for today from the dashboard — same effect as
    the exercise /end call: completes today's session. Find-or-creates the session
    first, so it works even if the exercise flow was never started."""
    from app.services import plan_progress

    item = get_by_guid(db, PlanItem, item_guid)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan item not found")
    plan = db.get(PracticePlan, item.plan_id)
    if plan is None or plan.patient_id != patient.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan item not found")

    session = plan_progress.complete_session(db, patient.user, item)
    return {
        "item_id": item.guid,
        "attempts_today": session.attempts_count,
        "due": False,
        "completed": True,
    }


def get_dashboard(db: Session, patient: PatientDetail) -> dict[str, Any]:
    """Patient home screen: today's due items + this week's schedule, across ALL
    active plans."""
    today_dt = _today_start()
    today = today_dt.date()
    monday = today - timedelta(days=today.weekday())
    week_dates = [monday + timedelta(days=i) for i in range(7)]

    today_items: list[dict[str, Any]] = []
    week_items: list[dict[str, Any]] = []
    for plan in _active_plans(db, patient):
        for item in plan.items:
            if item.status != PlanItemStatus.ACTIVE:
                continue
            scheduled_dates = [
                d for d in week_dates if _scheduled_today(item.frequency, item.schedule, d)
            ]
            if not scheduled_dates:
                continue

            # Done for the week? (all of this week's scheduled occurrences completed)
            # → drop the item from the dashboard entirely.
            if _completed_count(db, item.id, week_dates) >= len(scheduled_dates):
                continue

            base = {
                "item_id": item.guid,
                "plan_id": plan.guid,
                "plan_title": plan.title,
                "exercise_type": item.exercise_type,
                "target_phoneme": item.target_phoneme,
                "difficulty": item.difficulty,
                "frequency": item.frequency,
                "duration_minutes": item.duration_minutes,
            }
            week_items.append(
                {**base, "scheduled_days": [_WEEKDAYS[d.weekday()] for d in scheduled_dates]}
            )

            # Today's to-do: scheduled today AND today's occurrence not yet completed.
            if _scheduled_today(item.frequency, item.schedule, today):
                session = _today_session(db, item.id, today)
                if session is None or session.status != PlanItemSessionStatus.COMPLETED:
                    attempts_today, due = _today_progress(session)
                    today_items.append(
                        {
                            **base,
                            "dosage": item.dosage,
                            "status": item.status,
                            "attempts_today": attempts_today,
                            "due": due,
                        }
                    )

    return {"today": today_items, "weekly": week_items}
