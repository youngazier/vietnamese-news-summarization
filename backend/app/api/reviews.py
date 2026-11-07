"""Local reviewer endpoints. Unapproved content stays out of public reader APIs."""

from ipaddress import ip_address
from typing import Annotated, Literal
from urllib.parse import urlsplit

from app.db.session import get_db
from app.models import Article, Category, ContentOrigin, ProcessingStatus, Summary
from app.schemas import SourceRead
from app.services.manual_review import (
    ReviewConflict,
    can_review,
    decide_review,
    review_version,
)
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload


def require_local_reviewer(request: Request) -> None:
    """This MVP is local-only; forwarded headers are not an authorization mechanism."""
    try:
        local = request.client is not None and ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    origin = request.headers.get("origin")
    if origin:
        try:
            parsed = urlsplit(origin)
            local = (
                local
                and parsed.scheme in {"http", "https"}
                and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                and parsed.username is None
                and parsed.password is None
            )
        except ValueError:
            local = False
    if not local:
        raise HTTPException(
            403,
            detail={"code": "local_review_only", "message": "Review is available locally only."},
        )


router = APIRouter(
    prefix="/reviews", tags=["reviews"], dependencies=[Depends(require_local_reviewer)]
)


class ReviewItem(BaseModel):
    id: int
    title: str
    source: SourceRead
    has_draft: bool
    decision: Literal["accept", "decline"] | None
    can_review: bool


class ReviewPage(BaseModel):
    items: list[ReviewItem]
    total: int
    page: int
    page_size: int


class ReviewDraft(BaseModel):
    text: str
    category: Category
    keywords: list[str]
    ai_feedback: str | None
    attempts: int
    input_truncated: bool


class ReviewDetail(ReviewItem):
    original_url: str
    source_text: str | None
    content_origin: ContentOrigin | None
    draft: ReviewDraft | None
    reason: str | None
    version: str
    note: str | None


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accept", "decline"]
    expected_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def decline_requires_reason(self) -> "ReviewDecision":
        if self.decision == "decline" and not self.note.strip():
            raise ValueError("Declining requires a reason")
        return self


def item_for(article: Article) -> ReviewItem:
    summary = article.summary
    return ReviewItem(
        id=article.id,
        title=article.title,
        source=SourceRead.model_validate(article.source),
        has_draft=summary is not None,
        can_review=can_review(article, summary),
        decision=summary.human_review_decision if summary else None,
    )


def detail_for(article: Article) -> ReviewDetail:
    summary = article.summary
    reason = None
    if summary is None:
        reason = (
            "Chưa có bản nháp: trích đoạn RSS chưa đủ nội dung và việc trích xuất bài gốc đang tắt."
            if "insufficient_text" in (article.processing_error or "")
            and "extraction_disabled" in (article.processing_error or "")
            else "Chưa có bản nháp. Cần thu thập đủ nội dung và tạo tóm tắt trước khi duyệt."
        )
    elif not article.content:
        reason = "Thiếu văn bản nguồn để đối chiếu. Chưa thể duyệt bản nháp này."
    return ReviewDetail(
        **item_for(article).model_dump(),
        original_url=article.original_url,
        source_text=article.content,
        content_origin=article.content_origin,
        reason=reason,
        version=review_version(article, summary),
        note=summary.human_review_note if summary else None,
        draft=ReviewDraft(
            text=summary.summary_text,
            category=summary.category,
            keywords=summary.keywords,
            ai_feedback=summary.review_feedback,
            attempts=summary.draft_attempts,
            input_truncated=summary.input_truncated,
        )
        if summary
        else None,
    )


@router.get("", response_model=ReviewPage)
def list_reviews(
    db: Annotated[Session, Depends(get_db)],
    decision: Literal["pending", "accept", "decline"] = "pending",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ReviewPage:
    if decision == "pending":
        filters = [
            Article.processing_status == ProcessingStatus.NEEDS_REVIEW,
            ~Article.summary.has(Summary.human_review_decision.is_not(None)),
        ]
    else:
        filters = [Article.summary.has(Summary.human_review_decision == decision)]
    total = db.scalar(select(func.count()).select_from(Article).where(*filters))
    rows = db.scalars(
        select(Article)
        .where(*filters)
        .options(joinedload(Article.source), joinedload(Article.summary))
        .order_by(Article.summary.has().desc(), Article.created_at.desc(), Article.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ReviewPage(
        items=[item_for(article) for article in rows],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/{article_id}", response_model=ReviewDetail)
def get_review(
    article_id: Annotated[int, Path(gt=0)], db: Annotated[Session, Depends(get_db)]
) -> ReviewDetail:
    article = db.scalar(
        select(Article)
        .where(Article.id == article_id)
        .options(joinedload(Article.source), joinedload(Article.summary))
    )
    if article is None:
        raise HTTPException(404, detail={"code": "article_not_found"})
    return detail_for(article)


@router.post("/{article_id}", response_model=ReviewDetail)
def review_article(
    article_id: Annotated[int, Path(gt=0)],
    body: ReviewDecision,
    db: Annotated[Session, Depends(get_db)],
) -> ReviewDetail:
    try:
        with db.begin():
            article = decide_review(db, article_id, **body.model_dump())
            db.expire(article, ["summary"])
            result = detail_for(article)
        return result
    except LookupError:
        raise HTTPException(404, detail={"code": "article_not_found"}) from None
    except ReviewConflict:
        raise HTTPException(
            409,
            detail={
                "code": "review_conflict",
                "message": "Bản nháp đã thay đổi hoặc đã được duyệt. Vui lòng tải lại.",
            },
        ) from None
