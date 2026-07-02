"""Game-strategy registry — one unified interface for every single-shot game.

Each game (Repeat After Me, Read It Loud, Picture Talk, Story Teller) implements
the same `GameStrategy` interface, so the `/v1/exercises/{game}` router is thin and
identical for all of them. Two families:

  * ``ContentBankGame``      — the three new games. Prompts come from
                               ``disfluency_phrase`` (filtered by exercise_type +
                               difficulty) via the ``exercise_content`` service;
                               attempts are NOT persisted, but still feed the
                               disfluency profile.
  * ``RepeatAfterMeGame``    — delegates to the existing RAM services
                               (practice_planner + practice + per-sound mastery),
                               so the unified API serves RAM without duplicating its
                               data model. The legacy /v1/repeat-after-me routes stay.

Talk with Ollie is intentionally NOT here — it is a stateful, multi-turn dialogue
and keeps its own /v1/conversation endpoints.

Scoring reuses the two existing paths verbatim:
  * reference-based (Read It Loud, RAM) → app.api.audio._analyse_recording
  * reference-free  (Picture Talk, Story Teller) → app.api.audio._analyse_free_recording
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.disfluency import Difficulty, DisfluencyPhrase
from app.models.exercise import ExerciseType
from app.models.practice_plan import PlanItemSession
from app.models.user import User
from app.services import disfluency_tracker, exercise_content as content_service
from app.services import practice_planner, storage
from app.services import practice as practice_service

logger = logging.getLogger(__name__)

# S3 practice audio links are served presigned; keep them openable for a week.
_AUDIO_URL_EXPIRY = 7 * 24 * 3600


def _age_from_dob(user: User) -> int:
    """Child's age from DOB, clamped to 5–15 (default 8 when unknown)."""
    dob = getattr(user, "dob", None)
    if dob is None:
        return 8
    today = date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return max(5, min(15, age))


def _upload_audio(wav_bytes: bytes, user_id: int) -> Optional[str]:
    """Best-effort upload of the recording; storage hiccups must not lose the analysis."""
    try:
        canonical = storage.upload_practice_audio(wav_bytes, user_id)
        return storage.presigned_url(canonical, expires_in=_AUDIO_URL_EXPIRY)
    except Exception:  # noqa: BLE001 - storage is non-critical to persistence
        logger.warning("exercise audio upload failed; storing attempt without audio_url")
        return None


def _result_response(attempt_id: Optional[int], exercise_type: ExerciseType, content_id: Optional[str],
                     result: dict[str, Any], audio_url: Optional[str]) -> dict[str, Any]:
    return {
        "attempt_id": attempt_id,
        "exercise_type": exercise_type.value,
        "content_id": content_id,
        "transcript": result.get("transcript"),
        "scores": result.get("scores", {}),
        "disfluencies": result.get("disfluencies", []),
        "should_retry": result.get("should_retry"),
        "message": result.get("message"),
        "audio_url": audio_url,
    }


@dataclass
class ContentDTO:
    """What `next_content` returns: enough to render the prompt and score the reply."""
    content_id: str               # phrase id as a string
    exercise_type: ExerciseType
    text: str                     # the text shown to the child (phrase/passage/story/prompt)
    image_url: Optional[str]      # Picture Talk only; None otherwise
    tts_text: Optional[str]       # text to speak aloud (RAM phrase / story), or None
    reason: Optional[str] = None  # why chosen (RAM personalisation)


class GameStrategy:
    slug: str
    exercise_type: ExerciseType

    def intro(self, name: str, character: str) -> str:
        raise NotImplementedError

    def next_content(self, db: Session, user: User, difficulty: Difficulty,
                     target_phoneme: Optional[str] = None) -> Optional[ContentDTO]:
        raise NotImplementedError

    async def submit(self, db: Session, user: User, content_id: str, audio_bytes: bytes,
                     filename: Optional[str], use_mock: bool,
                     session: Optional[PlanItemSession] = None) -> dict[str, Any]:
        raise NotImplementedError


# ── The three new content-driven games ───────────────────────────────────────
class ContentBankGame(GameStrategy):
    def __init__(
        self,
        slug: str,
        exercise_type: ExerciseType,
        scoring: str,  # "reference" | "free"
        intro_template: str,
        text_from: Callable[[Any], str],
        image_from: Callable[[Any], Optional[str]],
        tts_from: Callable[[Any], Optional[str]],
        reference_from: Callable[[Any], Optional[str]],
    ):
        self.slug = slug
        self.exercise_type = exercise_type
        self.scoring = scoring
        self._intro = intro_template
        self._text_from = text_from
        self._image_from = image_from
        self._tts_from = tts_from
        self._reference_from = reference_from

    def intro(self, name: str, character: str) -> str:
        return self._intro.format(name=name, char=character)

    def next_content(self, db: Session, user: User, difficulty: Difficulty,
                     target_phoneme: Optional[str] = None) -> Optional[ContentDTO]:
        phrase = content_service.select_content(db, self.exercise_type, difficulty, target_phoneme)
        if phrase is None:
            return None
        return ContentDTO(
            content_id=str(phrase.guid),
            exercise_type=self.exercise_type,
            text=self._text_from(phrase),
            image_url=self._image_from(phrase),
            tts_text=self._tts_from(phrase),
        )

    async def submit(self, db: Session, user: User, content_id: str, audio_bytes: bytes,
                     filename: Optional[str], use_mock: bool,
                     session: Optional[PlanItemSession] = None) -> dict[str, Any]:
        # Import here to avoid a circular import at module load (audio → services).
        from app.api.audio import _analyse_free_recording, _analyse_recording

        phrase = content_service.get_content(db, content_id)
        if phrase is None or phrase.exercise_type != self.exercise_type.value:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Exercise content not found")

        child_age = _age_from_dob(user)
        reference = self._reference_from(phrase) or ""
        if self.scoring == "reference":
            result, wav_bytes = await _analyse_recording(
                audio_bytes, filename, reference, child_age, use_mock
            )
        else:
            result, wav_bytes = await _analyse_free_recording(
                audio_bytes, filename, child_age, use_mock
            )

        audio_url = _upload_audio(wav_bytes, user.id)

        # Persist the attempt — the single source of truth for fluency data, for
        # both free and planned play. `plan_item_id` marks a planned attempt.
        attempt = practice_service.record_attempt(
            db,
            user_id=user.id,
            reference_phrase=reference or self._text_from(phrase) or "",
            result=result,
            phrase_id=phrase.id,
            child_age=child_age,
            audio_url=audio_url,
            exercise_type=self.exercise_type.value,
            plan_item_session_id=(session.id if session is not None else None),
        )

        # Feed the shared disfluency profile (secondary — never break the response).
        try:
            disfluency_tracker.record_occurrences(
                db,
                user_id=user.id,
                disfluencies=result.get("disfluencies"),
                source=self.slug.replace("-", "_"),
            )
        except Exception:  # noqa: BLE001
            logger.warning("disfluency tracking failed for %s attempt", self.slug, exc_info=True)

        return _result_response(attempt.guid, self.exercise_type, content_id, result, audio_url)


# ── Repeat After Me — unified surface over the existing RAM services ──────────
class RepeatAfterMeGame(GameStrategy):
    slug = "repeat-after-me"
    exercise_type = ExerciseType.REPEAT_AFTER_ME
    _intro = (
        "Hi {name}! I'm {char}. Let's play Repeat After Me! "
        "I'll say a phrase, then it's your turn to say it back."
    )

    def intro(self, name: str, character: str) -> str:
        return self._intro.format(name=name, char=character)

    def next_content(self, db: Session, user: User, difficulty: Difficulty,
                     target_phoneme: Optional[str] = None) -> Optional[ContentDTO]:
        if target_phoneme:
            # Plan pinned a specific sound → serve a phrase for exactly that phoneme.
            phrase = content_service.select_content(
                db, self.exercise_type, difficulty, target_phoneme
            )
            if phrase is None:
                return None
            return ContentDTO(
                content_id=str(phrase.guid),
                exercise_type=self.exercise_type,
                text=phrase.sentence,
                image_url=None,
                tts_text=phrase.sentence,
                reason=f"targeting /{target_phoneme}/",
            )
        # Free practice → the existing adaptive planner (personalised to problem sounds).
        result = practice_planner.next_phrase(db, user.id, difficulty)
        if result is None:
            return None
        phrase = result["phrase"]
        return ContentDTO(
            content_id=str(phrase.guid),  # phrase GUID (unified content_id)
            exercise_type=self.exercise_type,
            text=phrase.sentence,
            image_url=None,
            tts_text=phrase.sentence,
            reason=result.get("reason"),
        )

    async def submit(self, db: Session, user: User, content_id: str, audio_bytes: bytes,
                     filename: Optional[str], use_mock: bool,
                     session: Optional[PlanItemSession] = None) -> dict[str, Any]:
        from app.api.audio import _analyse_recording

        phrase = content_service.get_content(db, content_id)  # by GUID
        if phrase is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Phrase not found")

        child_age = _age_from_dob(user)
        result, wav_bytes = await _analyse_recording(
            audio_bytes, filename, phrase.sentence, child_age, use_mock
        )
        audio_url = _upload_audio(wav_bytes, user.id)

        attempt = practice_service.record_attempt(
            db,
            user_id=user.id,
            reference_phrase=result["reference_phrase"],
            result=result,
            phrase_id=phrase.id,
            child_age=child_age,
            audio_url=audio_url,
            exercise_type=self.exercise_type.value,
            plan_item_session_id=(session.id if session is not None else None),
        )
        # RAM's own feedback loop feeds the profile AND updates per-sound mastery.
        try:
            practice_planner.process_attempt(db, attempt)
        except Exception:  # noqa: BLE001
            logger.warning("RAM feedback loop failed for attempt %s", attempt.id, exc_info=True)

        return _result_response(attempt.guid, self.exercise_type, content_id, result, audio_url)


# ── Registry ─────────────────────────────────────────────────────────────────
# The text/image/tts/reference builders receive a DisfluencyPhrase. For every game
# the display text lives in `phrase.sentence`; Picture Talk also uses `phrase.image_url`.
_READ_IT_LOUD = ContentBankGame(
    slug="read-it-loud",
    exercise_type=ExerciseType.READ_IT_LOUD,
    scoring="reference",  # child reads a known passage → compare to it
    intro_template="Hi {name}! I'm {char}. Let's play Read It Loud! I'll show you something to read — read it out loud in your best voice.",
    text_from=lambda ph: ph.sentence,
    image_from=lambda ph: None,
    tts_from=lambda ph: None,  # reading exercise — the child reads the text, we don't read it to them
    reference_from=lambda ph: ph.sentence,
)

_PICTURE_TALK = ContentBankGame(
    slug="picture-talk",
    exercise_type=ExerciseType.PICTURE_TALK,
    scoring="free",  # open-ended description → fluency-only, no reference
    intro_template="Hi {name}! I'm {char}. Let's play Picture Talk! I'll show you a picture — tell me all about what you see.",
    text_from=lambda ph: ph.sentence,       # the describe-prompt question
    image_from=lambda ph: ph.image_url,
    tts_from=lambda ph: None,  # visual exercise — nothing to voice; the image + text prompt suffice
    reference_from=lambda ph: None,
)

_STORY_TELLER = ContentBankGame(
    slug="story-teller",
    exercise_type=ExerciseType.STORY_TELLER,
    scoring="free",  # open-ended retell → fluency-only, no reference
    intro_template="Hi {name}! I'm {char}. Let's play Story Teller! Listen to the story, then tell it back to me in your own words.",
    text_from=lambda ph: ph.sentence,
    image_from=lambda ph: None,
    tts_from=lambda ph: ph.sentence,  # the child hears the story, then retells
    reference_from=lambda ph: None,
)

REGISTRY: dict[str, GameStrategy] = {
    "read-it-loud": _READ_IT_LOUD,
    "picture-talk": _PICTURE_TALK,
    "story-teller": _STORY_TELLER,
    "repeat-after-me": RepeatAfterMeGame(),
}


def get_strategy(game: str) -> GameStrategy:
    strategy = REGISTRY.get(game)
    if strategy is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Unknown game '{game}'. Valid games: {', '.join(REGISTRY)}",
        )
    return strategy
