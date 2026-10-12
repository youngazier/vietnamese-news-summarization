from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Identity, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .article import Article
    from .ingestion_job import IngestionJob


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    rss_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=true()
    )
    last_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    articles: Mapped[list[Article]] = relationship(
        back_populates="source", passive_deletes="all"
    )
    ingestion_jobs: Mapped[list[IngestionJob]] = relationship(
        back_populates="source", passive_deletes="all"
    )
