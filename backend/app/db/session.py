from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache()
def get_engine() -> Engine:
    settings = get_settings()

    if not settings.DATABASE_URL:
        raise ValueError("DATABASE_URL is not set in the environment variables.")

    try:
        url = make_url(settings.DATABASE_URL)
    except (ArgumentError, ValueError):
        raise RuntimeError(
            "Invalid DATABASE_URL format. Please check your environment variables."
        ) from None

    if url.drivername != "postgresql+psycopg":
        raise RuntimeError(
            "Invalid DATABASE_URL format. Please use 'postgresql+psycopg' as the driver."
        )

    if url.query.get("sslmode") not in {
        "require",
        "verify-ca",
        "verify-full",
    }:
        raise RuntimeError(
            "Invalid DATABASE_URL format. Please use 'sslmode=require', 'sslmode=verify-ca', or 'sslmode=verify-full' in the query parameters."
        )

    return create_engine(
        url,
        pool_size=2,
        max_overflow=1,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 5,
            "options": "-c statement_timeout=10000 -c timezone=UTC",
        },
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
    )


def get_db() -> Generator[Session, None, None]:
    factory = get_session_factory()

    with factory() as session:
        yield session
