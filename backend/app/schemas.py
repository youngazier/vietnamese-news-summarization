from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models.enums import Category, ContentOrigin, JobStatus, JobTrigger, ProcessingStatus


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    rss_url: str
    last_fetched_at: datetime | None


class ArticleCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    original_url: str
    source: SourceRead
    published_at: datetime | None
    created_at: datetime
    content_origin: ContentOrigin | None
    processing_status: ProcessingStatus
    category: Category | None
    summary_preview: str | None
    input_truncated: bool | None


class SummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    summary_text: str
    keywords: list[str]
    summarize_model_name: str
    agent_model_name: str
    created_at: datetime
    input_truncated: bool


class ArticleDetail(ArticleCard):
    summary: SummaryRead | None
    ai_generated: bool


class ArticlePage(BaseModel):
    model_config = ConfigDict()

    items: list[ArticleCard]
    total: int
    page: int
    page_size: int


class IngestionJobCreate(BaseModel):
    source_id: int | None = Field(default=None, gt=0)


class IngestionJobAccepted(BaseModel):
    job_id: int = Field(gt=0)
    status: Literal[JobStatus.PENDING]


class IngestionJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    job_id: int = Field(validation_alias="id", gt=0)
    source_id: int | None
    trigger: JobTrigger
    status: JobStatus
    attempts: int
    articles_created: int
    articles_summarized: int
    articles_processed: int
    articles_failed: int
    articles_needs_review: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
