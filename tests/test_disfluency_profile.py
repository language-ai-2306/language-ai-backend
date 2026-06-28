"""Tests for the disfluency profile feature (tracker service + doctor endpoint)."""

import uuid

from tests.conftest import auth
from app.models.disfluency_occurrence import DisfluencyOccurrence
from app.services import disfluency_tracker


def _events():
    """A turn's worth of disfluency events, as the pipeline emits them.

    Onset extraction is digraph-aware: 'shoe'→'sh', 'three'→'th', 'sun'/'sip'→'s'.
    """
    return [
        {"type": "Block", "word": "shoe", "severity": "severe", "timestamp_start": 1.0, "timestamp_end": 1.4},  # sh
        {"type": "repetition", "word": "shop", "severity": "mild"},      # sh
        {"type": "prolongation", "word": "three", "severity": "moderate"},  # th
        {"type": "interjection", "word": "um"},          # no severity → weight 1
        {"type": "", "word": "ignored"},                  # blank type → skipped
    ]


def test_onset_extraction_is_digraph_aware():
    f = disfluency_tracker.extract_onset_sound
    assert f("think") == "th"
    assert f("shoe") == "sh"
    assert f("street") == "str"
    assert f("snake") == "sn"
    assert f("sun") == "s"        # no cluster → first letter
    assert f("apple") == "a"
    assert f(None) is None


class TestRecordOccurrences:
    def test_inserts_one_row_per_valid_event(self, db, patient_user):
        n = disfluency_tracker.record_occurrences(
            db, user_id=patient_user.id, disfluencies=_events(), session_id=uuid.uuid4(), turn_id=None,
        )
        assert n == 4  # the blank-type event is skipped
        rows = db.query(DisfluencyOccurrence).all()
        assert len(rows) == 4

    def test_derives_onset_sound_and_normalises_type(self, db, patient_user):
        disfluency_tracker.record_occurrences(
            db, user_id=patient_user.id, disfluencies=_events(),
        )
        block = db.query(DisfluencyOccurrence).filter_by(word="shoe").one()
        assert block.sound == "sh"            # digraph onset of "shoe"
        assert block.disfluency_type == "block"  # lowercased
        assert block.severity == "severe"

    def test_empty_list_stores_nothing(self, db, patient_user):
        assert disfluency_tracker.record_occurrences(db, user_id=patient_user.id, disfluencies=[]) == 0
        assert db.query(DisfluencyOccurrence).count() == 0


class TestGetProfile:
    def test_aggregates_and_ranks_by_severity(self, db, patient_user):
        disfluency_tracker.record_occurrences(db, user_id=patient_user.id, disfluencies=_events())
        profile = disfluency_tracker.get_disfluency_profile(db, patient_user.id)

        assert profile["total_occurrences"] == 4
        # 'sh' appears 2x (shoe severe=3, shop mild=1) → score 4, the top sound.
        top_sound = profile["by_sound"][0]
        assert top_sound["value"] == "sh"
        assert top_sound["count"] == 2
        assert top_sound["severity_score"] == 4
        # by_type is present and ranked.
        types = {b["value"] for b in profile["by_type"]}
        assert {"block", "repetition", "prolongation", "interjection"} <= types

    def test_empty_profile(self, db, patient_user):
        profile = disfluency_tracker.get_disfluency_profile(db, patient_user.id)
        assert profile["total_occurrences"] == 0
        assert profile["by_sound"] == []
        assert profile["last_seen"] is None


class TestProfileEndpoint:
    def test_doctor_gets_200(self, client, db, patient_user, doctor_token):
        disfluency_tracker.record_occurrences(db, user_id=patient_user.id, disfluencies=_events())
        r = client.get(
            f"/v1/conversation/patients/{patient_user.id}/disfluency-profile",
            headers=auth(doctor_token),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total_occurrences"] == 4
        assert data["by_sound"][0]["value"] == "sh"

    def test_patient_gets_403(self, client, patient_user, patient_token):
        r = client.get(
            f"/v1/conversation/patients/{patient_user.id}/disfluency-profile",
            headers=auth(patient_token),
        )
        assert r.status_code == 403

    def test_unauthenticated_gets_401(self, client, patient_user):
        r = client.get(f"/v1/conversation/patients/{patient_user.id}/disfluency-profile")
        assert r.status_code == 401
