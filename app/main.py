import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import audio, auth, phrases, proficiency, users
from app.config.settings import settings

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def _check_db() -> None:
    if not settings.database_url:
        logger.warning("DATABASE_URL not set — skipping DB check")
        return
    try:
        import asyncpg
        # asyncpg expects postgresql:// not postgresql+asyncpg://
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


app = FastAPI(title=settings.service_name, lifespan=lifespan)

app.include_router(audio.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(phrases.router)
app.include_router(phrases.game_router)
app.include_router(proficiency.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": settings.service_name}
