import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import (
    admin,
    audio,
    auth,
    conversation,
    doctors,
    exercises,
    my_plan,
    patients,
    phrases,
    plans,
    proficiency,
    users,
)
from app.config.settings import settings

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

TAGS_METADATA = [
    {
        "name": "auth",
        "description": "Sign up, log in, and inspect the current session. "
                       "Login returns a **Bearer token** — pass it as `Authorization: Bearer <token>` on all protected endpoints.",
    },
    {
        "name": "users",
        "description": "Read, update, and delete user accounts. "
                       "A user can always act on their own account; doctors may act on any account.",
    },
    {
        "name": "phrases",
        "description": "Manage practice sentences (disfluency phrases). "
                       "Creating, editing, and deleting phrases is restricted to **doctors**.",
    },
    {
        "name": "game",
        "description": "Patient-facing game endpoints. Returns a randomised batch of unseen phrases "
                       "for the current difficulty level and records that they were shown.",
    },
    {
        "name": "proficiency",
        "description": "Proficiency test flow: start a 40-phrase assessment, then submit answers "
                       "to receive an assigned starting difficulty.",
    },
    {
        "name": "audio",
        "description": "Audio analysis pipeline. Upload a WAV/MP3 recording and receive a full "
                       "disfluency breakdown, fluency score, coverage score, and retry flag.",
    },
    {
        "name": "conversation",
        "description": "Conversational AI sessions. Start a session, submit audio turns, "
                       "and receive AI-generated replies with synthesised voice. "
                       "Doctors can retrieve full session transcripts.",
    },
    {
        "name": "admin",
        "description": "Runtime configuration management. **Doctor role required.** "
                       "Read and update business rules (phrase cooldown days, test size, etc.) "
                       "without a code deploy.",
    },
    {
        "name": "doctors",
        "description": "Doctor directory and a patient's request to be linked to a doctor. "
                       "Requesting a doctor creates a **pending** request that the doctor must approve.",
    },
    {
        "name": "patients",
        "description": "Doctor-facing patient management: list **pending** link requests, "
                       "approve/reject them, and list **approved** patients.",
    },
    {
        "name": "exercises",
        "description": "Unified practice-game API. `{game}` = read-it-loud, picture-talk, "
                       "story-teller, or repeat-after-me. Each game: **start** (spoken intro), "
                       "**content** (next prompt + audio), **attempt** (analyse a recording).",
    },
    {
        "name": "plans",
        "description": "Doctor-authored tailored treatment plans. Build an ordered set of "
                       "exercise assignments (by phoneme + difficulty), review progress, and "
                       "advance items. Scoped to the doctor's approved patients.",
    },
    {
        "name": "my-plan",
        "description": "Patient-facing: the child's active plan and today's due exercises.",
    },
]


def _run_migrations() -> None:
    if not settings.database_url:
        logger.warning("DATABASE_URL not set — skipping migrations")
        return
    try:
        from alembic import command
        from alembic.config import Config
        import os
        alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
        # Alembic needs a sync driver — strip +asyncpg if present.
        # connect_timeout=10 prevents an unreachable DB from hanging startup forever.
        sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        if "connect_timeout" not in sync_url:
            sep = "&" if "?" in sync_url else "?"
            sync_url = f"{sync_url}{sep}connect_timeout=10"
        alembic_cfg.set_main_option("sqlalchemy.url", sync_url)
        command.upgrade(alembic_cfg, "head")
        logger.info("✓ Migrations applied")
    except Exception as exc:
        logger.error("✗ Migration failed: %s", exc)
        raise


async def _check_db() -> None:
    if not settings.database_url:
        logger.warning("DATABASE_URL not set — skipping DB check")
        return
    try:
        import asyncpg
        url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(url)
        await conn.fetchval("SELECT 1")
        await conn.close()
        logger.info("✓ Connected to database")
    except Exception as exc:
        logger.error("✗ Database connection failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _run_migrations()
    await _check_db()
    yield


app = FastAPI(
    title="Language AI — Backend API",
    description=(
        "Backend service for the Language AI stuttering practice app.\n\n"
        "## Authentication\n"
        "Most endpoints require a Bearer token. Call **POST /auth/login** to get one, "
        "then click **Authorize** (top-right) and paste the token.\n\n"
        "## Roles\n"
        "| Role | Can do |\n"
        "|------|--------|\n"
        "| `PATIENT` | Play the game, take proficiency tests, analyse audio |\n"
        "| `DOCTOR` | Everything above + manage phrases and read all users |\n"
    ),
    version="1.0.0",
    openapi_tags=TAGS_METADATA,
    contact={"name": "Rahul Bhatt", "email": "rahul@edstruments.com"},
    lifespan=lifespan,
)

app.include_router(admin.router)
app.include_router(audio.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(phrases.router)
app.include_router(phrases.game_router)
app.include_router(proficiency.router)
app.include_router(conversation.router)
app.include_router(doctors.router)
app.include_router(patients.router)
app.include_router(exercises.router)
app.include_router(plans.router)
app.include_router(my_plan.router)
# Legacy /v1/repeat-after-me/* routes removed — served by /v1/exercises/repeat-after-me/*.


@app.get("/health", tags=["health"], summary="Health check")
async def health_check():
    """Returns `ok` if the service is running."""
    return {"status": "ok", "service": settings.service_name}
