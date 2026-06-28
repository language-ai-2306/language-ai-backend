"""Shared pytest fixtures for the backend test suite.

Uses an in-memory SQLite database so tests are fully isolated from each other
and from the production RDS instance. SQLAlchemy degrades PostgreSQL-specific
types (JSONB → JSON, UUID → CHAR) transparently for SQLite.

Environment variables are set at module level — before any app import — so that
pydantic-settings picks them up when creating the Settings singleton.
"""

import os

# ── Must be set before any app module is imported ─────────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret-for-pytest")
os.environ.setdefault("ML_SERVICE_URL", "http://fake-ml:8081")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")

import uuid
from datetime import date
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base, get_db
from app.main import app
from app.models.app_config import AppConfig
from app.models.conversation import ConversationHistory
from app.models.user import User, UserRole


# ── PostgreSQL → SQLite type compatibility ────────────────────────────────────

def _patch_pg_types_for_sqlite() -> None:
    """Swap PostgreSQL-only column types with SQLite-compatible equivalents.

    SQLite can't compile JSONB or the PostgreSQL UUID dialect type. Replacing
    with plain String(36) is not enough: SQLAlchemy would try to bind a Python
    uuid.UUID object to a String column and SQLite rejects it. We use a
    TypeDecorator that explicitly converts UUID↔str on bind/result.

    This runs once at import time and modifies Base.metadata in-place. It only
    affects tests (production always runs on PostgreSQL).
    """
    import uuid as _uuid
    from sqlalchemy import JSON
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.dialects.postgresql import UUID as PGUUID
    from sqlalchemy.types import String, TypeDecorator

    class _SQLiteUUID(TypeDecorator):
        impl = String(36)
        cache_ok = True

        def process_bind_param(self, value, dialect):
            return str(value) if value is not None else None

        def process_result_value(self, value, dialect):
            return _uuid.UUID(value) if value is not None else None

    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()
            elif isinstance(col.type, PGUUID):
                col.type = _SQLiteUUID()


_patch_pg_types_for_sqlite()


# ── Database fixture ──────────────────────────────────────────────────────────

@pytest.fixture()
def db_engine():
    """Fresh in-memory SQLite engine per test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        # StaticPool reuses ONE connection across threads, so the in-memory DB
        # (which lives inside that connection) is shared. Without this, an async
        # endpoint running in a different thread sees a fresh, empty database.
        poolclass=StaticPool,
    )
    # SQLite doesn't enforce foreign keys by default — enable them so
    # cascade deletes behave the same as PostgreSQL.
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db(db_engine) -> Generator[Session, None, None]:
    """SQLAlchemy session bound to the test engine."""
    TestSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


# ── User fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture()
def patient_user(db: Session) -> User:
    user = User(
        email="patient@test.com",
        role=UserRole.PATIENT,
        password=hash_password("test1234"),
        first_name="Test",
        last_name="Patient",
        dob=date(2012, 6, 15),
        gender="M",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def doctor_user(db: Session) -> User:
    user = User(
        email="doctor@test.com",
        role=UserRole.DOCTOR,
        password=hash_password("test1234"),
        first_name="Test",
        last_name="Doctor",
        dob=date(1980, 3, 10),
        gender="F",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def patient_token(patient_user: User) -> str:
    return create_access_token(patient_user.id)


@pytest.fixture()
def doctor_token(doctor_user: User) -> str:
    return create_access_token(doctor_user.id)


# ── FastAPI test client ───────────────────────────────────────────────────────

@pytest.fixture()
def client(db: Session) -> Generator[TestClient, None, None]:
    """TestClient with get_db overridden to use the test SQLite session."""

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    # Don't use the context-manager form — it triggers lifespan which calls asyncpg.
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Auth headers helpers ──────────────────────────────────────────────────────

def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Config seed ───────────────────────────────────────────────────────────────

@pytest.fixture()
def seeded_config(db: Session) -> None:
    """Insert the standard app_config rows used in production."""
    rows = [
        AppConfig(key="phrase_repeat_block_days",      value="15", value_type="int",  description="cooldown days",    is_editable=True),
        AppConfig(key="proficiency_test_phrase_count", value="40", value_type="int",  description="test size",        is_editable=True),
        AppConfig(key="game_batch_size",               value="10", value_type="int",  description="game batch",       is_editable=True),
        AppConfig(key="max_conversation_turns",        value="20", value_type="int",  description="max turns",        is_editable=True),
        AppConfig(key="ai_max_response_tokens",        value="150",value_type="int",  description="max AI tokens",    is_editable=True),
        AppConfig(key="readonly_flag",                 value="x",  value_type="str",  description="read only",        is_editable=False),
    ]
    db.add_all(rows)
    db.commit()


# ── Conversation session helpers ──────────────────────────────────────────────

def make_turn(
    db: Session,
    user: User,
    session_id: uuid.UUID,
    turn_number: int,
    transcript: str = "I like dogs",
    ai_text: str = "That's cool! What kind of dog?",
    disfluency_events: list | None = None,
) -> ConversationHistory:
    turn = ConversationHistory(
        user_id=user.id,
        session_id=session_id,
        turn_number=turn_number,
        child_transcript=transcript,
        child_audio_url=f"https://s3.example.com/{session_id}/turn_{turn_number}/child.wav",
        ai_text=ai_text,
        ai_audio_url=f"https://s3.example.com/{session_id}/turn_{turn_number}/ai.wav",
        disfluency_events=disfluency_events or [],
    )
    db.add(turn)
    db.commit()
    db.refresh(turn)
    return turn
