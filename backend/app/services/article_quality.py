"""Deterministic extraction quality signals shared by ingestion and inference."""

import re
from collections import Counter
from dataclasses import dataclass
from unicodedata import normalize
from urllib.parse import unquote, urlsplit

from app.models import ContentOrigin

MAX_TEXT_CHARACTERS = 20_000
WORD = re.compile(r"[^\W_]+", re.UNICODE)
ABBREVIATION = re.compile(r"(?:\b(?:TP|TS|ThS|PGS|GS|UBND|HĐND)|\b[A-ZÀ-Ỹ])\.$")
SENTENCE_BREAK = re.compile(r"(?:(?<=[.!?…])|(?<=[.!?…][”’\"]))\s+")
MEDIA_TYPES = {"photo", "photos", "video", "gallery", "infographic"}
BOILERPLATE = re.compile(
    r"^(?:(?:đăng nhập|đăng ký tài khoản|theo dõi chúng tôi|bạn cần đăng nhập)(?:\W|$)"
    r"|(?:xem thêm|xem tiếp|chia sẻ|bình luận)(?:\s*[:：–—-]|\s*$))",
    re.IGNORECASE,
)
STOP_WORDS = {
    "và",
    "của",
    "có",
    "cho",
    "là",
    "đã",
    "từ",
    "một",
    "được",
    "các",
    "những",
    "với",
    "trong",
    "để",
    "này",
    "về",
    "khi",
    "theo",
}


@dataclass(frozen=True)
class QualityThresholds:
    min_words: int = 60
    min_sentences: int = 3
    min_overlap: float = 0.1
    max_duplicate_ratio: float = 0.4


DEFAULT_THRESHOLDS = QualityThresholds()


def words(text: str) -> list[str]:
    return WORD.findall(normalize("NFC", text).casefold())


def split_sentences(text: str) -> list[str]:
    sentences = []
    for paragraph in text.splitlines():
        start = 0
        for boundary in SENTENCE_BREAK.finditer(paragraph):
            if ABBREVIATION.search(paragraph, start, boundary.start()):
                continue
            sentences.append(paragraph[start : boundary.start()].strip())
            start = boundary.end()
        if remainder := paragraph[start:].strip():
            sentences.append(remainder)
    return sentences


def is_media_url(url: str) -> bool:
    try:
        segments = unquote(urlsplit(url).path).casefold().split("/")
    except ValueError:
        return False  # URL policy validates destinations independently.
    return bool(MEDIA_TYPES.intersection(segments))


def quality_reasons(
    *,
    text: str | None,
    origin: ContentOrigin | None,
    url: str,
    title: str = "",
    description: str | None = None,
    publisher_meta: dict[str, list[str]] | None = None,
    thresholds: QualityThresholds = DEFAULT_THRESHOLDS,
) -> tuple[str, ...]:
    if origin == ContentOrigin.RSS_EXCERPT:
        return ("rss_excerpt_only",)
    reasons = []
    if is_media_url(url):
        reasons.append("media_url")
    meta = publisher_meta or {}
    if any(value.strip().casefold() in MEDIA_TYPES for value in meta.get("its_type", [])):
        reasons.append("media_content_type")
    if origin != ContentOrigin.EXTRACTED or not text or not text.strip():
        return (*reasons, "missing_text")
    if len(text) > MAX_TEXT_CHARACTERS:
        reasons.append("text_too_long")

    lines = [normalize("NFC", line.strip()) for line in text.splitlines() if line.strip()]
    clean_lines = []
    boilerplate_words = 0
    for line in lines:
        if BOILERPLATE.match(line):
            boilerplate_words += len(words(line))
        else:
            clean_lines.append(line)
    clean_body = "\n".join(clean_lines)
    body_words = words(clean_body)
    if len(body_words) < thresholds.min_words:
        reasons.append("too_few_words")
    wordcounts = [value.strip() for value in meta.get("its_wordcount", [])]
    if len(wordcounts) == 1 and re.fullmatch(r"[0-9]{1,6}", wordcounts[0]):
        expected = int(wordcounts[0])
        if expected >= 120 and len(body_words) < expected * 0.35:
            reasons.append("publisher_wordcount_mismatch")
    sentences = split_sentences(clean_body)
    if sum(len(words(sentence)) >= 5 for sentence in sentences) < thresholds.min_sentences:
        reasons.append("too_few_sentences")

    # Either the headline or the description can supply corroborating vocabulary.
    body_terms = set(body_words)
    overlap = []
    for reference in (title, description or ""):
        terms = {word for word in words(reference) if len(word) > 1} - STOP_WORDS
        if len(terms) >= 3:
            overlap.append(len(terms & body_terms) / len(terms))
    if overlap and max(overlap) < thresholds.min_overlap:
        reasons.append("low_rss_overlap")
    # An exact or near-exact teaser can still have high vocabulary overlap.
    excerpt = words(description or "")
    if (
        len(excerpt) >= 8
        and len(body_words) <= len(excerpt) * 1.1
        and len(body_terms & set(excerpt)) / max(len(body_terms), 1) >= 0.9
    ):
        reasons.append("rss_teaser_match")

    counts = Counter(tokens for line in clean_lines if (tokens := tuple(words(line))))
    line_count = sum(counts.values())
    if line_count > 1 and (line_count - len(counts)) / line_count > thresholds.max_duplicate_ratio:
        reasons.append("duplicate_lines")
    if boilerplate_words and (
        len(body_words) < thresholds.min_words or boilerplate_words * 2 >= len(body_words)
    ):
        reasons.append("boilerplate")
    return tuple(reasons)
