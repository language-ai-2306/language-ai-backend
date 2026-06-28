"""Conversation session orchestration.

Owns the per-turn pipeline:
  1. Upload child audio → S3
  2. Transcribe + text-layer disfluency detection via ML service (/v1/analyse)
  3. Enrich with waveform-based acoustic disfluency detection (librosa, local)
  4. Build conversation history from DB
  5. Generate AI reply via Claude
  6. Synthesise AI voice via ML service TTS
  7. Upload AI audio → S3
  8. Persist turn to DB
"""

import base64
import logging
import re
import uuid
from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.analysis.audio_utils import preprocess_audio
from app.analysis.free_speech import enrich_with_acoustics
from app.models.conversation import ConversationHistory
from app.models.user import User
from app.services import ai_brain
from app.services import disfluency_tracker
from app.services.ml_client import MLServiceError, ml_client
from app.services.storage import presigned_url, upload_audio

logger = logging.getLogger(__name__)

DEFAULT_CHILD_AGE = 10

# How long the stored child-audio link stays directly openable. Presigned URLs
# expire; 7 days is the maximum AWS SigV4 allows. The API re-signs on every read,
# so served links never break — only the raw value saved in the DB ages out.
_STORED_URL_EXPIRY = 7 * 24 * 3600  # 7 days


def new_session_id() -> uuid.UUID:
    """Generate a fresh session UUID. Called once per conversation start."""
    return uuid.uuid4()


# Emoji / pictograph / symbol unicode blocks the TTS engine would mispronounce.
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # symbols, pictographs, emoji, supplemental
    "\U00002600-\U000027BF"  # misc symbols & dingbats
    "\U0001F1E6-\U0001F1FF"  # regional indicator (flags)
    "\U00002190-\U000021FF"  # arrows
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U00002B00-\U00002BFF"  # misc symbols & arrows
    "]+",
    flags=re.UNICODE,
)


def _clean_for_speech(text: str) -> str:
    """Make text safe to read aloud.

    The TTS engine reads punctuation symbols literally — e.g. Claude's
    "that's *awesome*" was being spoken as "that's asterisk awesome asterisk".
    Strip markdown emphasis/format characters and emoji, then tidy whitespace.
    Only the spoken copy is cleaned; the original ai_text is returned unchanged.
    """
    text = re.sub(r"[*_`~#>|]", "", text)   # markdown emphasis / formatting marks
    text = _EMOJI_RE.sub("", text)           # emoji & pictographs
    text = re.sub(r"[ \t]{2,}", " ", text)   # collapse runs of spaces
    return text.strip()


async def start_session_with_greeting(db: Session, user: User) -> dict[str, Any]:
    """Begin a conversation: Ollie greets the child and asks the first question.

    Generates a session id, produces Ollie's opening line via Claude, synthesises
    it to speech, uploads it to S3, and stores it as turn 1 (an AI-only turn with
    no child input). The child's first reply then arrives as turn 2.

    Returns a dict matching StartSessionResponse.
    """
    session_id = new_session_id()
    turn_number = 1

    # ── 1. Ollie's opening greeting + question (Claude) ──────────────────────
    age = _get_age(user)
    ai_text = ai_brain.generate_opening(age, db=db)

    # ── 2. Synthesise Ollie's voice (ML TTS) ─────────────────────────────────
    # AI audio is NOT stored in S3 — it's ephemeral and reproducible from
    # ai_text, so we return it inline (base64) for the client to play.
    # Clean markdown/emoji first so they aren't read aloud as symbols.
    ai_audio_bytes = await ml_client.synthesise(_clean_for_speech(ai_text))
    ai_audio_base64 = base64.b64encode(ai_audio_bytes).decode("ascii")

    # ── 3. Persist as turn 1 (AI-only: no child transcript/audio) ────────────
    turn = ConversationHistory(
        user_id=user.id,
        session_id=session_id,
        turn_number=turn_number,
        child_transcript=None,
        child_audio_url=None,
        ai_text=ai_text,
        disfluency_events=None,
    )
    db.add(turn)
    db.commit()
    db.refresh(turn)

    return {
        "session_id": session_id,
        "turn_number": turn_number,
        "text": ai_text,
        "audio": ai_audio_base64,
    }


async def process_turn(
    db: Session,
    session_id: uuid.UUID,
    user: User,
    wav_path: str,
    raw_audio_bytes: bytes,
    original_filename: str,
) -> dict[str, Any]:
    """Run one full conversation turn and persist the result.

    Args:
        db:                SQLAlchemy session.
        session_id:        UUID grouping all turns of this conversation.
        user:              The authenticated patient.
        wav_path:          Local path to the preprocessed 16 kHz mono WAV.
        raw_audio_bytes:   Raw bytes of the preprocessed WAV (for S3 upload).
        original_filename: Original upload filename (used for S3 extension).

    Returns:
        Dict matching TurnResponse schema.
    """
    turn_number = _next_turn_number(db, session_id)

    # ── 1. Upload child audio to S3 (private bucket) ─────────────────────────
    child_audio_object = upload_audio(
        file_bytes=raw_audio_bytes,
        session_id=str(session_id),
        turn_number=turn_number,
        speaker="child",
    )
    # Store a presigned (directly-openable) link, valid for up to 7 days.
    child_audio_url = presigned_url(child_audio_object, expires_in=_STORED_URL_EXPIRY)

    # ── 2. Transcribe + text-layer disfluency detection (ML service) ────────
    ml_result = await ml_client.analyse(
        raw_audio_bytes, filename="processed.wav", content_type="audio/wav"
    )
    transcript: str = ml_result["transcript"]
    words: list[dict] = ml_result["words"]
    ml_disfluencies: list[dict] = ml_result["disfluencies"]

    # ── 3. Enrich with waveform-based acoustic detection (local, librosa) ───
    disfluencies = enrich_with_acoustics(words, ml_disfluencies, wav_path)

    # ── 4. Build conversation history from DB ────────────────────────────────
    history = _load_history(db, session_id)
    history.append({"role": "user", "content": transcript})

    # ── 5. Generate AI reply via Claude ──────────────────────────────────────
    age = _get_age(user)
    ai_text = ai_brain.generate_response(history, age, turn_number, disfluencies, db=db)

    # ── 6. Synthesise AI audio via ML service TTS ────────────────────────────
    # AI audio is NOT stored in S3 — it's ephemeral and reproducible from
    # ai_text, so we return it inline (base64) for the client to play.
    # Clean markdown/emoji first so they aren't read aloud as symbols.
    ai_audio_bytes = await ml_client.synthesise(_clean_for_speech(ai_text))
    ai_audio_base64 = base64.b64encode(ai_audio_bytes).decode("ascii")

    # ── 7. Persist turn to DB (child audio kept in S3; AI audio not stored) ──
    turn = ConversationHistory(
        user_id=user.id,
        session_id=session_id,
        turn_number=turn_number,
        child_transcript=transcript,
        child_audio_url=child_audio_url,  # presigned, directly openable (7-day)
        ai_text=ai_text,
        disfluency_events=disfluencies,
    )
    db.add(turn)
    db.commit()
    db.refresh(turn)

    # ── 8. Track disfluencies for the child's profile (drives targeted practice).
    # Secondary to the reply — never let a tracking error break the turn.
    try:
        disfluency_tracker.record_occurrences(
            db,
            user_id=user.id,
            disfluencies=disfluencies,
            source="conversation",
            session_id=session_id,
            turn_id=turn.id,
        )
    except Exception:  # noqa: BLE001
        logger.warning("disfluency tracking failed for turn %s", turn.id, exc_info=True)

    return {
        "turn_id": turn.id,
        "session_id": session_id,
        "turn_number": turn_number,
        "child_transcript": transcript,
        "child_audio_url": child_audio_url,  # same presigned link saved in the DB
        "text": ai_text,
        "audio": ai_audio_base64,
        "disfluency_count": len(disfluencies),
        "disfluencies": disfluencies,
    }


def get_session_report(db: Session, session_id: uuid.UUID) -> dict[str, Any]:
    turns = (
        db.query(ConversationHistory)
        .filter(ConversationHistory.session_id == session_id)
        .order_by(ConversationHistory.turn_number)
        .all()
    )
    return {
        "session_id": session_id,
        "total_turns": len(turns),
        "turns": [
            {
                "turn_number": t.turn_number,
                "child_transcript": t.child_transcript,
                "ai_text": t.ai_text,
                "child_audio_url": presigned_url(t.child_audio_url) if t.child_audio_url else None,
                "disfluency_count": len(t.disfluency_events or []),
                "disfluencies": t.disfluency_events or [],
            }
            for t in turns
        ],
    }


def list_patient_sessions(db: Session, user_id: int) -> dict[str, Any]:
    """Return a summary list of all sessions for a patient, newest first."""
    turns = (
        db.query(ConversationHistory)
        .filter(ConversationHistory.user_id == user_id)
        .order_by(ConversationHistory.created_at)
        .all()
    )

    # Group turns by session_id in Python — the table has no separate session row.
    buckets: dict[uuid.UUID, list[ConversationHistory]] = defaultdict(list)
    for t in turns:
        buckets[t.session_id].append(t)

    summaries = []
    for session_id, session_turns in buckets.items():
        total_dis = sum(len(t.disfluency_events or []) for t in session_turns)
        n = len(session_turns)
        summaries.append({
            "session_id": session_id,
            "started_at": session_turns[0].created_at,
            "last_active_at": session_turns[-1].created_at,
            "total_turns": n,
            "total_disfluencies": total_dis,
            "disfluency_rate": round(total_dis / n, 2) if n else 0.0,
        })

    summaries.sort(key=lambda s: s["last_active_at"], reverse=True)
    return {"sessions": summaries, "total": len(summaries)}


def end_session(
    db: Session, session_id: uuid.UUID, user_id: int
) -> dict[str, Any] | None:
    """Return a final breakdown for a session. Returns None if session not found.

    No write is needed — the flat conversation_history table implicitly tracks
    session state via turn timestamps. This just aggregates and returns stats.
    """
    turns = (
        db.query(ConversationHistory)
        .filter(
            ConversationHistory.session_id == session_id,
            ConversationHistory.user_id == user_id,
        )
        .order_by(ConversationHistory.turn_number)
        .all()
    )
    if not turns:
        return None

    all_events: list[dict] = []
    for t in turns:
        all_events.extend(t.disfluency_events or [])

    by_type: dict[str, int] = {}
    for ev in all_events:
        ev_type = ev.get("type", "unknown")
        by_type[ev_type] = by_type.get(ev_type, 0) + 1

    return {
        "session_id": session_id,
        "total_turns": len(turns),
        "total_disfluencies": len(all_events),
        "disfluency_breakdown": by_type,
        "started_at": turns[0].created_at,
        "ended_at": turns[-1].created_at,
    }


def get_patient_progress(
    db: Session, user_id: int, limit: int = 20
) -> dict[str, Any]:
    """Return disfluency trends across the patient's last `limit` sessions.

    Each point in `trend` represents one full session — oldest first so the
    caller can draw a left-to-right improvement chart.
    """
    turns = (
        db.query(ConversationHistory)
        .filter(ConversationHistory.user_id == user_id)
        .order_by(ConversationHistory.created_at)
        .all()
    )

    buckets: dict[uuid.UUID, list[ConversationHistory]] = defaultdict(list)
    for t in turns:
        buckets[t.session_id].append(t)

    points = []
    for session_id, session_turns in buckets.items():
        all_events: list[dict] = []
        by_type: dict[str, int] = {}
        for t in sorted(session_turns, key=lambda x: x.turn_number):
            for ev in (t.disfluency_events or []):
                all_events.append(ev)
                tp = ev.get("type", "unknown")
                by_type[tp] = by_type.get(tp, 0) + 1

        n = len(session_turns)
        points.append({
            "session_id": session_id,
            "date": session_turns[0].created_at,
            "total_turns": n,
            "total_disfluencies": len(all_events),
            "disfluencies_per_turn": round(len(all_events) / n, 2) if n else 0.0,
            "by_type": by_type,
        })

    # Sort oldest → newest, take last `limit` sessions.
    points.sort(key=lambda p: p["date"])
    points = points[-limit:]

    return {"user_id": user_id, "sessions_analysed": len(points), "trend": points}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _next_turn_number(db: Session, session_id: uuid.UUID) -> int:
    count = (
        db.query(ConversationHistory)
        .filter(ConversationHistory.session_id == session_id)
        .count()
    )
    return count + 1


def _load_history(db: Session, session_id: uuid.UUID) -> list[dict]:
    """Return the last 10 turns as alternating user/assistant messages."""
    past = (
        db.query(ConversationHistory)
        .filter(ConversationHistory.session_id == session_id)
        .order_by(ConversationHistory.turn_number)
        .limit(10)
        .all()
    )
    messages: list[dict] = []
    for t in past:
        if t.child_transcript:
            messages.append({"role": "user", "content": t.child_transcript})
        if t.ai_text:
            messages.append({"role": "assistant", "content": t.ai_text})
    return messages


def _get_age(user: User) -> int:
    """The child's age from their date of birth, clamped to the 5–15 range the
    conversation persona is calibrated for. Falls back to a default if no DOB."""
    dob = getattr(user, "dob", None)
    if dob is None:
        return DEFAULT_CHILD_AGE
    today = date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return max(5, min(15, age))
