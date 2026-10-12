from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import ContentOrigin, ProcessingStatus, string_enum

if TYPE_CHECKING:
    from .source import Source
    from .summary import Summary


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    rss_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_origin: Mapped[ContentOrigin | None] = mapped_column(
        string_enum(ContentOrigin, name="content_origin"), nullable=True
    )
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        string_enum(ProcessingStatus, name="processing_status"),
        nullable=False,
        server_default=ProcessingStatus.PENDING.value,
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    source: Mapped[Source] = relationship(back_populates="articles")
    summary: Mapped[Summary | None] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
