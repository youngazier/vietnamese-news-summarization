"""Human review migration round-trip only in a disposable test schema."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration


def test_manual_review_migration_lifecycle(test_database):
    db = test_database
    db.migrate("upgrade", "0003")
    with db.connection.begin():
        sid = db.connection.scalar(
            text(
                "INSERT INTO sources(name,rss_url) VALUES('Fixture','https://example.com/review') RETURNING id"
            )
        )
        aid = db.connection.scalar(
            text(
                "INSERT INTO articles(source_id,title,original_url,canonical_url) VALUES(:sid,'Fixture','https://example.com/a','https://example.com/a') RETURNING id"
            ),
            {"sid": sid},
        )
        db.connection.execute(
            text(
                "INSERT INTO summaries(article_id,summary_text,category,keywords,summarize_model_name,agent_model_name) VALUES(:aid,'Fixture','other','[]','fixture','fixture')"
            ),
            {"aid": aid},
        )
    db.migrate("upgrade", "head")
    with db.connection.begin():
        assert db.connection.scalar(text("SELECT human_review_decision FROM summaries")) is None
        with pytest.raises(IntegrityError), db.connection.begin_nested():
            db.connection.execute(
                text("UPDATE summaries SET human_review_decision='decline',human_reviewed_at=now()")
            )
        db.connection.execute(
            text(
                "UPDATE summaries SET human_review_decision='decline',human_review_note='Not supported',human_reviewed_at=now()"
            )
        )
    db.migrate("upgrade", "head")
    with db.connection.begin():
        assert (
            db.connection.scalar(text("SELECT human_review_decision FROM summaries")) == "decline"
        )
    db.migrate("downgrade", "0003")
    with db.connection.begin():
        assert "human_review_decision" not in {
            column["name"] for column in inspect(db.connection).get_columns("summaries")
        }
        assert db.connection.scalar(text("SELECT summary_text FROM summaries")) == "Fixture"
    db.migrate("upgrade", "head")
    with db.connection.begin():
        assert db.connection.scalar(text("SELECT human_review_decision FROM summaries")) is None
