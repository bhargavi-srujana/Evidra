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
    # Failover model when the primary is still rate-limited after all retries
    # (e.g. Groq daily-token exhaustion on openai/gpt-oss-120b). Blank disables.
    OPENAI_FALLBACK_MODEL: str = "llama-3.1-8b-instant"
    # Rotation pool: comma-separated keys, e.g.
    # GROQ_API_KEYS="gsk_key1,gsk_key2,gsk_key3". Falls back to the single
    # GROQ_API_KEY, then to OPENAI_API_KEY for backward compatibility.
    GROQ_API_KEYS: str = ""
    GROQ_API_KEY: str = ""

    @property
    def API_KEYS(self) -> list[str]:
        """Usable LLM keys in rotation order (deduped, placeholder-free)."""
        keys: list[str] = []
        for chunk in (self.GROQ_API_KEYS or "").split(","):
            key = chunk.strip().strip("'\"").strip()
            if key and key != "sk-change-me" and key not in keys:
                keys.append(key)
        for single in ((self.GROQ_API_KEY or "").strip(), (self.OPENAI_API_KEY or "").strip()):
            key = single.strip().strip("'\"").strip()
            if key and key != "sk-change-me" and key not in keys:
                keys.append(key)
        return keys

    def llm_key_warning(self) -> str | None:
        """Human-readable warning when a configured key looks malformed.

        Catches the common silent-failure mode: a pasted key with the wrong
        shape for the configured provider (every LLM call then 401s and
        extraction degrades to hollow "Not reported" records). Returns None
        when keys look sane or none are configured.
        """
        keys = self.API_KEYS
        if not keys:
            return None
        base = (self.OPENAI_BASE_URL or "").lower()
        provider = "groq" if "groq" in base else ("openai" if "openai" in base else "custom")
        for key in keys:
            masked = f"{key[:4]}...{key[-3:]}"
            if provider == "groq" and not key.startswith("gsk_"):
                return (
                    f"LLM key {masked!r} does not look like a Groq key (expected gsk_...) "
                    f"for base URL {self.OPENAI_BASE_URL}; every extraction call will 401."
                )
            if provider == "openai" and not key.startswith(("sk-", "sess-")):
                return (
                    f"LLM key {masked!r} does not look like an OpenAI key (expected sk-...) "
                    f"for base URL {self.OPENAI_BASE_URL}; every extraction call will 401."
                )
            if len(key) < 20:
                return (
                    f"LLM key {masked!r} is suspiciously short ({len(key)} chars); "
                    "check for a truncated paste."
                )
            if provider == "groq" and len(key) > 80:
                return (
                    f"LLM key {masked!r} has a suspicious length ({len(key)} chars; "
                    "Groq keys are short) — check for a paste error in "
                    "GROQ_API_KEYS/GROQ_API_KEY/OPENAI_API_KEY; "
                    "every extraction call will 401 until fixed."
                )
        return None
    # Minimum seconds between LLM request starts (free-tier RPM pacing).
    # 12.0s keeps usage strictly under a 5 req/min limit (e.g. Gemini free
    # tier: 5 RPM, 20 req/day per model). Lower to 4.0 for 15 RPM providers.
    # Set to 0 to disable pacing (paid tier) and rely on the semaphore
    # burst cap instead.
    LLM_MIN_INTERVAL_SECONDS: float = 12.0
    # Retries (after the first attempt) on transient 429/503 LLM errors:
    # up to 4 attempts per model (1 initial + 3 retries). 429s honor the
    # server's "retry in Xs" hint with exponential-backoff fallback; anything
    # above LLM_MAX_RETRY_DELAY_SECONDS (e.g. an 18h daily-quota lockout)
    # fails fast to the fallback model (or graceful degradation) instead of
    # hanging the request.
    LLM_MAX_RETRIES: int = 3
    LLM_MAX_RETRY_DELAY_SECONDS: float = 75.0
    # LLM query-parser fallback: when the rule-based parser misses a question
    # shape (is/are, which/who, why, superlatives, conversational queries),
    # spend one cached LLM call to extract intervention/outcome/direction
    # instead of searching unanchored. False forces keyword fallback always.
    LLM_QUERY_PARSER: bool = True

    SERPAPI_API_KEY: str = ""
    S2_API_KEY: str = ""

    # Comma-separated extra frontend origins to allow via CORS,
    # e.g. FRONTEND_URL="https://evidra-ten.vercel.app" on Render.
    FRONTEND_URL: str = ""
    CORS_EXTRA_ORIGINS: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
