"""Fill missing article images from RSS, optionally reading public page metadata.

Run with --apply to save changes. No articles are inserted or reprocessed.
"""

import argparse
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.models import Article, Source
from app.seed_sources import SourceConfig, load_source_config
from app.services.article_extractor import ArticleExtractor
from app.services.article_images import image_url
from app.services.rss_collector import FeedError, RSSCollector, parse_feed
from app.services.url_normalization import normalize_url


@dataclass(frozen=True)
class ImageCandidate:
    article_id: int
    original_url: str
    source_id: int


def save_article_image(session: Session, candidate: ImageCandidate, url: str) -> bool:
    """Only fill an absent image on the same active-source article; caller owns commit."""
    validated = image_url(url, candidate.original_url)
    if validated is None:
        return False
    return (
        session.scalar(
            update(Article)
            .where(
                Article.id == candidate.article_id,
                Article.source_id == candidate.source_id,
                Article.original_url == candidate.original_url,
                Article.image_url.is_(None),
                Article.source.has(Source.is_active.is_(True)),
            )
            .values(image_url=validated)
            .returning(Article.id)
        )
        is not None
    )


def source_policy(source: Source, policies: list[SourceConfig]) -> SourceConfig | None:
    """Additional RSS sections may share an already reviewed publisher origin."""
    if not source.is_active:
        return None
    for policy in policies:
        if (
            policy.is_active
            and policy.review_status == "rss_reader_supported"
            and urlsplit(source.rss_url).hostname == urlsplit(policy.rss_url).hostname
        ):
            return policy.model_copy(update={"rss_url": source.rss_url})
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Save only missing image URLs")
    parser.add_argument(
        "--from-pages", action="store_true", help="Allow robots-checked page metadata"
    )
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")
    policies = load_source_config()
    factory = get_session_factory()
    with factory() as session:
        sources = session.scalars(select(Source).where(Source.is_active.is_(True))).all()
        configs = {source.id: source_policy(source, policies) for source in sources}
        rows = session.execute(
            select(Article.id, Article.original_url, Article.source_id)
            .where(Article.image_url.is_(None), Article.source.has(Source.is_active.is_(True)))
            .order_by(Article.id)
            .limit(args.limit)
        ).all()
        candidates = [ImageCandidate(*row) for row in rows]
    # No database transaction remains open during publisher requests.
    found = saved = unavailable = 0
    rss_images: dict[str, str] = {}
    with httpx.Client() as client:
        collector = RSSCollector(client)
        extractor = ArticleExtractor(client)
        for source_id in {candidate.source_id for candidate in candidates}:
            policy = configs.get(source_id)
            if policy is None:
                continue
            try:
                entries = parse_feed(collector.fetch(policy), source_id, policy.allowed_hosts)
                rss_images.update(
                    (normalize_url(entry.original_url), entry.image_url)
                    for entry in entries
                    if entry.image_url
                )
            except FeedError:
                pass
        for candidate in candidates:
            policy = configs.get(candidate.source_id)
            url = rss_images.get(normalize_url(candidate.original_url)) if policy else None
            if url is None and policy is not None and args.from_pages:
                url = extractor.fetch_image_metadata(candidate.original_url, policy)
            if url is None:
                unavailable += 1
                continue
            found += 1
            if args.apply:
                with factory() as session, session.begin():
                    saved += save_article_image(session, candidate, url)
            print(f"article_id={candidate.article_id} image_found=true", flush=True)
    print(f"examined={len(candidates)} found={found} saved={saved} unavailable={unavailable}")


if __name__ == "__main__":
    main()
