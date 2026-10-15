from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import SourceRead
from app.models import Source


router = APIRouter(prefix="/sources", tags=["sources"])

@router.get("", response_model=list[SourceRead])
def list_sources(
    db: Annotated[Session, Depends(get_db)],
) -> list[SourceRead]:
    statement = (
        select(Source)
        .where(Source.is_active.is_(True))
        .order_by(Source.name.asc(), Source.id.asc())
    )

    sources = db.scalars(statement).all()
    return [SourceRead.model_validate(source) for source in sources]