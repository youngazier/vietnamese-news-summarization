import sys

from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


def probe_database() -> int:
    try:
        settings = get_settings()
    except ValidationError:
        print(
            "Database probe failed: invalid application settings.",
            file=sys.stderr,
        )
        return 1

    if not settings.DATABASE_URL:
        print(
            "Database probe failed: DATABASE_URL is not configured.",
            file=sys.stderr,
        )
        return 1

    engine = None

    try:
        url = make_url(settings.DATABASE_URL)

        if url.drivername != "postgresql+psycopg":
            print(
                "Database probe failed: use postgresql+psycopg.",
                file=sys.stderr,
            )
            return 1

        engine = create_engine(
            url,
            poolclass=NullPool,
            connect_args={
                "connect_timeout": 5,
                "options": "-c statement_timeout=5000",
            },
        )

        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1")).scalar_one()

        if result != 1:
            print("Database probe failed: unexpected result.", file=sys.stderr)
            return 1

        print("Database probe successful: SELECT 1 returned 1.")
        return 0

    except (SQLAlchemyError, ValueError):
        print(
            "Database probe failed. Check the URL, password, "
            "network access and TLS settings.",
            file=sys.stderr,
        )
        return 1

    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(probe_database())