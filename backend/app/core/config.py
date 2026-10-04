"""Application configuration via environment variables.

Uses pydantic-settings so all secrets/URLs are injected from the environment,
never hardcoded. Compatible with plain OpenAI, OpenCode, or any
OpenAI-compatible gateway via OPENAI_BASE_URL.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Evidra API"
    APP_ENV: str = "dev"
    API_V1_PREFIX: str = "/api/v1"

    MONGO_URL: str = "mongodb://localhost:27017"
    MONGO_DB: str = "evidra"

    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_API_KEY: str = "sk-change-me"
    OPENAI_MODEL: str = "gpt-4o-mini"
    # Minimum seconds between LLM request starts (free-tier RPM pacing).
    # 12.0s keeps usage strictly under a 5 req/min limit (e.g. Gemini free
    # tier: 5 RPM, 20 req/day per model). Lower to 4.0 for 15 RPM providers.
    # Set to 0 to disable pacing (paid tier) and rely on the semaphore
    # burst cap instead.
    LLM_MIN_INTERVAL_SECONDS: float = 12.0
    # Retries (after the first attempt) on transient 429/503 LLM errors.
    # 429s honor the server's "retry in Xs" hint; anything above
    # LLM_MAX_RETRY_DELAY_SECONDS (e.g. an 18h daily-quota lockout) fails
    # fast instead of hanging the request — extraction degrades gracefully.
    LLM_MAX_RETRIES: int = 2
    LLM_MAX_RETRY_DELAY_SECONDS: float = 75.0

    SERPAPI_API_KEY: str = ""
    S2_API_KEY: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
