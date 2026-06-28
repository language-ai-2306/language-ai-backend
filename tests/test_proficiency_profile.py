"""Proficiency-test disfluencies feed the unified profile (source='proficiency')."""

import pytest

from tests.conftest import auth
from app.models.ailment import Ailment, AilmentType
from app.models.disfluency import Difficulty, DisfluencyPhrase
from app.models.disfluency_occurrence import DisfluencyOccurrence
from app.models.proficiency import ProficiencyTest


@pytest.fixture()
def phrase(db):
    a = Ailment(name="Stuttering"); db.add(a); db.flush()
    at = AilmentType(name="General", ailment_id=a.id); db.add(at); db.flush()
    p = DisfluencyPhrase(
        sentence="She sells shells", ailment_type_id=at.id,
        target_phoneme="sh", difficulty=Difficulty.EASY,
    )
    db.add(p); db.commit(); db.refresh(p)
    return p


def _test_row(db, user):
    t = ProficiencyTest(user_id=user.id, is_completed=False)
    db.add(t); db.commit(); db.refresh(t)
    return t


def test_submit_with_disfluencies_feeds_profile(client, db, patient_user, patient_token, phrase):
    test = _test_row(db, patient_user)
    r = client.post(
        f"/proficiency-test/{test.id}/submit",
        json={"responses": [{
            "phrase_id": phrase.id, "score": 0.5,
            "disfluencies": [{"type": "block", "word": "shoe", "severity": "severe"}],
        }]},
        headers=auth(patient_token),
    )
    assert r.status_code == 200
    occ = db.query(DisfluencyOccurrence).filter_by(user_id=patient_user.id, source="proficiency").all()
    assert len(occ) == 1
    assert occ[0].sound == "sh"


def test_submit_without_disfluencies_is_noop(client, db, patient_user, patient_token, phrase):
    test = _test_row(db, patient_user)
    r = client.post(
        f"/proficiency-test/{test.id}/submit",
        json={"responses": [{"phrase_id": phrase.id, "is_correct": True}]},
        headers=auth(patient_token),
    )
    assert r.status_code == 200
    assert db.query(DisfluencyOccurrence).filter_by(source="proficiency").count() == 0
