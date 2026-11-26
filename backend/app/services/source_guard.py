"""Re-check source eligibility inside a database transaction."""

from app.core.source_config import SourceConfig
from app.models import Source
from sqlalchemy import select
from sqlalchemy.orm import Session


def require_active_source(session: Session, source_id: int, config: SourceConfig) -> None:
    source = session.scalar(select(Source).where(Source.id == source_id).with_for_update())
    if (
        source is None
        or not source.is_active
        or source.rss_url != config.rss_url
        or not config.is_usable
    ):
        raise ValueError("Source configuration changed during collection")
