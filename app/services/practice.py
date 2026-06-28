"""Persistence for "Repeat After Me" attempts.

`record_attempt` takes the raw result dict produced by
``app.analysis.pipeline.analyze`` and stores it as a PracticeAttempt row,
promoting the dashboard-relevant scalar metrics to their own columns while
keeping the full payloads in JSONB. This is what the speech-therapist
dashboard later reads from.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.practice_attempt import PracticeAttempt

logger = logging.getLogger(__name__)


def record_attempt(
    db: Session,
    *,
    user_id: int,
    reference_phrase: str,
    result: dict[str, Any],
    phrase_id: int | None = None,
    child_age: int | None = None,
    audio_url: str | None = None,
) -> PracticeAttempt:
    """Persist one analysed Repeat-After-Me attempt and return the saved row.

    Args:
        db:               SQLAlchemy session (caller owns the transaction lifetime;
                          this function commits).
        user_id:          The patient who made the attempt.
        reference_phrase: The target text the patient was asked to say.
        result:           The dict returned by ``pipeline.analyze``.
        phrase_id:        FK to the catalogued phrase, if this attempt used one.
        child_age:        Age used to calibrate scoring/feedback.
        audio_url:        S3 URL of the recording, if uploaded.
    """
    scores: dict[str, Any] = result.get("scores", {}) or {}
    recognition: dict[str, Any] = result.get("recognition", {}) or {}

    attempt = PracticeAttempt(
        user_id=user_id,
        phrase_id=phrase_id,
        reference_phrase=reference_phrase,
        transcript=result.get("transcript"),
        audio_url=audio_url,
        child_age=child_age,
        # Promoted scalar metrics.
        fluency_score=scores.get("fluency_score"),
        coverage_score=scores.get("coverage_score"),
        stutter_frequency_percent=scores.get("stutter_frequency_percent"),
        words_per_minute=scores.get("words_per_minute"),
        dominant_disfluency=recognition.get("dominant_disfluency"),
        should_retry=result.get("should_retry"),
        # Full payloads.
        disfluencies=result.get("disfluencies"),
        recognition=recognition or None,
        scores=scores or None,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    logger.info(
        "practice attempt stored id=%s user=%s phrase=%s fluency=%s",
        attempt.id, user_id, phrase_id, attempt.fluency_score,
    )
    return attempt
