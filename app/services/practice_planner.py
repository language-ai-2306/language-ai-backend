"""Phase 2 — adaptive targeted practice.

Two responsibilities:

  build_practice_set(...)  — choose a personalised, mixed batch of Repeat-After-Me
                             phrases aimed at the child's problem sounds, at the
                             right difficulty per sound, with a warm-up / at-level /
                             stretch difficulty mix, respecting cooldown.
  process_attempt(...)     — the feedback loop after each attempt: feed its
                             disfluencies into the unified profile and update the
                             child's per-sound mastery (promote / demote difficulty).

Parameters are grounded in the stuttering-therapy research (see
docs/Stuttering_Research_Compendium.docx) and are tunable at runtime via
app_config (SLPs can adjust without a deploy):
  * Scoring uses %SS (percent syllables stuttered). Guitar (2019) bands:
    < 2 normal/mastered · 2–<4 mild · 4–<8 moderate · ≥8 severe.
  * Promotion mirrors Lidcombe's "sustained near-zero" rule.
  * A warm-up/stretch mix keeps success rates motivating (desensitization) while
    still challenging (zone of proximal development); mixed practice aids retention.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.delivery import DeliveryContext, PhraseDelivery
from app.models.disfluency import Difficulty, DisfluencyPhrase
from app.models.practice_attempt import PracticeAttempt
from app.models.practice_skill import PracticeSkill
from app.services import config_service, disfluency_tracker
from app.services.game import record_deliveries, select_unseen_phrases

logger = logging.getLogger(__name__)

# ── default parameters (overridable via app_config) ───────────────────────────
DIFFICULTY_ORDER = ["EASY", "MEDIUM", "HARD", "TONGUE_TWISTER"]
PROMOTE_SS = 3.0        # %SS below this = a "clean" attempt (≈ Guitar normal/mild floor)
DEMOTE_SS = 8.0         # %SS at/above this is "severe" → drop difficulty
PROMOTE_STREAK = 3      # consecutive clean attempts needed to advance a level
WARMUP_RATIO = 0.2      # fraction of a batch served one tier easier (confidence)
STRETCH_RATIO = 0.2     # fraction of a batch served one tier harder (growth)
MODERATE_SS = 4.0       # ≥ this (and < severe) → "struggling"
EMA_ALPHA = 0.4         # recency weight for the rolling %SS
MAX_TARGET_SOUNDS = 5   # spread a batch across at most this many problem sounds
DEFAULT_BATCH_SIZE = 10


# ── helpers ───────────────────────────────────────────────────────────────────

def _attempt_ss(attempt: PracticeAttempt) -> float | None:
    """The attempt's %SS. Prefer the pipeline's value; else approximate from
    the fluency score (1.0 → 0%, 0.5 → ~5%, 0.2 → ~8%)."""
    if attempt.stutter_frequency_percent is not None:
        return float(attempt.stutter_frequency_percent)
    if attempt.fluency_score is not None:
        return max(0.0, (1.0 - float(attempt.fluency_score)) * 10.0)
    return None


def _shift_difficulty(current: str, step: int) -> str:
    try:
        i = DIFFICULTY_ORDER.index(current)
    except ValueError:
        i = 0
    return DIFFICULTY_ORDER[max(0, min(len(DIFFICULTY_ORDER) - 1, i + step))]


# ════════════════════════════════════════════════════════════════════════════
# Feedback loop — runs after every attempt
# ════════════════════════════════════════════════════════════════════════════

def process_attempt(db: Session, attempt: PracticeAttempt) -> None:
    """Post-attempt feedback loop. Never raises — it's secondary to returning the
    analysis to the child."""
    # 1. Unify the profile: practice disfluencies feed the same per-child profile.
    try:
        disfluency_tracker.record_occurrences(
            db, user_id=attempt.user_id, disfluencies=attempt.disfluencies, source="practice",
        )
    except Exception:  # noqa: BLE001
        logger.warning("failed to record practice disfluencies for attempt %s", attempt.id, exc_info=True)

    # 2. Update per-sound mastery — only for catalogued phrases (we know the target sound).
    if attempt.phrase_id is None:
        return
    phrase = db.get(DisfluencyPhrase, attempt.phrase_id)
    if phrase is None or not phrase.target_phoneme:
        return
    ss = _attempt_ss(attempt)
    if ss is None:
        return

    promote_ss = config_service.get_float("practice_promote_ss", db, PROMOTE_SS)
    demote_ss = config_service.get_float("practice_demote_ss", db, DEMOTE_SS)
    promote_streak = config_service.get_int("practice_promote_streak", db, PROMOTE_STREAK)

    sound = phrase.target_phoneme
    skill = db.scalar(
        select(PracticeSkill).where(
            PracticeSkill.user_id == attempt.user_id,
            PracticeSkill.target_phoneme == sound,
        )
    )
    if skill is None:
        skill = PracticeSkill(
            user_id=attempt.user_id,
            target_phoneme=sound,
            current_difficulty=(phrase.difficulty.value if phrase.difficulty else "EASY"),
            attempts=0,
            consecutive_low=0,
            mastery_level="practicing",
        )
        db.add(skill)

    # Recency-weighted %SS.
    skill.rolling_ss = ss if skill.rolling_ss is None else (EMA_ALPHA * ss + (1 - EMA_ALPHA) * skill.rolling_ss)
    skill.attempts += 1
    skill.last_practiced_at = datetime.now(timezone.utc)

    # Promote / demote difficulty.
    if ss < promote_ss:
        skill.consecutive_low += 1
        if skill.consecutive_low >= promote_streak:
            skill.current_difficulty = _shift_difficulty(skill.current_difficulty, +1)
            skill.consecutive_low = 0
    elif ss >= demote_ss:
        skill.current_difficulty = _shift_difficulty(skill.current_difficulty, -1)
        skill.consecutive_low = 0
    else:
        skill.consecutive_low = 0

    # Mastery label.
    if skill.current_difficulty == DIFFICULTY_ORDER[-1] and (skill.rolling_ss or 0) < promote_ss:
        skill.mastery_level = "mastered"
    elif (skill.rolling_ss or 0) >= MODERATE_SS:
        skill.mastery_level = "struggling"
    else:
        skill.mastery_level = "practicing"

    db.commit()
    logger.info(
        "skill updated user=%s sound=%s ss=%.1f diff=%s mastery=%s",
        attempt.user_id, sound, ss, skill.current_difficulty, skill.mastery_level,
    )


# ════════════════════════════════════════════════════════════════════════════
# Selector — builds a targeted, mixed batch
# ════════════════════════════════════════════════════════════════════════════

def _recently_shown_ids(db: Session, user_id: int) -> set[int]:
    block_days = config_service.get_int(
        "phrase_repeat_block_days", db, default=settings.phrase_repeat_block_days
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=block_days)
    rows = db.scalars(
        select(PhraseDelivery.phrase_id)
        .where(PhraseDelivery.user_id == user_id, PhraseDelivery.created_at >= cutoff)
    ).all()
    return set(rows)


def _pick(db: Session, sound: str, difficulty: str, exclude: set[int]) -> DisfluencyPhrase | None:
    """Pick one unseen phrase for a sound at an exact difficulty."""
    q = (
        select(DisfluencyPhrase)
        .where(
            DisfluencyPhrase.target_phoneme == sound,
            DisfluencyPhrase.difficulty == Difficulty(difficulty),
        )
        .order_by(func.random())
        .limit(1)
    )
    if exclude:
        q = q.where(DisfluencyPhrase.id.not_in(exclude))
    return db.scalar(q)


def _pick_any(db: Session, sound: str, difficulty: str, exclude: set[int]) -> DisfluencyPhrase | None:
    """Pick for a sound, trying the wanted difficulty then adjacent ones."""
    tried: list[str] = []
    for d in (difficulty, _shift_difficulty(difficulty, -1), _shift_difficulty(difficulty, +1)):
        if d in tried:
            continue
        tried.append(d)
        phrase = _pick(db, sound, d, exclude)
        if phrase is not None:
            return phrase
    return None


def build_practice_set(db: Session, user_id: int, count: int | None = None) -> dict[str, Any]:
    """Return a personalised batch (phrase + reason) with a warm-up/at-level/stretch
    difficulty mix, and record delivery for cooldown."""
    if count is None:
        count = config_service.get_int("targeted_batch_size", db, DEFAULT_BATCH_SIZE)
    warmup_ratio = config_service.get_float("practice_warmup_ratio", db, WARMUP_RATIO)
    stretch_ratio = config_service.get_float("practice_stretch_ratio", db, STRETCH_RATIO)

    profile = disfluency_tracker.get_disfluency_profile(db, user_id)
    skills = {
        s.target_phoneme: s
        for s in db.scalars(select(PracticeSkill).where(PracticeSkill.user_id == user_id)).all()
    }

    # Ranked target sounds: profile problem-sounds first, then non-mastered skill sounds.
    target_sounds = [b["value"] for b in profile["by_sound"]]
    for ph, sk in skills.items():
        if sk.mastery_level != "mastered" and ph not in target_sounds:
            target_sounds.append(ph)
    target_sounds = target_sounds[:MAX_TARGET_SOUNDS]

    recently = _recently_shown_ids(db, user_id)
    chosen: list[tuple[DisfluencyPhrase, str]] = []
    chosen_ids: set[int] = set()

    def base_difficulty(sound: str) -> str:
        return skills[sound].current_difficulty if sound in skills else "EASY"

    if target_sounds:
        # Build a difficulty-band plan and interleave it so the batch isn't grouped.
        n_warm = round(count * warmup_ratio)
        n_stretch = round(count * stretch_ratio)
        n_at = max(0, count - n_warm - n_stretch)
        pools = {"at-level": n_at, "warm-up": n_warm, "stretch": n_stretch}
        offset = {"at-level": 0, "warm-up": -1, "stretch": +1}
        bands: list[str] = []
        while sum(pools.values()) > 0:
            for b in ("at-level", "warm-up", "stretch"):
                if pools[b] > 0:
                    bands.append(b); pools[b] -= 1

        si = 0  # round-robin pointer across target sounds
        for band in bands:
            for k in range(len(target_sounds)):
                sound = target_sounds[(si + k) % len(target_sounds)]
                want = _shift_difficulty(base_difficulty(sound), offset[band])
                phrase = _pick(db, sound, want, recently | chosen_ids)
                if phrase is not None:
                    chosen.append((phrase, f"{band} for '{sound}' ({phrase.difficulty.value})"))
                    chosen_ids.add(phrase.id)
                    si = (si + k + 1) % len(target_sounds)
                    break

        # Top up any unfilled band slots using adjacent-difficulty fallback.
        guard = 0
        while len(chosen) < count and guard < count * len(target_sounds) + len(target_sounds):
            progressed = False
            for sound in target_sounds:
                if len(chosen) >= count:
                    break
                phrase = _pick_any(db, sound, base_difficulty(sound), recently | chosen_ids)
                if phrase is not None:
                    chosen.append((phrase, f"targets '{sound}' ({phrase.difficulty.value})"))
                    chosen_ids.add(phrase.id)
                    progressed = True
            guard += 1
            if not progressed:
                break

    # Cold start / final top-up: fill any remainder with unseen variety phrases.
    if len(chosen) < count:
        extra = select_unseen_phrases(db, user_id=user_id, count=count - len(chosen))
        cold = not target_sounds
        for p in extra:
            if p.id not in chosen_ids:
                chosen.append((p, "warm-up (building your profile)" if cold else "variety"))
                chosen_ids.add(p.id)

    chosen = chosen[:count]
    phrases = [p for p, _ in chosen]
    record_deliveries(db, user_id, phrases, DeliveryContext.GAME)
    db.commit()

    return {
        "user_id": user_id,
        "targeted_sounds": target_sounds,
        "count": len(chosen),
        "items": [{"phrase": p, "reason": r} for p, r in chosen],
    }


def get_practice_skill(db: Session, user_id: int) -> dict[str, Any]:
    """The child's mastery matrix — one row per practised sound, worst first."""
    skills = db.scalars(select(PracticeSkill).where(PracticeSkill.user_id == user_id)).all()
    rows = sorted(skills, key=lambda s: (s.rolling_ss if s.rolling_ss is not None else -1), reverse=True)
    return {
        "user_id": user_id,
        "sounds": [
            {
                "target_phoneme": s.target_phoneme,
                "current_difficulty": s.current_difficulty,
                "mastery_level": s.mastery_level,
                "attempts": s.attempts,
                "rolling_ss": round(s.rolling_ss, 2) if s.rolling_ss is not None else None,
                "last_practiced_at": s.last_practiced_at,
            }
            for s in rows
        ],
    }
