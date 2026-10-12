from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import Category, string_enum

if TYPE_CHECKING:
    from .article import Article


class Summary(Base):
    __tablename__ = "summaries"
    __table_args__ = (
        CheckConstraint("draft_attempts BETWEEN 1 AND 2", name="draft_attempts"),
        CheckConstraint("jsonb_typeof(keywords) = 'array'", name="keywords_array"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    article_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Category] = mapped_column(
        string_enum(Category, name="category"), nullable=False, index=True
    )
    keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    agent_model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    review_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    input_truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
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

    article: Mapped[Article] = relationship(back_populates="summary")
