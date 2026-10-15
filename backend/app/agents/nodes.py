"""Partial state updates for drafting and review; no database access."""

from collections.abc import Callable
from typing import Protocol

from app.agents.schemas import ArticleMetadata, NewsDraft, ReviewResult
from app.agents.state import NewsState
from app.models.enums import ContentOrigin
from app.services.summary_service import SummaryResult


class Summarizer(Protocol):
    def summarize(self, source_text: str, *, attempt: int = 1) -> SummaryResult: ...


class MetadataProvider(Protocol):
    def metadata(
        self,
        *,
        title: str,
        source_text: str,
        content_origin: ContentOrigin,
    ) -> ArticleMetadata: ...


class ReviewProvider(Protocol):
    def review(
        self,
        *,
        title: str,
        source_text: str,
        content_origin: ContentOrigin,
        inference_text: str,
        input_truncated: bool,
        draft: NewsDraft,
    ) -> ReviewResult: ...


def make_draft_node(
    summarizer: Summarizer,
    metadata_provider: MetadataProvider,
    *,
    max_attempts: int = 2,
) -> Callable[[NewsState], dict[str, object]]:
    if type(max_attempts) is not int or max_attempts not in {1, 2}:
        raise ValueError("At most two draft attempts are supported")

    def draft(state: NewsState) -> dict[str, object]:
        attempts = state.get("attempts", 0)
        if type(attempts) is not int or not 0 <= attempts < max_attempts:
            raise ValueError("Draft attempts must start at zero and stop after two")
        attempt = attempts + 1
        result = summarizer.summarize(state["source_text"], attempt=attempt)
        metadata = metadata_provider.metadata(
            title=state["title"],
            source_text=state["source_text"],
            content_origin=state["content_origin"],
        )
        assembled = NewsDraft(summary=result.summary, **metadata.model_dump())
        return {
            "attempts": attempt,
            "approved": False,
            "feedback": "",
            "summary": assembled.summary,
            "category": assembled.category,
            "keywords": assembled.keywords,
            "inference_text": result.inference_text,
            "input_truncated": result.input_truncated,
        }

    return draft


def make_review_node(provider: ReviewProvider) -> Callable[[NewsState], dict[str, object]]:
    def review(state: NewsState) -> dict[str, object]:
        draft = NewsDraft(
            summary=state["summary"], category=state["category"], keywords=state["keywords"]
        )
        result = ReviewResult.model_validate(
            provider.review(
                title=state["title"],
                source_text=state["source_text"],
                content_origin=state["content_origin"],
                inference_text=state["inference_text"],
                input_truncated=state["input_truncated"],
                draft=draft,
            )
        )
        return result.model_dump()

    return review
