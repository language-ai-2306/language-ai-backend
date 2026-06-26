from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "language-ai-backend"
    database_url: str = ""
    ml_service_url: str = "http://localhost:8081"
    ml_service_timeout_seconds: float = 30.0


settings = Settings()
