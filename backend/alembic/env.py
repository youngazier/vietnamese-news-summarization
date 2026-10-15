"""Run migrations using application settings and the shared model metadata."""

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from app.core.config import get_settings
from app.models import Base
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.exc import ArgumentError

config = context.config

if config.config_file_name is not None:
    # Root commands use pyproject.toml; logging remains in backend/alembic.ini.
    logging_config = Path(config.config_file_name)
    if not logging_config.is_file():
        logging_config = Path(__file__).resolve().parents[1] / "alembic.ini"
    fileConfig(logging_config)

target_metadata = Base.metadata


def get_database_url() -> URL:
    """Validate configuration without including credentials in errors."""
    value = get_settings().DATABASE_URL
    if not value:
        raise RuntimeError("DATABASE_URL is not configured")
    try:
        url = make_url(value)
    except (ArgumentError, ValueError):
        raise RuntimeError("DATABASE_URL is invalid") from None
    if url.drivername != "postgresql+psycopg":
        raise RuntimeError("DATABASE_URL must use postgresql+psycopg")
    if url.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
        raise RuntimeError("DATABASE_URL must require TLS")
    return url


def run_migrations_offline() -> None:
    """Generate SQL without opening a database connection."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        version_table_schema=config.attributes.get("version_table_schema"),
    )
    with context.begin_transaction():
        context.run_migrations()


def migrate_connection(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        version_table_schema=config.attributes.get("version_table_schema"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Use a supplied test connection or open a dedicated migration connection."""
    connection = config.attributes.get("connection")
    if connection is not None:
        migrate_connection(connection)
        return

    engine = create_engine(
        get_database_url(),
        poolclass=pool.NullPool,
        connect_args={
            "connect_timeout": 5,
            "options": "-c statement_timeout=10000 -c timezone=UTC",
        },
    )
    try:
        with engine.connect() as connection:
            migrate_connection(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
