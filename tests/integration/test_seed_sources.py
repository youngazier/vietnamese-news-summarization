"""Repeatable source seeding on real PostgreSQL in the owned test schema."""

from datetime import UTC, datetime

import pytest
from app.models import Source
from app.seed_sources import load_source_config, seed_sources
from sqlalchemy import select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def test_seed_configured_publishers_twice(db_session: Session) -> None:
    configs = load_source_config()
    seeds = [source.model_dump(include={"name", "rss_url", "is_active"}) for source in configs]
    with db_session.begin():
        seed_sources(db_session, seeds)
    first = {source.rss_url: source.id for source in db_session.scalars(select(Source))}
    db_session.rollback()
    with db_session.begin():
        seed_sources(db_session, seeds)
    sources = db_session.scalars(select(Source)).all()
    assert {source.rss_url: source.id for source in sources} == first
    assert {source.name: source.is_active for source in sources} == {
        "VnExpress": True,
        "Tuổi Trẻ": True,
        "Thanh Niên": False,
    }


def test_seed_sources_upsert_preserves_identity_and_fetch_time(db_session: Session) -> None:
    seeds = [{"name": "Fixture", "rss_url": "https://example.com/seed.xml", "is_active": False}]
    fetched_at = datetime(2026, 10, 14, tzinfo=UTC)
    with db_session.begin():
        seed_sources(db_session, seeds)
        source = db_session.scalar(select(Source))
        source_id = source.id
        source.last_fetched_at = fetched_at

    with db_session.begin():
        seed_sources(db_session, seeds)
    with db_session.begin():
        seed_sources(db_session, [{**seeds[0], "name": "Updated fixture", "is_active": True}])

    db_session.expire_all()
    sources = db_session.scalars(select(Source)).all()
    assert len(sources) == 1
    assert sources[0].id == source_id
    assert sources[0].name == "Updated fixture"
    assert sources[0].is_active is True
    assert sources[0].last_fetched_at == fetched_at
