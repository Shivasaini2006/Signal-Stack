from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: str = "sqlite:///./data/signal_stack.db"

    # LLM Providers (Free Tier)
    GEMINI_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    DEFAULT_LLM_PROVIDER: str = "gemini"
    FALLBACK_LLM_PROVIDER: str = "groq"
    LLM_CACHE_ENABLED: bool = True

    # Models
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Web Crawler & Search Politeness Settings
    CRAWLER_USER_AGENT: str = (
        "SignalStackBot/1.0 (+https://github.com/Shivasaini2006/Signal-Stack; signalstack@example.com)"
    )
    CRAWL_DELAY_SECONDS: float = 2.0
    ROBOTS_TXT_TIMEOUT_SECONDS: float = 5.0
    MAX_CONCURRENT_CRAWLS_PER_DOMAIN: int = 1

    # API Server
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000

    # Automation & Scheduler
    SCHEDULER_TIMEZONE: str = "UTC"
    WEEKLY_SCHEDULE_CRON: str = "mon 06:00"
    MONTHLY_SCHEDULE_CRON: str = "1 06:00"


settings = Settings()
