from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    service_name: str = "language-ai-backend"
    host: str = "0.0.0.0"
    port: int = 8080

    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/languageai"

    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    s3_bucket_name: str = "language-ai-audio"
    delete_audio_after_processing: bool = False

    ml_service_url: str = "http://localhost:8081"
    ml_service_timeout_seconds: float = 30.0

    allowed_audio_content_types: list[str] = [
        "audio/wav",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp3",
        "audio/webm",
        "audio/ogg",
        "application/octet-stream",
    ]


settings = Settings()
