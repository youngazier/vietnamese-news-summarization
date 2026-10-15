"""D2.6: each test owns a fresh schema in the development PostgreSQL database."""

import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.db.session import get_engine
from app.models import Article, ProcessingStatus, Source
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

ROOT = Path(__file__).resolve().parents[2]
TEST_SCHEMA_PATTERN = re.compile(r"test_news_[0-9a-f]{32}")


def require_test_schema(name: str) -> None:
    """Refuse public, application schemas, and arbitrary user-supplied names."""
    if TEST_SCHEMA_PATTERN.fullmatch(name) is None:
        raise ValueError("Only a generated test_news_<uuid> schema is allowed")


@dataclass(frozen=True)
class TestDatabase:
    # This connection is owned by the fixture, not by an individual test.
    connection: Connection
    schema: str

    def migrate(self, direction: str, revision: str) -> None:
        require_test_schema(self.schema)
        if direction not in {"upgrade", "downgrade"}:
            raise ValueError("Unknown migration direction")

        # An outer transaction commits the migration on success.
        with self.connection.begin():
            current_schema = self.connection.execute(text("SELECT current_schema()")).scalar_one()
            if current_schema != self.schema:
                raise RuntimeError("Refusing migration outside the owned test schema")

            cfg = Config(str(ROOT / "backend" / "alembic.ini"))
            cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
            # env.py already supports both of these attributes.
            cfg.attributes["connection"] = self.connection
            cfg.attributes["version_table_schema"] = self.schema
            # Preserve pytest logging rather than running fileConfig for every test.
            cfg.config_file_name = None
            operation = command.upgrade if direction == "upgrade" else command.downgrade
            operation(cfg, revision)


@pytest.fixture
def test_database():
    """Empty schema for migration tests; default fixture scope is one test."""
    schema = f"test_news_{uuid4().hex}"
    require_test_schema(schema)

    # Reuse URL validation from D2.3, but use a separate, unpooled test engine.
    # Merely calling get_engine() does not open an application connection.
    engine = create_engine(
        get_engine().url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 5,
            "options": "-c statement_timeout=10000 -c timezone=UTC",
        },
    )
    created = False
    try:
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(CreateSchema(schema))
            created = True

            # Use ONLY this schema. Do not fall back to public if a table is missing.
            # set_config accepts a bound string; Create/DropSchema quote identifiers.
            with connection.begin():
                connection.execute(
                    text("SELECT set_config('search_path', :schema, false)"),
                    {"schema": schema},
                )
            try:
                yield TestDatabase(connection=connection, schema=schema)
            finally:
                # Clear failed/unfinished transactions before releasing the connection.
                connection.rollback()
    finally:
        try:
            if created:
                require_test_schema(schema)
                # A fresh connection can clean up even after the test connection fails.
                with engine.begin() as cleanup:
                    cleanup.execute(DropSchema(schema, cascade=True))
        finally:
            engine.dispose()


@pytest.fixture
def migrated_database(test_database):
    """Same isolated schema, with the committed initial migration applied."""
    test_database.migrate("upgrade", "head")
    return test_database


@pytest.fixture
def db_session(migrated_database):
    """Sessions use the SAME connection/search path as the migration."""
    with Session(bind=migrated_database.connection, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def api_article(db_session: Session) -> Article:
    """Commit fictional active source/article data in the disposable schema."""
    with db_session.begin():
        source = Source(
            name="Test fixture - not a publisher",
            rss_url="https://example.com/fixture.xml",
            is_active=True,
        )
        db_session.add(source)
        db_session.flush()

        article = Article(
            source_id=source.id,
            title="Test article fixture",
            original_url="https://example.com/fixture-article",
            canonical_url="https://example.com/fixture-article",
            processing_status=ProcessingStatus.PENDING,
        )
        db_session.add(article)
    return article
