"""Load reviewed RSS configuration and seed sources; run from the repository root."""

import argparse
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from soupsieve import SelectorSyntaxError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.models import Source

DEFAULT_SOURCE_CONFIG = Path("config/sources.json")


class ArticleExtractionPolicy(BaseModel):
    """Explicitly reviewed public paths and a fixture-tested article container."""

    model_config = ConfigDict(extra="forbid", strict=True)

    public_path_prefixes: list[str] = Field(min_length=1)
    content_selector: str = Field(min_length=1)
    review_note: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_scope(self) -> "ArticleExtractionPolicy":
        if any(
            not path.startswith("/") or any(char in path for char in "?#%\\")
            for path in self.public_path_prefixes
        ):
            raise ValueError("Public paths must be absolute, decoded path prefixes")
        try:
            BeautifulSoup("", "html.parser").select(self.content_selector)
        except SelectorSyntaxError:
            raise ValueError("Article content selector must be valid CSS") from None
        return self


class SourceConfig(BaseModel):
    """Policy metadata stays in JSON; only existing Source columns are seeded."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=120)
    rss_url: str
    is_active: bool
    allowed_hosts: list[str] = Field(min_length=1)
    checked_on: date
    official_rss_url: str
    robots_url: str
    attribution: str = Field(min_length=1)
    review_status: Literal["rss_reader_supported", "reuse_unresolved"]
    review_note: str = Field(min_length=1)
    article_extraction_allowed: bool
    article_extraction: ArticleExtractionPolicy | None = None
    ai_processing_allowed: bool
    ai_processing_review_note: str | None = Field(default=None, min_length=1)
    availability: dict[str, str | int | bool]

    @model_validator(mode="after")
    def validate_review(self) -> "SourceConfig":
        for url in (self.rss_url, self.official_rss_url, self.robots_url):
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in self.allowed_hosts
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in (None, 443)
            ):
                raise ValueError("Source URLs must use HTTPS and an exact allowed host")
        if self.is_active and (
            self.review_status != "rss_reader_supported"
            or self.availability.get("status") != 200
            or self.availability.get("official_link") is not True
            or self.availability.get("robots_allowed") is not True
            or self.availability.get("bozo") is not False
        ):
            raise ValueError("Active sources require reviewed RSS use and verified access")
        if self.article_extraction_allowed and (
            not self.is_active or self.article_extraction is None
        ):
            raise ValueError("Extraction requires an active source and reviewed public-path policy")
        if self.ai_processing_allowed and (
            not self.is_active
            or not self.ai_processing_review_note
            or not self.ai_processing_review_note.strip()
        ):
            raise ValueError("AI processing requires an active source and an explicit review note")
        return self


def load_source_config(path: Path = DEFAULT_SOURCE_CONFIG) -> list[SourceConfig]:
    """Validate the complete configuration before opening a database session."""
    sources = TypeAdapter(list[SourceConfig]).validate_json(path.read_text(encoding="utf-8"))
    urls = [source.rss_url for source in sources]
    if len(urls) != len(set(urls)):
        raise ValueError("Source configuration contains duplicate RSS URLs")
    if not sources:
        raise ValueError("Source configuration must not be empty")
    return sources


def seed_sources(session: Session, sources: list[dict[str, str | bool]]) -> None:
    """Upsert by RSS URL; the caller owns the transaction."""
    for source in sources:
        statement = insert(Source).values(**source)
        statement = statement.on_conflict_do_update(
            index_elements=[Source.rss_url],
            set_={
                "name": statement.excluded.name,
                "is_active": statement.excluded.is_active,
            },
        )
        session.execute(statement)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_SOURCE_CONFIG)
    args = parser.parse_args()
    sources = load_source_config(args.config)
    seeds = [source.model_dump(include={"name", "rss_url", "is_active"}) for source in sources]
    factory = get_session_factory()
    with factory() as session, session.begin():
        seed_sources(session, seeds)


if __name__ == "__main__":
    main()
