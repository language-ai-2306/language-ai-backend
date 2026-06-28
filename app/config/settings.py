from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "language-ai-backend"
    database_url: str = ""
    ml_service_url: str = "http://localhost:8081"
    ml_service_timeout_seconds: float = 30.0

    # --- Auth / JWT -------------------------------------------------------
    # Secret used to SIGN bearer tokens. MUST be set in .env and kept private;
    # anyone who knows it can forge logins. Generate one with:
    #   python -c "import secrets; print(secrets.token_hex(32))"
    jwt_secret: str = "CHANGE_ME_IN_ENV"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours

    # --- AWS S3 -----------------------------------------------------------
    s3_bucket_name: str = ""  # e.g. "language-ai-audio"
    # boto3 does NOT read .env — it only sees real env vars or ~/.aws. So we
    # load the credentials into settings here and pass them to the client
    # explicitly (see app/services/storage.py).
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "ap-southeast-2"

    # --- Conversational AI ------------------------------------------------
    anthropic_api_key: str = ""
    ai_model: str = "claude-haiku-4-5-20251001"
    ai_character_name: str = "Ollie"
    ai_character_description: str = (
        "a warm, fun-loving children's author who adores hearing kids "
        "tell stories about their lives"
    )

    # --- Game rules -------------------------------------------------------
    # A phrase shown to a user is not served again to them for this many days.
    phrase_repeat_block_days: int = 15
    # How many phrases the proficiency test contains.
    proficiency_test_phrase_count: int = 40


settings = Settings()
