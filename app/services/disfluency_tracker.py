"""Disfluency profile — write and aggregate.

`record_occurrences` explodes a turn's disfluency events into one row each in
`disfluency_occurrence`. `get_disfluency_profile` aggregates those rows into a
per-child profile (top problem sounds / types / words), ranked by a
severity-weighted score within a recent time window.

No ML here — it's deterministic aggregation, which keeps the numbers explainable
for the therapists who read them.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.analysis.recognition import _clean
from app.models.disfluency_occurrence import DisfluencyOccurrence

logger = logging.getLogger(__name__)

# Onset clusters/digraphs the phrase library targets, longest first. We match the
# longest prefix so the profile's `sound` aligns with DisfluencyPhrase.target_phoneme
# (e.g. "think" → "th", "street" → "str", "snake" → "sn"), enabling phrase targeting.
_ONSET_CLUSTERS = (
    "scr", "spl", "spr", "str",                              # 3-char
    "bl", "br", "ch", "cl", "dr", "fl", "fr", "gr", "pl",    # 2-char
    "pr", "sh", "sk", "sl", "sm", "sn", "sp", "sw", "th", "tr",
)


def extract_onset_sound(word: str | None) -> str | None:
    """Return the onset phoneme of a word, matched to the phrase library's
    vocabulary (longest cluster first, else the first letter)."""
    if not word:
        return None
    w = _clean(word)
    if not w:
        return None
    for cluster in _ONSET_CLUSTERS:
        if w.startswith(cluster):
            return cluster
    return w[0]

# Severity → weight, so three mild stumbles don't outrank one severe block.
_SEVERITY_WEIGHT = case(
    (DisfluencyOccurrence.severity == "severe", 3),
    (DisfluencyOccurrence.severity == "moderate", 2),
    else_=1,
)


def record_occurrences(
    db: Session,
    *,
    user_id: int,
    disfluencies: Sequence[dict[str, Any]] | None,
    source: str = "conversation",
    session_id=None,
    turn_id: int | None = None,
) -> int:
    """Persist one row per disfluency event. Returns the number stored.

    The onset `sound` is taken from the event if present, else derived from the
    first letter of the stumbled word (repetitions/blocks cluster on onsets).
    """
    rows: list[DisfluencyOccurrence] = []
    for ev in disfluencies or []:
        dtype = (ev.get("type") or "").strip().lower()
        if not dtype:
            continue
        word = ev.get("word") or None
        sound = ev.get("sound") or extract_onset_sound(word)
        rows.append(
            DisfluencyOccurrence(
                user_id=user_id,
                source=source,
                session_id=session_id,
                turn_id=turn_id,
                disfluency_type=dtype,
                word=word,
                sound=(sound or None),
                severity=((ev.get("severity") or "").strip().lower() or None),
                timestamp_start=ev.get("timestamp_start"),
                timestamp_end=ev.get("timestamp_end"),
            )
        )
    if rows:
        db.add_all(rows)
        db.commit()
        logger.info("recorded %d disfluency occurrences for user=%s", len(rows), user_id)
    return len(rows)


def get_disfluency_profile(
    db: Session, user_id: int, *, window_days: int = 90, top: int = 10
) -> dict[str, Any]:
    """Aggregate a child's recent disfluencies into a ranked profile.

    Returns top problem sounds, types and words within the last `window_days`,
    each with an occurrence count and a severity-weighted score (used for
    ranking — and, later, for choosing targeted Repeat-After-Me phrases).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    where = [
        DisfluencyOccurrence.user_id == user_id,
        DisfluencyOccurrence.created_at >= cutoff,
    ]

    total = db.scalar(
        select(func.count()).select_from(DisfluencyOccurrence).where(*where)
    ) or 0
    last_seen = db.scalar(
        select(func.max(DisfluencyOccurrence.created_at)).where(*where)
    )

    def grouped(col) -> list[dict[str, Any]]:
        q = (
            select(
                col.label("value"),
                func.count().label("count"),
                func.sum(_SEVERITY_WEIGHT).label("score"),
            )
            .where(*where, col.isnot(None))
            .group_by(col)
            .order_by(func.sum(_SEVERITY_WEIGHT).desc(), func.count().desc())
            .limit(top)
        )
        return [
            {"value": r.value, "count": int(r.count), "severity_score": int(r.score or 0)}
            for r in db.execute(q)
        ]

    return {
        "user_id": user_id,
        "window_days": window_days,
        "total_occurrences": int(total),
        "last_seen": last_seen,
        "by_sound": grouped(DisfluencyOccurrence.sound),
        "by_type": grouped(DisfluencyOccurrence.disfluency_type),
        "by_word": grouped(DisfluencyOccurrence.word),
    }
