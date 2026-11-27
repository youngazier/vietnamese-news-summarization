"""Frozen calibration snapshots and the pinned ViT5 VietNews test slice."""

import csv
import hashlib
import json
import os
from collections import defaultdict, deque
from pathlib import Path
from typing import Literal

from app.core.source_config import load_source_config
from app.db.session import get_session_factory
from app.models import Article, ContentOrigin, Source, Summary
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from sqlalchemy import select
from sqlalchemy.orm import defer

VIETNEWS_REVISION = "b3886e9a9f8d29837aa156b11f840977cf7565be"
VIETNEWS_SHA256 = "064f3559aacb14d5690ef24f1346fd54ebf1b2040683da8dc602e0aa8085fd2d"
VIETNEWS_URL = (
    f"https://raw.githubusercontent.com/vietai/ViT5/{VIETNEWS_REVISION}/data/vietnews/test.tsv"
)


class CalibrationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    article_id: int = Field(gt=0)
    source: str = Field(min_length=1)
    url: str
    title: str = Field(min_length=1, max_length=500)
    description: str | None
    text: str | None = Field(max_length=20_000)
    origin: ContentOrigin | None
    publisher_meta: dict[str, list[str]] | None = None
    accepted_summary: str | None = Field(default=None, max_length=4000)
    candidate: str | None = Field(default=None, max_length=4000)
    inference_text: str | None = Field(default=None, max_length=20_000)
    input_truncated: StrictBool = False
    extraction_valid: StrictBool | None = None
    summary_faithful: StrictBool | None = None
    real_paraphrase: StrictBool | None = None

    @model_validator(mode="after")
    def check_candidate_labels(self) -> "CalibrationItem":
        if self.candidate and not self.inference_text:
            raise ValueError("A candidate requires the exact model input")
        if (self.summary_faithful is not None or self.real_paraphrase is not None) and (
            not self.candidate or self.origin != ContentOrigin.EXTRACTED
        ):
            raise ValueError("Summary labels require a full-text candidate")
        if self.real_paraphrase and self.summary_faithful is not True:
            raise ValueError("A valid real paraphrase must be labeled faithful")
        return self


class CalibrationSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    candidate_model: str | None = None
    items: list[CalibrationItem] = Field(min_length=1)

    @model_validator(mode="after")
    def check_unique_ids(self) -> "CalibrationSnapshot":
        if len({item.article_id for item in self.items}) != len(self.items):
            raise ValueError("Duplicate article IDs in calibration snapshot")
        return self


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_vietnews(path: Path, limit: int) -> list[tuple[int, str, str]]:
    if sha256(path) != VIETNEWS_SHA256:
        raise ValueError("VietNews test file does not match the pinned SHA-256")
    # Smallest hashes define a fixed slice of the published test split.
    with path.open(encoding="utf-8", newline="") as stream:
        records = [
            (index, body.strip().replace("_", " "), reference.strip().replace("_", " "))
            for index, (body, reference) in enumerate(
                csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            )
            if body.strip() and reference.strip() and len(body.strip()) <= 20_000
        ]
    return sorted(
        records, key=lambda row: hashlib.sha256(f"vietnews-p1:{row[0]}".encode()).digest()
    )[:limit]


def read_snapshot(path: Path) -> CalibrationSnapshot:
    return CalibrationSnapshot.model_validate_json(path.read_bytes())


def write_snapshot(path: Path, snapshot: CalibrationSnapshot) -> None:
    write_private_json(path, snapshot.model_dump(mode="json"))


def write_private_json(path: Path, data: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Exclusive create protects frozen inputs on reruns.
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        stream.write(payload)


def freeze_snapshot(limit: int, *, legacy_schema: bool = False) -> CalibrationSnapshot:
    configs = [
        config
        for config in load_source_config()
        if config.is_usable and config.ai_processing_allowed
    ]
    groups = defaultdict(deque)
    options = [defer(Article.evaluation_exempt, raiseload=True)]
    if legacy_schema:
        options.append(defer(Article.publisher_meta, raiseload=True))

    with get_session_factory()() as session:
        # Bound each source independently and retain both accepted and rejected input examples.
        for config in configs:
            for accepted in (False, True):
                rows = session.execute(
                    select(Article, Source.name, Summary.summary_text)
                    .options(*options)
                    .join(Source)
                    .outerjoin(Summary, (Summary.article_id == Article.id) & Summary.approved)
                    .where(
                        Source.is_active,
                        Source.rss_url == config.rss_url,
                        Article.content.is_not(None),
                        Article.content_origin.is_not(None),
                        Summary.id.is_not(None) if accepted else Summary.id.is_(None),
                    )
                    .order_by(Article.id.desc())
                    .limit(limit)
                )
                groups[config.rss_url, accepted].extend(
                    CalibrationItem(
                        article_id=article.id,
                        source=source,
                        url=article.original_url,
                        title=article.title,
                        description=article.rss_description,
                        text=article.content,
                        origin=article.content_origin,
                        publisher_meta=None if legacy_schema else article.publisher_meta,
                        accepted_summary=summary
                        if article.content_origin == ContentOrigin.EXTRACTED
                        else None,
                    )
                    for article, source, summary in rows
                )
    items = []
    while len(items) < limit and any(groups.values()):
        for group in groups.values():
            if group and len(items) < limit:
                items.append(group.popleft())
    return CalibrationSnapshot(items=items)


def protect_snapshot(snapshot: CalibrationSnapshot) -> int:
    """Mark matching source-text rows as retention exempt in one transaction."""
    with get_session_factory()() as session, session.begin():
        rows = session.scalars(
            select(Article)
            .where(Article.id.in_([item.article_id for item in snapshot.items]))
            .order_by(Article.id)
            .with_for_update()
        )
        by_id = {article.id: article for article in rows}
        for item in snapshot.items:
            article = by_id.get(item.article_id)
            if (
                article is None
                or article.content != item.text
                or article.original_url != item.url
                or article.title != item.title
                or article.content_origin != item.origin
            ):
                raise ValueError("Snapshot no longer matches the stored source text")
            article.evaluation_exempt = True
    return len(by_id)
