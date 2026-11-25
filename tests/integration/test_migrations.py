"""D2.7: migration lifecycle, always inside the fixture-owned test schema."""

import pytest
from sqlalchemy import inspect, text

pytestmark = pytest.mark.integration

APPLICATION_TABLES = {"sources", "articles", "summaries", "ingestion_jobs"}


def assert_head(database):
    # A fresh inspector avoids cached results after schema changes.
    tables = set(inspect(database.connection).get_table_names(schema=database.schema))
    assert tables == APPLICATION_TABLES | {"alembic_version"}
    revision = database.connection.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar_one()
    assert revision == "0004"
    # Inspection/SELECT starts a transaction; end it before migrate() opens one.
    database.connection.rollback()


def test_empty_schema_upgrade(test_database):
    assert inspect(test_database.connection).get_table_names(schema=test_database.schema) == []
    test_database.connection.rollback()

    test_database.migrate("upgrade", "head")
    assert_head(test_database)


def test_repeated_upgrade_preserves_existing_data(migrated_database):
    database = migrated_database
    with database.connection.begin():
        source_id = database.connection.execute(
            text("INSERT INTO sources (name, rss_url) VALUES (:name, :url) RETURNING id"),
            {"name": "D2 fixture", "url": "https://example.com/fixture.xml"},
        ).scalar_one()

    database.migrate("upgrade", "head")
    assert_head(database)
    name = database.connection.execute(
        text("SELECT name FROM sources WHERE id = :id"), {"id": source_id}
    ).scalar_one()
    assert name == "D2 fixture"


def test_downgrade_and_reupgrade(migrated_database):
    database = migrated_database
    # Do not replace this with a standalone `alembic downgrade base` command.
    database.migrate("downgrade", "base")
    tables = set(inspect(database.connection).get_table_names(schema=database.schema))
    assert tables.isdisjoint(APPLICATION_TABLES)
    revisions = database.connection.execute(text("SELECT version_num FROM alembic_version")).all()
    assert revisions == []
    database.connection.rollback()

    database.migrate("upgrade", "head")
    assert_head(database)


def test_summary_model_column_rename_preserves_data(test_database):
    database = test_database
    database.migrate("upgrade", "0001")
    with database.connection.begin():
        source_id = database.connection.execute(
            text(
                "INSERT INTO sources (name, rss_url) VALUES ('Fixture', 'https://example.com/rss') RETURNING id"
            )
        ).scalar_one()
        article_id = database.connection.execute(
            text(
                "INSERT INTO articles (source_id, title, original_url, canonical_url) VALUES (:source, 'Fixture', 'https://example.com/a', 'https://example.com/a') RETURNING id"
            ),
            {"source": source_id},
        ).scalar_one()
        database.connection.execute(
            text(
                "INSERT INTO summaries (article_id, summary_text, category, keywords, model_name, agent_model_name) VALUES (:article, 'Fixture', 'other', '[]', 'fixture-model', 'fixture-reviewer')"
            ),
            {"article": article_id},
        )

    for direction, revision, column in [
        ("upgrade", "head", "summarize_model_name"),
        ("downgrade", "0001", "model_name"),
        ("upgrade", "head", "summarize_model_name"),
    ]:
        database.migrate(direction, revision)
        with database.connection.begin():
            columns = {
                item["name"] for item in inspect(database.connection).get_columns("summaries")
            }
            assert column in columns
            other = "model_name" if column == "summarize_model_name" else "summarize_model_name"
            assert other not in columns
            assert (
                database.connection.execute(
                    text(f"SELECT {column} FROM summaries WHERE article_id = :article"),
                    {"article": article_id},
                ).scalar_one()
                == "fixture-model"
            )


def test_article_image_column_lifecycle_preserves_article(test_database):
    database = test_database
    database.migrate("upgrade", "0002")
    with database.connection.begin():
        source_id = database.connection.scalar(
            text(
                "INSERT INTO sources (name, rss_url) VALUES ('Image fixture', 'https://example.com/image-rss') RETURNING id"
            )
        )
        article_id = database.connection.scalar(
            text(
                "INSERT INTO articles (source_id, title, original_url, canonical_url) VALUES (:source, 'Image fixture', 'https://example.com/image-a', 'https://example.com/image-a') RETURNING id"
            ),
            {"source": source_id},
        )
    database.migrate("upgrade", "head")
    with database.connection.begin():
        assert (
            database.connection.scalar(
                text("SELECT image_url FROM articles WHERE id = :id"), {"id": article_id}
            )
            is None
        )
        database.connection.execute(
            text(
                "UPDATE articles SET image_url = 'https://cdn.example.com/lead.jpg' WHERE id = :id"
            ),
            {"id": article_id},
        )
    database.migrate("upgrade", "head")
    with database.connection.begin():
        assert (
            database.connection.scalar(
                text("SELECT image_url FROM articles WHERE id = :id"), {"id": article_id}
            )
            == "https://cdn.example.com/lead.jpg"
        )
    database.migrate("downgrade", "0002")
    with database.connection.begin():
        assert "image_url" not in {
            column["name"] for column in inspect(database.connection).get_columns("articles")
        }
        assert (
            database.connection.scalar(
                text("SELECT title FROM articles WHERE id = :id"), {"id": article_id}
            )
            == "Image fixture"
        )
    database.migrate("upgrade", "head")
    with database.connection.begin():
        assert (
            database.connection.scalar(
                text("SELECT image_url FROM articles WHERE id = :id"), {"id": article_id}
            )
            is None
        )
