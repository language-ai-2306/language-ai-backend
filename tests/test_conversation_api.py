"""Integration tests for the /v1/conversation endpoints.

External dependencies (ML service, S3, Claude) are mocked. The DB uses the
SQLite test fixture from conftest.py, so these tests have no network calls.
"""

import io
import shutil
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import auth, make_turn


# ── Shared mock context ───────────────────────────────────────────────────────

FAKE_SESSION_TURN = {
    "turn_id": 1,
    "session_id": uuid.uuid4(),
    "turn_number": 1,
    "child_transcript": "I like dogs",
    "child_audio_url": "https://s3.example.com/child.wav",
    "text": "That's cool! What kind of dog do you like?",
    "audio": "RkFLRUFVRElP",
    "disfluency_count": 0,
    "disfluencies": [],
}


def _audio_upload(content: bytes = b"fake wav") -> dict:
    return {"audio": ("recording.wav", io.BytesIO(content), "audio/wav")}


# ── POST /v1/conversation/session ──────────────────────────────────────────

class TestStartSession:
    @pytest.fixture(autouse=True)
    def mock_greeting_externals(self):
        """Stub Ollie's opening (Claude), voice synthesis (ML) and S3 upload so
        start-session tests stay offline. Real session ids are still generated."""
        with patch(
            "app.services.conversation.ai_brain.generate_opening",
            return_value="Hi, I'm Ollie! What's your favourite animal?",
        ), patch(
            "app.services.conversation.ml_client.synthesise",
            new_callable=AsyncMock, return_value=b"FAKEAUDIO",
        ), patch(
            "app.services.conversation.upload_audio",
            return_value="https://s3.example/ai.mp3",
        ):
            yield

    def test_patient_gets_201(self, client, patient_token):
        response = client.post("/v1/conversation/session/start", headers=auth(patient_token))
        assert response.status_code == 201

    def test_returns_greeting_and_audio(self, client, patient_token):
        data = client.post("/v1/conversation/session/start", headers=auth(patient_token)).json()
        assert data["turn_number"] == 1
        assert data["text"]
        assert data["audio"]

    def test_returns_session_id_uuid(self, client, patient_token):
        response = client.post("/v1/conversation/session/start", headers=auth(patient_token))
        data = response.json()
        assert "session_id" in data
        # Should be parseable as UUID
        uuid.UUID(data["session_id"])

    def test_each_call_returns_unique_session_id(self, client, patient_token):
        r1 = client.post("/v1/conversation/session/start", headers=auth(patient_token))
        r2 = client.post("/v1/conversation/session/start", headers=auth(patient_token))
        assert r1.json()["session_id"] != r2.json()["session_id"]

    def test_doctor_gets_403(self, client, doctor_token):
        response = client.post("/v1/conversation/session/start", headers=auth(doctor_token))
        assert response.status_code == 403

    def test_unauthenticated_gets_401(self, client):
        response = client.post("/v1/conversation/session/start")
        assert response.status_code == 401


# ── POST /v1/conversation/session/{id}/reply ────────────────────────────────

class TestSubmitTurn:
    @pytest.fixture(autouse=True)
    def mock_process_turn(self):
        """Mock the entire process_turn coroutine — avoids ML/S3/Claude calls.

        preprocess_audio is given a side_effect that copies raw→processed so
        the router's subsequent `open(wav_path, "rb")` finds the file it expects.
        """
        with patch(
            "app.api.conversation.conv_service.process_turn",
            new_callable=AsyncMock,
        ) as mock_pt, patch(
            "app.api.conversation.preprocess_audio",
            side_effect=lambda src, dst: shutil.copy(src, dst),
        ), patch(
            "app.api.conversation.validate_audio"
        ):
            mock_pt.return_value = FAKE_SESSION_TURN
            yield mock_pt

    def test_patient_gets_200(self, client, patient_token):
        sid = uuid.uuid4()
        response = client.post(
            f"/v1/conversation/session/{sid}/reply",
            files=_audio_upload(),
            headers=auth(patient_token),
        )
        assert response.status_code == 200

    def test_response_has_required_fields(self, client, patient_token):
        sid = uuid.uuid4()
        response = client.post(
            f"/v1/conversation/session/{sid}/reply",
            files=_audio_upload(),
            headers=auth(patient_token),
        )
        data = response.json()
        for field in ("turn_id", "session_id", "turn_number", "child_transcript",
                      "child_audio_url", "text", "audio",
                      "disfluency_count", "disfluencies"):
            assert field in data, f"missing field: {field}"

    def test_empty_audio_returns_400(self, client, patient_token):
        sid = uuid.uuid4()
        response = client.post(
            f"/v1/conversation/session/{sid}/reply",
            files={"audio": ("empty.wav", io.BytesIO(b""), "audio/wav")},
            headers=auth(patient_token),
        )
        assert response.status_code == 400

    def test_doctor_gets_403(self, client, doctor_token):
        sid = uuid.uuid4()
        response = client.post(
            f"/v1/conversation/session/{sid}/reply",
            files=_audio_upload(),
            headers=auth(doctor_token),
        )
        assert response.status_code == 403

    def test_unauthenticated_gets_401(self, client):
        sid = uuid.uuid4()
        response = client.post(
            f"/v1/conversation/session/{sid}/reply",
            files=_audio_upload(),
        )
        assert response.status_code == 401


# ── POST /v1/conversation/session/{id}/end ──────────────────────────────────

class TestEndSession:
    def test_returns_200_when_session_exists(self, client, db, patient_user, patient_token):
        sid = uuid.uuid4()
        make_turn(db, patient_user, sid, 1)
        response = client.post(
            f"/v1/conversation/session/{sid}/end",
            headers=auth(patient_token),
        )
        assert response.status_code == 200

    def test_response_fields(self, client, db, patient_user, patient_token):
        sid = uuid.uuid4()
        make_turn(db, patient_user, sid, 1)
        data = client.post(
            f"/v1/conversation/session/{sid}/end",
            headers=auth(patient_token),
        ).json()
        for field in ("session_id", "total_turns", "total_disfluencies",
                      "disfluency_breakdown", "started_at", "ended_at"):
            assert field in data, f"missing field: {field}"

    def test_returns_404_for_unknown_session(self, client, patient_token):
        response = client.post(
            f"/v1/conversation/session/{uuid.uuid4()}/end",
            headers=auth(patient_token),
        )
        assert response.status_code == 404

    def test_returns_404_for_other_users_session(self, client, db, doctor_user, patient_token):
        sid = uuid.uuid4()
        make_turn(db, doctor_user, sid, 1)
        response = client.post(
            f"/v1/conversation/session/{sid}/end",
            headers=auth(patient_token),
        )
        assert response.status_code == 404

    def test_doctor_gets_403(self, client, doctor_token):
        response = client.post(
            f"/v1/conversation/session/{uuid.uuid4()}/end",
            headers=auth(doctor_token),
        )
        assert response.status_code == 403


# ── GET /v1/conversation/session ───────────────────────────────────────────

class TestListSessions:
    def test_empty_list_for_new_patient(self, client, patient_token):
        response = client.get("/v1/conversation/session", headers=auth(patient_token))
        assert response.status_code == 200
        data = response.json()
        assert data["sessions"] == []
        assert data["total"] == 0

    def test_returns_own_sessions(self, client, db, patient_user, patient_token):
        make_turn(db, patient_user, uuid.uuid4(), 1)
        make_turn(db, patient_user, uuid.uuid4(), 1)
        response = client.get("/v1/conversation/session", headers=auth(patient_token))
        assert response.json()["total"] == 2

    def test_does_not_return_other_users_sessions(
        self, client, db, patient_user, doctor_user, patient_token
    ):
        make_turn(db, patient_user, uuid.uuid4(), 1)
        make_turn(db, doctor_user, uuid.uuid4(), 1)
        response = client.get("/v1/conversation/session", headers=auth(patient_token))
        assert response.json()["total"] == 1

    def test_session_summary_fields(self, client, db, patient_user, patient_token):
        make_turn(db, patient_user, uuid.uuid4(), 1)
        data = client.get("/v1/conversation/session", headers=auth(patient_token)).json()
        session = data["sessions"][0]
        for field in ("session_id", "started_at", "last_active_at",
                      "total_turns", "total_disfluencies", "disfluency_rate"):
            assert field in session, f"missing field: {field}"

    def test_doctor_gets_403(self, client, doctor_token):
        response = client.get("/v1/conversation/session", headers=auth(doctor_token))
        assert response.status_code == 403


# ── GET /v1/conversation/session/{id} ──────────────────────────────────────

class TestGetSessionReport:
    def test_patient_can_view_own_session(self, client, db, patient_user, patient_token):
        sid = uuid.uuid4()
        make_turn(db, patient_user, sid, 1)
        response = client.get(
            f"/v1/conversation/session/{sid}",
            headers=auth(patient_token),
        )
        assert response.status_code == 200

    def test_patient_cannot_view_other_session(
        self, client, db, doctor_user, patient_token
    ):
        sid = uuid.uuid4()
        make_turn(db, doctor_user, sid, 1)
        response = client.get(
            f"/v1/conversation/session/{sid}",
            headers=auth(patient_token),
        )
        assert response.status_code == 403

    def test_doctor_can_view_any_session(self, client, db, patient_user, doctor_token):
        sid = uuid.uuid4()
        make_turn(db, patient_user, sid, 1)
        response = client.get(
            f"/v1/conversation/session/{sid}",
            headers=auth(doctor_token),
        )
        assert response.status_code == 200

    def test_404_for_nonexistent_session(self, client, patient_token):
        response = client.get(
            f"/v1/conversation/session/{uuid.uuid4()}",
            headers=auth(patient_token),
        )
        assert response.status_code == 404

    def test_response_contains_turns(self, client, db, patient_user, patient_token):
        sid = uuid.uuid4()
        make_turn(db, patient_user, sid, 1)
        make_turn(db, patient_user, sid, 2)
        data = client.get(
            f"/v1/conversation/session/{sid}",
            headers=auth(patient_token),
        ).json()
        assert data["total_turns"] == 2
        assert len(data["turns"]) == 2

    def test_turn_fields_present(self, client, db, patient_user, patient_token):
        sid = uuid.uuid4()
        make_turn(db, patient_user, sid, 1)
        data = client.get(
            f"/v1/conversation/session/{sid}",
            headers=auth(patient_token),
        ).json()
        turn = data["turns"][0]
        for field in ("turn_number", "child_transcript", "ai_text",
                      "child_audio_url", "disfluency_count", "disfluencies"):
            assert field in turn, f"missing field: {field}"


# ── GET /v1/conversation/patients/{id}/progress ─────────────────────────────

class TestPatientProgress:
    def test_doctor_gets_200(self, client, db, patient_user, doctor_token):
        make_turn(db, patient_user, uuid.uuid4(), 1)
        response = client.get(
            f"/v1/conversation/patients/{patient_user.id}/progress",
            headers=auth(doctor_token),
        )
        assert response.status_code == 200

    def test_patient_gets_403(self, client, patient_user, patient_token):
        response = client.get(
            f"/v1/conversation/patients/{patient_user.id}/progress",
            headers=auth(patient_token),
        )
        assert response.status_code == 403

    def test_response_fields(self, client, db, patient_user, doctor_token):
        make_turn(db, patient_user, uuid.uuid4(), 1)
        data = client.get(
            f"/v1/conversation/patients/{patient_user.id}/progress",
            headers=auth(doctor_token),
        ).json()
        assert "user_id" in data
        assert "sessions_analysed" in data
        assert "trend" in data

    def test_empty_trend_for_patient_with_no_sessions(
        self, client, patient_user, doctor_token
    ):
        data = client.get(
            f"/v1/conversation/patients/{patient_user.id}/progress",
            headers=auth(doctor_token),
        ).json()
        assert data["trend"] == []
        assert data["sessions_analysed"] == 0

    def test_trend_point_fields(self, client, db, patient_user, doctor_token):
        make_turn(db, patient_user, uuid.uuid4(), 1)
        data = client.get(
            f"/v1/conversation/patients/{patient_user.id}/progress",
            headers=auth(doctor_token),
        ).json()
        point = data["trend"][0]
        for field in ("session_id", "date", "total_turns", "total_disfluencies",
                      "disfluencies_per_turn", "by_type"):
            assert field in point, f"missing field: {field}"

    def test_limit_query_param(self, client, db, patient_user, doctor_token):
        for _ in range(5):
            make_turn(db, patient_user, uuid.uuid4(), 1)
        data = client.get(
            f"/v1/conversation/patients/{patient_user.id}/progress?limit=2",
            headers=auth(doctor_token),
        ).json()
        assert data["sessions_analysed"] == 2
