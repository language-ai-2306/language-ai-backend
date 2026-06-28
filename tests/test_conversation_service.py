"""Unit tests for the pure-Python service functions in conversation.py.

Uses the SQLite test DB — no ML service, no S3, no Claude calls.
Only the three aggregation/read functions are tested here:
  list_patient_sessions, end_session, get_patient_progress.
"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.services import conversation as svc
from tests.conftest import make_turn


# ── list_patient_sessions ─────────────────────────────────────────────────────

class TestListPatientSessions:
    def test_empty_when_no_turns(self, db: Session, patient_user):
        result = svc.list_patient_sessions(db, patient_user.id)
        assert result["sessions"] == []
        assert result["total"] == 0

    def test_single_session_single_turn(self, db: Session, patient_user):
        sid = uuid.uuid4()
        make_turn(db, patient_user, sid, 1)
        result = svc.list_patient_sessions(db, patient_user.id)
        assert result["total"] == 1
        assert str(result["sessions"][0]["session_id"]) == str(sid)

    def test_counts_turns_per_session(self, db: Session, patient_user):
        sid = uuid.uuid4()
        make_turn(db, patient_user, sid, 1)
        make_turn(db, patient_user, sid, 2)
        make_turn(db, patient_user, sid, 3)
        result = svc.list_patient_sessions(db, patient_user.id)
        assert result["sessions"][0]["total_turns"] == 3

    def test_two_sessions_returned(self, db: Session, patient_user):
        make_turn(db, patient_user, uuid.uuid4(), 1)
        make_turn(db, patient_user, uuid.uuid4(), 1)
        result = svc.list_patient_sessions(db, patient_user.id)
        assert result["total"] == 2

    def test_disfluency_totals_aggregated(self, db: Session, patient_user):
        sid = uuid.uuid4()
        make_turn(db, patient_user, sid, 1, disfluency_events=[
            {"type": "repetition", "word": "the", "timestamp_start": 0.0, "timestamp_end": 0.6, "severity": "mild"},
            {"type": "block",      "word": "want","timestamp_start": 1.0, "timestamp_end": 1.5, "severity": "mild"},
        ])
        make_turn(db, patient_user, sid, 2, disfluency_events=[
            {"type": "interjection", "word": "um", "timestamp_start": 0.0, "timestamp_end": 0.3, "severity": "mild"},
        ])
        result = svc.list_patient_sessions(db, patient_user.id)
        assert result["sessions"][0]["total_disfluencies"] == 3

    def test_disfluency_rate_computed(self, db: Session, patient_user):
        sid = uuid.uuid4()
        make_turn(db, patient_user, sid, 1, disfluency_events=[{"type": "block", "word": "a", "timestamp_start": 0.0, "timestamp_end": 0.5, "severity": "mild"}])
        make_turn(db, patient_user, sid, 2, disfluency_events=[])  # 0 disfluencies
        result = svc.list_patient_sessions(db, patient_user.id)
        assert result["sessions"][0]["disfluency_rate"] == 0.5  # 1 disfluency / 2 turns

    def test_returns_all_sessions_present(self, db: Session, patient_user):
        # Ordering by last_active_at desc is correct in production (PostgreSQL
        # has microsecond precision). SQLite's 1-second resolution makes strict
        # order testing unreliable in tests, so we only verify both sessions exist.
        sid1 = uuid.uuid4()
        sid2 = uuid.uuid4()
        make_turn(db, patient_user, sid1, 1)
        make_turn(db, patient_user, sid2, 1)
        result = svc.list_patient_sessions(db, patient_user.id)
        returned_ids = {str(s["session_id"]) for s in result["sessions"]}
        assert str(sid1) in returned_ids
        assert str(sid2) in returned_ids
        assert result["total"] == 2

    def test_only_own_sessions_returned(self, db: Session, patient_user, doctor_user):
        make_turn(db, patient_user, uuid.uuid4(), 1)
        make_turn(db, doctor_user, uuid.uuid4(), 1)
        result = svc.list_patient_sessions(db, patient_user.id)
        assert result["total"] == 1


# ── end_session ───────────────────────────────────────────────────────────────

class TestEndSession:
    def test_returns_none_for_unknown_session(self, db: Session, patient_user):
        result = svc.end_session(db, uuid.uuid4(), patient_user.id)
        assert result is None

    def test_returns_none_for_another_users_session(self, db: Session, patient_user, doctor_user):
        sid = uuid.uuid4()
        make_turn(db, doctor_user, sid, 1)
        result = svc.end_session(db, sid, patient_user.id)
        assert result is None

    def test_returns_correct_turn_count(self, db: Session, patient_user):
        sid = uuid.uuid4()
        make_turn(db, patient_user, sid, 1)
        make_turn(db, patient_user, sid, 2)
        result = svc.end_session(db, sid, patient_user.id)
        assert result["total_turns"] == 2

    def test_disfluency_breakdown_by_type(self, db: Session, patient_user):
        sid = uuid.uuid4()
        make_turn(db, patient_user, sid, 1, disfluency_events=[
            {"type": "repetition",  "word": "go", "timestamp_start": 0.0, "timestamp_end": 0.6, "severity": "mild"},
            {"type": "block",       "word": "I",  "timestamp_start": 1.0, "timestamp_end": 1.5, "severity": "mild"},
            {"type": "repetition",  "word": "go", "timestamp_start": 2.0, "timestamp_end": 2.6, "severity": "mild"},
        ])
        result = svc.end_session(db, sid, patient_user.id)
        assert result["disfluency_breakdown"]["repetition"] == 2
        assert result["disfluency_breakdown"]["block"] == 1

    def test_empty_session_has_zero_disfluencies(self, db: Session, patient_user):
        sid = uuid.uuid4()
        make_turn(db, patient_user, sid, 1, disfluency_events=[])
        result = svc.end_session(db, sid, patient_user.id)
        assert result["total_disfluencies"] == 0
        assert result["disfluency_breakdown"] == {}

    def test_started_and_ended_at_populated(self, db: Session, patient_user):
        sid = uuid.uuid4()
        make_turn(db, patient_user, sid, 1)
        make_turn(db, patient_user, sid, 2)
        result = svc.end_session(db, sid, patient_user.id)
        assert result["started_at"] is not None
        assert result["ended_at"] is not None


# ── get_patient_progress ──────────────────────────────────────────────────────

class TestGetPatientProgress:
    def test_empty_when_no_sessions(self, db: Session, patient_user):
        result = svc.get_patient_progress(db, patient_user.id)
        assert result["sessions_analysed"] == 0
        assert result["trend"] == []

    def test_trend_oldest_first(self, db: Session, patient_user):
        sid1 = uuid.uuid4()
        sid2 = uuid.uuid4()
        make_turn(db, patient_user, sid1, 1)
        make_turn(db, patient_user, sid2, 1)
        result = svc.get_patient_progress(db, patient_user.id)
        # sid1 inserted first → should appear first in trend
        assert str(result["trend"][0]["session_id"]) == str(sid1)

    def test_disfluencies_per_turn_computed(self, db: Session, patient_user):
        sid = uuid.uuid4()
        make_turn(db, patient_user, sid, 1, disfluency_events=[
            {"type": "block", "word": "I", "timestamp_start": 0.0, "timestamp_end": 0.5, "severity": "mild"},
            {"type": "block", "word": "I", "timestamp_start": 1.0, "timestamp_end": 1.5, "severity": "mild"},
        ])
        make_turn(db, patient_user, sid, 2, disfluency_events=[])
        result = svc.get_patient_progress(db, patient_user.id)
        assert result["trend"][0]["disfluencies_per_turn"] == 1.0  # 2 disfluencies / 2 turns

    def test_by_type_breakdown(self, db: Session, patient_user):
        sid = uuid.uuid4()
        make_turn(db, patient_user, sid, 1, disfluency_events=[
            {"type": "repetition",   "word": "go", "timestamp_start": 0.0, "timestamp_end": 0.6, "severity": "mild"},
            {"type": "interjection", "word": "um", "timestamp_start": 1.0, "timestamp_end": 1.3, "severity": "mild"},
            {"type": "repetition",   "word": "go", "timestamp_start": 2.0, "timestamp_end": 2.6, "severity": "mild"},
        ])
        result = svc.get_patient_progress(db, patient_user.id)
        by_type = result["trend"][0]["by_type"]
        assert by_type["repetition"] == 2
        assert by_type["interjection"] == 1

    def test_limit_applied(self, db: Session, patient_user):
        for _ in range(5):
            make_turn(db, patient_user, uuid.uuid4(), 1)
        result = svc.get_patient_progress(db, patient_user.id, limit=3)
        assert result["sessions_analysed"] == 3

    def test_user_id_in_response(self, db: Session, patient_user):
        result = svc.get_patient_progress(db, patient_user.id)
        assert result["user_id"] == patient_user.id
