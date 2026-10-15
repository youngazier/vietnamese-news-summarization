from typing import Annotated

from app.db.session import get_db
from app.models import Article, Category, ProcessingStatus, Summary
from app.schemas import ArticleCard, ArticleDetail, ArticlePage, SourceRead, SummaryRead
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("/{article_id}", response_model=ArticleDetail)
def get_article(
    article_id: Annotated[int, Path(gt=0)],
    db: Annotated[Session, Depends(get_db)],
) -> ArticleDetail:
    statement = (
        select(Article)
        .where(Article.id == article_id)
        .options(
            joinedload(Article.source),
            joinedload(Article.summary),
        )
    )

    article = db.scalar(statement)

    if article is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "article_not_found",
                "message": "Article not found.",
            },
        )

    summary = article.summary
    visible = (
        article.processing_status == ProcessingStatus.READY
        and summary is not None
        and summary.approved
    )

    return ArticleDetail(
        id=article.id,
        title=article.title,
        original_url=article.original_url,
        source=SourceRead.model_validate(article.source),
        published_at=article.published_at,
        created_at=article.created_at,
        content_origin=article.content_origin,
        processing_status=article.processing_status,
        category=summary.category if visible else None,
        summary_preview=summary.summary_text[:240] if visible else None,
        input_truncated=summary.input_truncated if visible else None,
        summary=SummaryRead.model_validate(summary) if visible else None,
        ai_generated=visible,
    )


@router.get("", response_model=ArticlePage)
def list_articles(
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=200)] = None,
    source_id: Annotated[int | None, Query(gt=0)] = None,
    category: Category | None = None,
) -> ArticlePage:
    filters = []
    if source_id is not None:
        filters.append(Article.source_id == source_id)
    if q is not None:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(Article.title.ilike(f"%{escaped}%", escape="\\"))
    if category is not None:
        filters.extend(
            [
                Article.processing_status == ProcessingStatus.READY,
                Article.summary.has(Summary.approved.is_(True) & (Summary.category == category)),
            ]
        )
    total = db.scalar(select(func.count()).select_from(Article).where(*filters))
    statement = (
        select(Article)
        .where(*filters)
        .options(joinedload(Article.source), joinedload(Article.summary))
        .order_by(func.coalesce(Article.published_at, Article.created_at).desc(), Article.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = []
    for article in db.scalars(statement).all():
        summary = article.summary
        visible = (
            article.processing_status == ProcessingStatus.READY
            and summary is not None
            and summary.approved
        )
        items.append(
            ArticleCard(
                id=article.id,
                title=article.title,
                original_url=article.original_url,
                source=SourceRead.model_validate(article.source),
                published_at=article.published_at,
                created_at=article.created_at,
                content_origin=article.content_origin,
                processing_status=article.processing_status,
                category=summary.category if visible else None,
                summary_preview=summary.summary_text[:240] if visible else None,
                input_truncated=summary.input_truncated if visible else None,
            )
        )
    return ArticlePage(items=items, total=total, page=page, page_size=page_size)
