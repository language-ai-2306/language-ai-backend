"""
Game/phrase-selection logic — the rules that decide which phrases a patient gets.

The key rule: a phrase shown to a user must NOT be served to them again for
`phrase_repeat_block_days` days (runtime value from app_config). We enforce this
by excluding any phrase that appears in `phrase_delivery` for this user within
the cutoff window.

Two reusable functions:
  * select_unseen_phrases(...) -> picks N random eligible phrases.
  * record_deliveries(...)     -> writes a phrase_delivery row for each phrase
                                  shown, which is what makes the cooldown work
                                  next time.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.delivery import DeliveryContext, PhraseDelivery
from app.models.disfluency import Difficulty, DisfluencyPhrase
from app.models.patient import PatientDetail, patient_ailment
from app.services import config_service


def get_patient_ailment_ids(db: Session, user_id: int) -> List[int]:
    """The ailment ids a patient practices (used to serve relevant phrases)."""
    patient = db.scalar(select(PatientDetail).where(PatientDetail.user_id == user_id))
    if patient is None:
        return []
    return list(
        db.scalars(
            select(patient_ailment.c.ailment_id).where(
                patient_ailment.c.patient_detail_id == patient.id
            )
        ).all()
    )


def select_unseen_phrases(
    db: Session,
    user_id: int,
    count: int,
    difficulty: Optional[Difficulty] = None,
    ailment_ids: Optional[Sequence[int]] = None,
) -> List[DisfluencyPhrase]:
    """
    Return up to `count` RANDOM phrases that this user has NOT been shown in the
    last 15 days. Optionally filter by difficulty and/or the patient's ailments.

    If fewer than `count` eligible phrases exist, returns however many there are
    (we never break the cooldown rule just to hit the count).
    """
    block_days = config_service.get_int(
        "phrase_repeat_block_days", db, default=settings.phrase_repeat_block_days
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=block_days)

    # Phrase ids already shown to this user within the block window.
    recently_shown = (
        select(PhraseDelivery.phrase_id)
        .where(PhraseDelivery.user_id == user_id)
        .where(PhraseDelivery.created_at >= cutoff)
    )

    query = select(DisfluencyPhrase).where(DisfluencyPhrase.id.not_in(recently_shown))

    if difficulty is not None:
        query = query.where(DisfluencyPhrase.difficulty == difficulty)
    if ailment_ids:
        query = query.where(DisfluencyPhrase.ailment_id.in_(ailment_ids))

    # ORDER BY random() lets PostgreSQL do the shuffling for us.
    query = query.order_by(func.random()).limit(count)
    return list(db.scalars(query).all())


def record_deliveries(
    db: Session,
    user_id: int,
    phrases: Sequence[DisfluencyPhrase],
    context: DeliveryContext,
) -> None:
    """Write one phrase_delivery row per phrase shown. Caller commits."""
    for phrase in phrases:
        db.add(PhraseDelivery(user_id=user_id, phrase_id=phrase.id, context=context))
