"""Deterministic quality signals, including Unicode and fallback provenance."""

import pytest
from app.models import ContentOrigin
from app.services.article_quality import quality_reasons
from app.services.summary_service import SMOKE_TEXT, SMOKE_TITLE

URL = "https://example.com/news/library"


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"origin": ContentOrigin.RSS_EXCERPT}, ("rss_excerpt_only",)),
        ({"text": "Thư viện."}, ("too_few_words", "too_few_sentences")),
        ({"title": "Bão nhiệt đới mạnh ngoài khơi"}, ("low_rss_overlap",)),
        ({"description": SMOKE_TEXT}, ("rss_teaser_match",)),
        ({"text": "\n\n".join([SMOKE_TEXT] * 3)}, ("duplicate_lines",)),
        ({"text": SMOKE_TEXT + "\n\nĐăng nhập để bình luận"}, ()),
        ({"text": "Đăng nhập để xem bài." * 25 + "\n\n" + SMOKE_TEXT}, ("boilerplate",)),
        (
            {"text": "Đăng nhập để xem bài." * 25 + "\n\nThư viện."},
            ("too_few_words", "too_few_sentences", "boilerplate"),
        ),
        ({"url": "https://example.com/news/%76ideo/clip"}, ("media_url",)),
        ({"publisher_meta": {"its_type": ["Text", " PHOTO "]}}, ("media_content_type",)),
        ({"publisher_meta": {"its_wordcount": ["2000"]}}, ("publisher_wordcount_mismatch",)),
    ],
)
def test_quality_signals_report_stable_codes(changes, expected):
    params = {
        "text": SMOKE_TEXT,
        "origin": ContentOrigin.EXTRACTED,
        "url": URL,
        "title": SMOKE_TITLE,
    }
    assert quality_reasons(**(params | changes)) == expected


def test_matching_description_supports_a_paraphrased_headline():
    reasons = quality_reasons(
        text=SMOKE_TEXT,
        origin=ContentOrigin.EXTRACTED,
        url=URL + "?section=/video/",
        title="Cơ hội vàng cho cộng đồng",
        description="Lớp kỹ năng số tại thư viện Bình Minh.",
    )
    assert reasons == ()


@pytest.mark.parametrize(
    "line",
    [
        "Xem thêm: Lịch sinh hoạt của thư viện",
        "Chia sẻ: Gửi bản tin cho bạn bè",
        "Bình luận",
        "Bình luận của bạn đọc về buổi học được thư viện ghi nhận.",
    ],
)
def test_boilerplate_does_not_reject_good_body(line):
    assert not quality_reasons(
        text=f"{line}\n\n{SMOKE_TEXT}\n\n{line}",
        origin=ContentOrigin.EXTRACTED,
        url=URL,
        title=SMOKE_TITLE,
    )
