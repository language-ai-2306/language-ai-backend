"""SLP dashboard service — analytics aggregations over existing data.

Read-only. Everything keys off the patient's `user.id`:
  * fluency metrics    → practice_attempt (planned AND free play)
  * adherence          → plan_item_session vs the patient's active plan schedule
  * disfluency profile → disfluency_occurrence
  * per-sound mastery  → practice_skill
  * baseline           → proficiency_test

Ownership: a doctor may only view a patient linked to them
(PatientDetail.doctor_id == doctor.user_id).
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.guid import get_by_guid
from app.models.disfluency_occurrence import DisfluencyOccurrence
from app.models.doctor import Doctor
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
from app.models.practice_skill import PracticeSkill
from app.models.proficiency import ProficiencyTest
from app.models.user import User
from app.services.practice_plan import _scheduled_today  # reuse the schedule logic

# Windows.
_RECENT_DAYS = 7
_INACTIVE_DAYS = 3
_TREND_WEEKS = 8
_CALENDAR_DAYS = 28

# Thresholds for alerts.
_SS_REGRESSION = 2.0      # %SS worse than prior week by this much
_FLUENCY_PLATEAU = 2.0    # |Δ fluency| under this = flat
_LOW_ADHERENCE = 50       # percent


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _r(x: Optional[float]) -> Optional[float]:
    return round(float(x), 1) if x is not None else None


def _age(user: User) -> Optional[int]:
    dob = getattr(user, "dob", None)
    if dob is None:
        return None
    today = _now().date()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _name(user: User) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.email


# --- authorisation ------------------------------------------------------------
def _owned_patient(db: Session, doctor: Doctor, patient_guid) -> User:
    user = get_by_guid(db, User, patient_guid)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    detail = db.scalar(select(PatientDetail).where(PatientDetail.user_id == user.id))
    if detail is None or detail.doctor_id != doctor.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    return user


# --- shared aggregations ------------------------------------------------------
def _avg_metrics(db: Session, user_id: int, start: Optional[datetime] = None,
                 end: Optional[datetime] = None) -> tuple:
    """(avg_fluency, avg_ss, avg_wpm, count) over practice_attempt in a window."""
    q = select(
        func.avg(PracticeAttempt.fluency_score),
        func.avg(PracticeAttempt.stutter_frequency_percent),
        func.avg(PracticeAttempt.words_per_minute),
        func.count(PracticeAttempt.id),
    ).where(PracticeAttempt.user_id == user_id)
    if start is not None:
        q = q.where(PracticeAttempt.created_at >= start)
    if end is not None:
        q = q.where(PracticeAttempt.created_at < end)
    return db.execute(q).first() or (None, None, None, 0)


def _dominant_disfluency(db: Session, user_id: int) -> Optional[str]:
    row = db.execute(
        select(PracticeAttempt.dominant_disfluency, func.count())
        .where(
            PracticeAttempt.user_id == user_id,
            PracticeAttempt.dominant_disfluency.isnot(None),
        )
        .group_by(PracticeAttempt.dominant_disfluency)
        .order_by(func.count().desc())
        .limit(1)
    ).first()
    return row[0] if row else None


def _last_active(db: Session, user_id: int) -> Optional[datetime]:
    return db.scalar(
        select(func.max(PracticeAttempt.created_at)).where(PracticeAttempt.user_id == user_id)
    )


def _plan_item_ids(db: Session, user_id: int, active_only: bool = True) -> list[int]:
    q = select(PlanItem.id).join(PracticePlan, PlanItem.plan_id == PracticePlan.id).where(
        PracticePlan.patient_id == user_id
    )
    if active_only:
        q = q.where(PracticePlan.status == PlanStatus.ACTIVE)
    return [r for (r,) in db.execute(q).all()]


def _week_bounds(today: date) -> list[date]:
    monday = today - timedelta(days=today.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


def _adherence_this_week(db: Session, user_id: int, today: date) -> dict[str, Any]:
    """Scheduled vs completed occurrences across the patient's ACTIVE plans, this week."""
    week_dates = _week_bounds(today)
    scheduled = 0
    items = list(
        db.scalars(
            select(PlanItem)
            .join(PracticePlan, PlanItem.plan_id == PracticePlan.id)
            .where(
                PracticePlan.patient_id == user_id,
                PracticePlan.status == PlanStatus.ACTIVE,
                PlanItem.status == PlanItemStatus.ACTIVE,
            )
        ).all()
    )
    item_ids = [it.id for it in items]
    for it in items:
        scheduled += sum(1 for d in week_dates if _scheduled_today(it.frequency, it.schedule, d))

    completed = 0
    if item_ids:
        completed = int(
            db.scalar(
                select(func.count(PlanItemSession.id)).where(
                    PlanItemSession.plan_item_id.in_(item_ids),
                    PlanItemSession.occurrence_date.in_(week_dates),
                    PlanItemSession.status == PlanItemSessionStatus.COMPLETED,
                )
            )
            or 0
        )
    pct = int(round(100 * completed / scheduled)) if scheduled else None
    return {"scheduled": scheduled, "completed": min(completed, scheduled) if scheduled else completed, "pct": pct}


# --- Tier 1: caseload ---------------------------------------------------------
def get_caseload(db: Session, doctor: Doctor) -> dict[str, Any]:
    rows = db.execute(
        select(PatientDetail, User)
        .join(User, PatientDetail.user_id == User.id)
        .where(PatientDetail.doctor_id == doctor.user_id)
        .order_by(PatientDetail.id)
    ).all()

    now = _now()
    today = now.date()
    recent_start = now - timedelta(days=_RECENT_DAYS)
    prior_start = now - timedelta(days=2 * _RECENT_DAYS)

    patients = []
    for _detail, user in rows:
        _, recent_ss, _, recent_n = _avg_metrics(db, user.id, start=recent_start)
        recent_fl, _, _, _ = _avg_metrics(db, user.id, start=recent_start)
        _, prior_ss, _, prior_n = _avg_metrics(db, user.id, start=prior_start, end=recent_start)
        prior_fl, _, _, _ = _avg_metrics(db, user.id, start=prior_start, end=recent_start)

        # SS trend (lower = better).
        ss_trend = None
        if recent_ss is not None and prior_ss is not None:
            diff = recent_ss - prior_ss
            ss_trend = "flat" if abs(diff) < 1 else ("worsening" if diff > 0 else "improving")

        adherence = _adherence_this_week(db, user.id, today)
        last_active = _last_active(db, user.id)

        alerts: list[str] = []
        if last_active is None or last_active < now - timedelta(days=_INACTIVE_DAYS):
            alerts.append("inactive")
        if adherence["pct"] is not None and adherence["pct"] < _LOW_ADHERENCE:
            alerts.append("low_adherence")
        if recent_ss is not None and prior_ss is not None and (recent_ss - prior_ss) > _SS_REGRESSION:
            alerts.append("regression")
        elif (
            recent_fl is not None and prior_fl is not None
            and recent_n >= 3 and prior_n >= 3
            and abs(recent_fl - prior_fl) < _FLUENCY_PLATEAU
        ):
            alerts.append("plateau")

        patients.append(
            {
                "patient_id": user.guid,
                "name": _name(user),
                "email": user.email,
                "age": _age(user),
                "last_active_at": last_active,
                "adherence_pct": adherence["pct"],
                "current_ss": _r(recent_ss),
                "ss_trend": ss_trend,
                "dominant_disfluency": _dominant_disfluency(db, user.id),
                "alerts": alerts,
            }
        )
    return {"patients": patients}


# --- Tier 2: patient detail ---------------------------------------------------
def get_patient_detail(db: Session, doctor: Doctor, patient_guid) -> dict[str, Any]:
    user = _owned_patient(db, doctor, patient_guid)
    uid = user.id
    now = _now()
    today = now.date()
    recent_start = now - timedelta(days=_RECENT_DAYS)
    prior_start = now - timedelta(days=2 * _RECENT_DAYS)

    rec_fl, rec_ss, rec_wpm, _ = _avg_metrics(db, uid, start=recent_start)
    pri_fl, pri_ss, pri_wpm, _ = _avg_metrics(db, uid, start=prior_start, end=recent_start)

    # Baseline = most recent completed proficiency test score.
    baseline = db.scalar(
        select(ProficiencyTest.score)
        .where(ProficiencyTest.user_id == uid, ProficiencyTest.is_completed.is_(True))
        .order_by(ProficiencyTest.created_at.desc())
        .limit(1)
    )

    def _delta(recent, prior, base=None):
        return {
            "value": _r(recent),
            "vs_last_week": _r(recent - prior) if recent is not None and prior is not None else None,
            "vs_baseline": _r(recent - base) if recent is not None and base is not None else None,
        }

    # Weekly trend.
    trend_rows = db.execute(
        select(
            func.date_trunc("week", PracticeAttempt.created_at),
            func.avg(PracticeAttempt.fluency_score),
            func.avg(PracticeAttempt.stutter_frequency_percent),
            func.count(PracticeAttempt.id),
        )
        .where(
            PracticeAttempt.user_id == uid,
            PracticeAttempt.created_at >= now - timedelta(weeks=_TREND_WEEKS),
        )
        .group_by(func.date_trunc("week", PracticeAttempt.created_at))
        .order_by(func.date_trunc("week", PracticeAttempt.created_at))
    ).all()
    fluency_trend = [
        {"week_start": wk.date(), "avg_fluency": _r(fl), "avg_ss": _r(ss), "attempts": int(n)}
        for wk, fl, ss, n in trend_rows
    ]

    # Disfluency-type breakdown.
    breakdown = {
        t: int(c)
        for t, c in db.execute(
            select(DisfluencyOccurrence.disfluency_type, func.count())
            .where(DisfluencyOccurrence.user_id == uid)
            .group_by(DisfluencyOccurrence.disfluency_type)
            .order_by(func.count().desc())
        ).all()
    }

    # Context comparison (per game).
    context = [
        {
            "exercise_type": et or "UNKNOWN",
            "attempts": int(n),
            "avg_fluency": _r(fl),
            "avg_ss": _r(ss),
        }
        for et, fl, ss, n in db.execute(
            select(
                PracticeAttempt.exercise_type,
                func.avg(PracticeAttempt.fluency_score),
                func.avg(PracticeAttempt.stutter_frequency_percent),
                func.count(PracticeAttempt.id),
            )
            .where(PracticeAttempt.user_id == uid)
            .group_by(PracticeAttempt.exercise_type)
            .order_by(func.count(PracticeAttempt.id).desc())
        ).all()
    ]

    # Per-sound mastery.
    per_sound = [
        {
            "target_phoneme": s.target_phoneme,
            "current_difficulty": s.current_difficulty,
            "mastery_level": s.mastery_level,
            "rolling_ss": _r(s.rolling_ss),
            "attempts": s.attempts,
        }
        for s in db.scalars(
            select(PracticeSkill)
            .where(PracticeSkill.user_id == uid)
            .order_by(PracticeSkill.last_practiced_at.desc().nullslast())
        ).all()
    ]

    # Active plan titles.
    active_plans = [
        t
        for (t,) in db.execute(
            select(PracticePlan.title).where(
                PracticePlan.patient_id == uid, PracticePlan.status == PlanStatus.ACTIVE
            )
        ).all()
    ]

    # Practice calendar (last 28 days of completed sessions).
    item_ids = _plan_item_ids(db, uid, active_only=False)
    calendar = []
    if item_ids:
        cal_start = today - timedelta(days=_CALENDAR_DAYS)
        cal_rows = db.execute(
            select(PlanItemSession.occurrence_date, func.count(PlanItemSession.id))
            .where(
                PlanItemSession.plan_item_id.in_(item_ids),
                PlanItemSession.status == PlanItemSessionStatus.COMPLETED,
                PlanItemSession.occurrence_date >= cal_start,
            )
            .group_by(PlanItemSession.occurrence_date)
            .order_by(PlanItemSession.occurrence_date)
        ).all()
        calendar = [{"date": d, "completed": int(c)} for d, c in cal_rows]

    return {
        "patient_id": user.guid,
        "name": _name(user),
        "age": _age(user),
        "dominant_disfluency": _dominant_disfluency(db, uid),
        "active_plans": active_plans,
        "fluency": _delta(rec_fl, pri_fl, baseline),
        "stutter_frequency": _delta(rec_ss, pri_ss),
        "words_per_minute": _delta(rec_wpm, pri_wpm),
        "fluency_trend": fluency_trend,
        "disfluency_breakdown": breakdown,
        "context_comparison": context,
        "per_sound": per_sound,
        "adherence_this_week": _adherence_this_week(db, uid, today),
        "practice_calendar": calendar,
    }


# --- Tier 3: attempt drill-down ----------------------------------------------
def list_attempts(db: Session, doctor: Doctor, patient_guid, limit: int, offset: int) -> dict[str, Any]:
    user = _owned_patient(db, doctor, patient_guid)
    total = int(
        db.scalar(select(func.count(PracticeAttempt.id)).where(PracticeAttempt.user_id == user.id)) or 0
    )
    rows = db.scalars(
        select(PracticeAttempt)
        .where(PracticeAttempt.user_id == user.id)
        .order_by(PracticeAttempt.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    attempts = [
        {
            "attempt_id": a.guid,
            "created_at": a.created_at,
            "exercise_type": a.exercise_type,
            "fluency_score": _r(a.fluency_score),
            "stutter_frequency_percent": _r(a.stutter_frequency_percent),
            "words_per_minute": _r(a.words_per_minute),
            "dominant_disfluency": a.dominant_disfluency,
        }
        for a in rows
    ]
    return {"attempts": attempts, "total": total}


def get_attempt(db: Session, doctor: Doctor, attempt_guid) -> dict[str, Any]:
    attempt = get_by_guid(db, PracticeAttempt, attempt_guid)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    # Authorise: the attempt's patient must be linked to this doctor.
    detail = db.scalar(select(PatientDetail).where(PatientDetail.user_id == attempt.user_id))
    if detail is None or detail.doctor_id != doctor.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    return {
        "attempt_id": attempt.guid,
        "created_at": attempt.created_at,
        "exercise_type": attempt.exercise_type,
        "reference_phrase": attempt.reference_phrase,
        "transcript": attempt.transcript,
        "audio_url": attempt.audio_url,
        "fluency_score": _r(attempt.fluency_score),
        "coverage_score": _r(attempt.coverage_score),
        "stutter_frequency_percent": _r(attempt.stutter_frequency_percent),
        "words_per_minute": _r(attempt.words_per_minute),
        "dominant_disfluency": attempt.dominant_disfluency,
        "disfluencies": attempt.disfluencies,
        "recognition": attempt.recognition,
        "scores": attempt.scores,
    }
