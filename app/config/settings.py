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

    # --- Game rules -------------------------------------------------------
    # A phrase shown to a user is not served again to them for this many days.
    phrase_repeat_block_days: int = 15
    # How many phrases the proficiency test contains.
    proficiency_test_phrase_count: int = 40


settings = Settings()
