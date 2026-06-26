import logging

from fastapi import FastAPI

from app.api import audio
from app.config.settings import settings

logging.basicConfig(level=logging.INFO)

app = FastAPI(title=settings.service_name)

app.include_router(audio.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": settings.service_name}
