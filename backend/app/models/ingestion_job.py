from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import JobStatus, JobTrigger, string_enum

if TYPE_CHECKING:
    from .source import Source


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint(
            "attempts >= 0 AND articles_created >= 0 "
            "AND articles_summarized >= 0 AND articles_processed >= 0 "
            "AND articles_failed >= 0 AND articles_needs_review >= 0",
            name="nonnegative_counters",
        ),
        CheckConstraint(
            "articles_processed = articles_summarized "
            "+ articles_failed + articles_needs_review",
            name="processed_counter_total",
        ),
        Index("ix_ingestion_jobs_status_created_at_id", "status", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    status: Mapped[JobStatus] = mapped_column(
        string_enum(JobStatus, name="status"),
        nullable=False,
        server_default=JobStatus.PENDING.value,
    )
    trigger: Mapped[JobTrigger] = mapped_column(
        string_enum(JobTrigger, name="trigger"), nullable=False
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    articles_created: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    articles_summarized: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    articles_processed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    articles_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    articles_needs_review: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    source: Mapped[Source | None] = relationship(back_populates="ingestion_jobs")
