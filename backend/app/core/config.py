from functools import cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


class Settings(LogSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Vietnamese News Summarization"

    DATABASE_URL: str = Field(default="", repr=False)

    COLLECTION_INTERVAL_MINUTES: int = Field(default=30, gt=0)
    WORKER_POLL_INTERVAL_SECONDS: int = Field(default=10, gt=0)
    JOB_MAX_ARTICLE_INSERTIONS: int = Field(default=20, gt=0)
    JOB_MAX_ARTICLE_RESULTS: int = Field(default=20, gt=0)
    MAX_JOB_BACKLOG: int = Field(default=5, gt=0)

    MAX_GRAPH_DRAFT_ATTEMPTS: int = Field(default=2, ge=1, le=2)

    GEMINI_API_KEY: str = Field(default="", repr=False)
    GEMINI_MODEL: str = ""

    SUMMARIZATION_MODEL_ID: str = "VietAI/vit5-base-vietnews-summarization"
    SUMMARIZATION_MODEL_PATH: str = ".models/vit5-base-vietnews-summarization"
    SUMMARIZATION_CPU_THREADS: int = Field(default=4, ge=1, le=32)


@cache
def get_settings() -> Settings:
    return Settings()
