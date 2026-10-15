"""Validated provider metadata and application-assembled drafts."""

import unicodedata
from typing import Annotated, Literal

from app.models.enums import Category, ContentOrigin
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

Keyword = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class ArticleMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category
    keywords: list[Keyword] = Field(min_length=3, max_length=5)

    @field_validator("keywords")
    @classmethod
    def distinct_keywords(cls, keywords: list[str]) -> list[str]:
        normalized = [unicodedata.normalize("NFC", keyword) for keyword in keywords]
        if len({keyword.casefold() for keyword in normalized}) != len(normalized):
            raise ValueError("Keywords must be distinct")
        return normalized


class NewsDraft(ArticleMetadata):
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: StrictBool
    feedback: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]

    @model_validator(mode="after")
    def rejection_requires_reason(self) -> "ReviewResult":
        if not self.approved and not self.feedback:
            raise ValueError("Rejected drafts require feedback")
        return self


class ReviewedNews(NewsDraft, ReviewResult):
    """Validate the complete graph output again at the persistence boundary."""

    article_id: int = Field(gt=0, strict=True)
    title: str = Field(min_length=1, max_length=500)
    source_text: str = Field(min_length=1, max_length=20_000)
    content_origin: ContentOrigin
    inference_text: str = Field(min_length=1, max_length=20_000)
    input_truncated: StrictBool
    attempts: int = Field(ge=1, le=2, strict=True)
    outcome: Literal["approved", "needs_review"]

    @model_validator(mode="after")
    def consistent_outcome(self) -> "ReviewedNews":
        expected = "approved" if self.approved else "needs_review"
        if self.outcome != expected:
            raise ValueError("Graph approval and outcome must agree")
        return self
