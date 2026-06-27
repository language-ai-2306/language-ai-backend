import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import audio, auth, phrases, proficiency, users
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
]


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

app.include_router(audio.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(phrases.router)
app.include_router(phrases.game_router)
app.include_router(proficiency.router)


@app.get("/health", tags=["health"], summary="Health check")
async def health_check():
    """Returns `ok` if the service is running."""
    return {"status": "ok", "service": settings.service_name}
