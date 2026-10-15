"""Required article inputs and partial updates for the Day 6 StateGraph."""

from typing import Literal, NotRequired, TypedDict

from app.models.enums import Category, ContentOrigin


class NewsInput(TypedDict):
    article_id: int
    title: str
    source_text: str
    content_origin: ContentOrigin


class NewsState(NewsInput):
    inference_text: NotRequired[str]
    input_truncated: NotRequired[bool]
    summary: NotRequired[str]
    category: NotRequired[Category]
    keywords: NotRequired[list[str]]
    approved: NotRequired[bool]
    feedback: NotRequired[str]
    attempts: NotRequired[int]
    outcome: NotRequired[Literal["approved", "needs_review"]]
