"""Tests for Phase 2 — adaptive targeted practice (planner + feedback loop)."""

import pytest

from tests.conftest import auth
from app.models.ailment import Ailment, AilmentType
from app.models.disfluency import Difficulty, DisfluencyPhrase
from app.models.disfluency_occurrence import DisfluencyOccurrence
from app.models.practice_attempt import PracticeAttempt
from app.models.practice_skill import PracticeSkill
from app.services import disfluency_tracker, practice_planner


# ── fixtures / helpers ────────────────────────────────────────────────────────

@pytest.fixture()
def ailment_type(db):
    a = Ailment(name="Stuttering")
    db.add(a); db.flush()
    at = AilmentType(name="General", ailment_id=a.id)
    db.add(at); db.commit(); db.refresh(at)
    return at


def make_phrase(db, ailment_type, sound, difficulty: Difficulty, n=1):
    out = []
    for i in range(n):
        p = DisfluencyPhrase(
            sentence=f"{sound} {difficulty.value} {i}",
            ailment_type_id=ailment_type.id,
            target_phoneme=sound,
            difficulty=difficulty,
        )
        db.add(p); out.append(p)
    db.commit()
    for p in out:
        db.refresh(p)
    return out if n > 1 else out[0]


def make_attempt(db, user, phrase, ss):
    a = PracticeAttempt(
        user_id=user.id, phrase_id=phrase.id,
        reference_phrase=phrase.sentence, transcript=phrase.sentence,
        stutter_frequency_percent=ss, fluency_score=max(0.0, 1 - ss / 10),
        disfluencies=[{"type": "block", "word": "shoe", "severity": "severe"}] if ss >= 8 else [],
    )
    db.add(a); db.commit(); db.refresh(a)
    return a


# ── feedback loop ─────────────────────────────────────────────────────────────

class TestProcessAttempt:
    def test_creates_and_updates_skill(self, db, patient_user, ailment_type):
        phrase = make_phrase(db, ailment_type, "s", Difficulty.EASY)
        practice_planner.process_attempt(db, make_attempt(db, patient_user, phrase, ss=1.0))
        skill = db.query(PracticeSkill).filter_by(user_id=patient_user.id, target_phoneme="s").one()
        assert skill.attempts == 1
        assert skill.consecutive_low == 1
        assert round(skill.rolling_ss, 2) == 1.0
        assert skill.current_difficulty == "EASY"

    def test_promotes_after_streak(self, db, patient_user, ailment_type):
        phrase = make_phrase(db, ailment_type, "s", Difficulty.EASY)
        for _ in range(3):                       # 3 consecutive clean attempts
            practice_planner.process_attempt(db, make_attempt(db, patient_user, phrase, ss=1.0))
        skill = db.query(PracticeSkill).filter_by(user_id=patient_user.id, target_phoneme="s").one()
        assert skill.current_difficulty == "MEDIUM"   # promoted EASY → MEDIUM
        assert skill.consecutive_low == 0             # reset after promotion

    def test_demotes_on_severe(self, db, patient_user, ailment_type):
        db.add(PracticeSkill(user_id=patient_user.id, target_phoneme="s", current_difficulty="MEDIUM"))
        db.commit()
        phrase = make_phrase(db, ailment_type, "s", Difficulty.MEDIUM)
        practice_planner.process_attempt(db, make_attempt(db, patient_user, phrase, ss=9.0))
        skill = db.query(PracticeSkill).filter_by(user_id=patient_user.id, target_phoneme="s").one()
        assert skill.current_difficulty == "EASY"     # demoted on severe %SS
        assert skill.mastery_level == "struggling"

    def test_feeds_disfluencies_into_profile(self, db, patient_user, ailment_type):
        phrase = make_phrase(db, ailment_type, "sh", Difficulty.EASY)
        practice_planner.process_attempt(db, make_attempt(db, patient_user, phrase, ss=9.0))
        occ = db.query(DisfluencyOccurrence).filter_by(user_id=patient_user.id, source="practice").all()
        assert len(occ) == 1
        assert occ[0].sound == "sh"


# ── selector ──────────────────────────────────────────────────────────────────

class TestBuildPracticeSet:
    def test_cold_start_warmup(self, db, patient_user, ailment_type):
        make_phrase(db, ailment_type, "s", Difficulty.EASY, n=6)
        result = practice_planner.build_practice_set(db, patient_user.id, count=3)
        assert result["targeted_sounds"] == []          # no profile yet
        assert result["count"] == 3
        assert all("warm-up" in it["reason"] for it in result["items"])

    def test_targets_profile_sounds(self, db, patient_user, ailment_type):
        # Seed the profile: child struggles with 'sh'.
        disfluency_tracker.record_occurrences(
            db, user_id=patient_user.id,
            disfluencies=[{"type": "block", "word": "shoe"}, {"type": "block", "word": "ship"}],
        )
        make_phrase(db, ailment_type, "sh", Difficulty.EASY, n=5)
        make_phrase(db, ailment_type, "s", Difficulty.EASY, n=5)   # distractor sound
        result = practice_planner.build_practice_set(db, patient_user.id, count=3)
        assert "sh" in result["targeted_sounds"]
        assert all(it["phrase"].target_phoneme == "sh" for it in result["items"])
        assert all("'sh'" in it["reason"] for it in result["items"])

    def test_warmup_atlevel_stretch_mix(self, db, patient_user, ailment_type):
        # Child works on 'sh' at MEDIUM; the batch should mix easier/harder tiers.
        disfluency_tracker.record_occurrences(
            db, user_id=patient_user.id, disfluencies=[{"type": "block", "word": "shoe"}],
        )
        db.add(PracticeSkill(
            user_id=patient_user.id, target_phoneme="sh", current_difficulty="MEDIUM",
            attempts=0, consecutive_low=0, mastery_level="practicing",
        ))
        db.commit()
        make_phrase(db, ailment_type, "sh", Difficulty.EASY, n=4)     # warm-up pool
        make_phrase(db, ailment_type, "sh", Difficulty.MEDIUM, n=4)   # at-level pool
        make_phrase(db, ailment_type, "sh", Difficulty.HARD, n=4)     # stretch pool

        result = practice_planner.build_practice_set(db, patient_user.id, count=5)
        diffs = {it["phrase"].difficulty.value for it in result["items"]}
        assert "MEDIUM" in diffs           # at-level present
        assert len(diffs) >= 2             # plus a warm-up and/or stretch tier
        bands = {it["reason"].split(" ")[0] for it in result["items"]}
        assert "at-level" in bands


# ── endpoints ─────────────────────────────────────────────────────────────────

class TestEndpoints:
    def test_targeted_phrases_patient_200(self, client, db, patient_user, patient_token, ailment_type):
        make_phrase(db, ailment_type, "s", Difficulty.EASY, n=6)
        r = client.get("/game/targeted-phrases?count=3", headers=auth(patient_token))
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 3
        assert "items" in body and len(body["items"]) == 3

    def test_targeted_phrases_doctor_403(self, client, doctor_token):
        assert client.get("/game/targeted-phrases", headers=auth(doctor_token)).status_code == 403

    def test_practice_skill_doctor_200(self, client, db, patient_user, doctor_token, ailment_type):
        phrase = make_phrase(db, ailment_type, "s", Difficulty.EASY)
        practice_planner.process_attempt(db, make_attempt(db, patient_user, phrase, ss=1.0))
        r = client.get(f"/v1/audio/patients/{patient_user.id}/practice-skill", headers=auth(doctor_token))
        assert r.status_code == 200
        body = r.json()
        assert body["sounds"][0]["target_phoneme"] == "s"

    def test_practice_skill_patient_403(self, client, patient_user, patient_token):
        r = client.get(f"/v1/audio/patients/{patient_user.id}/practice-skill", headers=auth(patient_token))
        assert r.status_code == 403
