"""Seed reviewed RSS sources. Run from the repository root."""

import argparse
from pathlib import Path

from app.core.config import LogSettings
from app.core.logging import configure_logging
from app.core.source_config import DEFAULT_SOURCE_CONFIG, load_source_config
from app.db.session import get_session_factory
from app.models import Source
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


def seed_sources(session: Session, sources: list[dict[str, str | bool]]) -> None:
    """Upsert by RSS URL; the caller owns the transaction."""
    for source in sources:
        statement = insert(Source).values(**source)
        statement = statement.on_conflict_do_update(
            index_elements=[Source.rss_url],
            set_={
                "name": statement.excluded.name,
                "is_active": statement.excluded.is_active,
            },
        )
        session.execute(statement)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_SOURCE_CONFIG)
    args = parser.parse_args()
    sources = load_source_config(args.config)
    seeds = [source.model_dump(include={"name", "rss_url", "is_active"}) for source in sources]
    factory = get_session_factory()
    with factory() as session, session.begin():
        seed_sources(session, seeds)


if __name__ == "__main__":
    try:
        configure_logging(LogSettings().LOG_LEVEL)
        main()
    except Exception:  # noqa: BLE001 -- keep credentials out of CLI tracebacks.
        raise SystemExit("Command failed: check configuration and service availability") from None
