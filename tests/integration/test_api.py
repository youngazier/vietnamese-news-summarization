"""D2.10–D2.11: persisted PostgreSQL data follows the read API contract."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.db.session import get_db
from app.main import app
from app.models import Article, Category, ProcessingStatus, Source, Summary
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Session]:
        yield db_session

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def make_summary(
    article: Article,
    *,
    approved: bool,
    category: Category,
    summary_text: str,
    input_truncated: bool = False,
) -> Summary:
    return Summary(
        article=article,
        summary_text=summary_text,
        category=category,
        keywords=["kiểm thử", category.value],
        summarize_model_name="fixture-summarizer",
        agent_model_name="fixture-reviewer",
        approved=approved,
        input_truncated=input_truncated,
    )


@pytest.fixture
def api_dataset(db_session: Session) -> dict[str, Any]:
    """Create varied fictional rows for search, filtering, ordering, and visibility."""
    same_time = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
    with db_session.begin():
        alpha = Source(
            name="Alpha fixture",
            rss_url="https://example.com/alpha.xml",
            is_active=True,
        )
        beta = Source(
            name="Beta fixture",
            rss_url="https://example.com/beta.xml",
            is_active=True,
        )
        inactive = Source(
            name="Hidden fixture",
            rss_url="https://example.com/hidden.xml",
            is_active=False,
        )
        db_session.add_all([alpha, beta, inactive])
        db_session.flush()

        pending = Article(
            source=alpha,
            title="Chỉ số 100%_ thử nghiệm",
            original_url="https://example.com/pending",
            canonical_url="https://example.com/pending",
            processing_status=ProcessingStatus.PENDING,
            created_at=same_time - timedelta(days=1),
        )
        approved_low_id = Article(
            source=alpha,
            title="Công nghệ Việt Nam",
            original_url="https://example.com/technology-low",
            canonical_url="https://example.com/technology-low",
            processing_status=ProcessingStatus.READY,
            published_at=same_time,
            created_at=same_time - timedelta(hours=2),
        )
        approved_high_id = Article(
            source=beta,
            title="Công nghệ thế giới",
            original_url="https://example.com/technology-high",
            canonical_url="https://example.com/technology-high",
            processing_status=ProcessingStatus.READY,
            published_at=same_time,
            created_at=same_time - timedelta(hours=1),
        )
        rejected = Article(
            source=alpha,
            title="Kinh tế bị từ chối",
            original_url="https://example.com/rejected",
            canonical_url="https://example.com/rejected",
            processing_status=ProcessingStatus.READY,
            published_at=same_time - timedelta(hours=1),
            created_at=same_time - timedelta(hours=1),
        )
        pending_approved = Article(
            source=beta,
            title="Thể thao chưa sẵn sàng",
            original_url="https://example.com/pending-approved",
            canonical_url="https://example.com/pending-approved",
            processing_status=ProcessingStatus.PENDING,
            published_at=same_time - timedelta(hours=2),
            created_at=same_time - timedelta(hours=2),
        )
        db_session.add_all([pending, approved_low_id, approved_high_id, rejected, pending_approved])
        db_session.flush()

        long_summary = "x" * 260
        db_session.add_all(
            [
                make_summary(
                    approved_low_id,
                    approved=True,
                    category=Category.TECHNOLOGY,
                    summary_text=long_summary,
                    input_truncated=True,
                ),
                make_summary(
                    approved_high_id,
                    approved=True,
                    category=Category.TECHNOLOGY,
                    summary_text="Tóm tắt công nghệ đã duyệt.",
                ),
                make_summary(
                    rejected,
                    approved=False,
                    category=Category.ECONOMY,
                    summary_text="Bản nháp bị từ chối.",
                ),
                make_summary(
                    pending_approved,
                    approved=True,
                    category=Category.SPORTS,
                    summary_text="Không được lộ khi bài chưa ready.",
                ),
            ]
        )

    return {
        "sources": {"alpha": alpha, "beta": beta, "inactive": inactive},
        "articles": {
            "pending": pending,
            "approved_low_id": approved_low_id,
            "approved_high_id": approved_high_id,
            "rejected": rejected,
            "pending_approved": pending_approved,
        },
        "long_summary": long_summary,
    }


def test_fixture_article_read_endpoints(client: TestClient, api_article: Article) -> None:
    response = client.get("/api/v1/sources")
    assert response.status_code == 200
    sources = response.json()
    assert len(sources) == 1
    assert sources[0]["id"] == api_article.source_id
    assert sources[0]["name"] == "Test fixture - not a publisher"

    response = client.get("/api/v1/articles")
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 1
    assert page["page"] == 1
    assert page["page_size"] == 20
    assert len(page["items"]) == 1
    card = page["items"][0]
    assert card["id"] == api_article.id
    assert card["title"] == api_article.title
    assert card["source"] == sources[0]
    assert card["published_at"] is None
    assert datetime.fromisoformat(card["created_at"]) == api_article.created_at

    response = client.get(f"/api/v1/articles/{api_article.id}")
    assert response.status_code == 200
    detail = response.json()
    assert {key: detail[key] for key in card} == card
    assert detail["processing_status"] == "pending"
    assert detail["summary"] is None
    assert detail["ai_generated"] is False
    for field in ("category", "summary_preview", "input_truncated"):
        assert detail[field] is None


def test_sources_search_and_combined_filters(
    client: TestClient, api_dataset: dict[str, Any]
) -> None:
    sources = client.get("/api/v1/sources").json()
    assert [source["name"] for source in sources] == ["Alpha fixture", "Beta fixture"]

    literal = client.get("/api/v1/articles", params={"q": "100%_"}).json()
    assert literal["total"] == 1
    assert literal["items"][0]["id"] == api_dataset["articles"]["pending"].id

    combined = client.get(
        "/api/v1/articles",
        params={
            "q": "Công nghệ",
            "source_id": api_dataset["sources"]["alpha"].id,
            "category": "technology",
        },
    ).json()
    assert combined["total"] == 1
    assert combined["items"][0]["id"] == api_dataset["articles"]["approved_low_id"].id

    unknown_source = client.get("/api/v1/articles", params={"source_id": 999_999_999}).json()
    assert unknown_source["total"] == 0
    assert unknown_source["items"] == []

    hidden_categories = client.get("/api/v1/articles", params={"category": "economy"}).json()
    assert hidden_categories["total"] == 0


def test_pagination_uses_timestamp_then_id_and_preserves_total(
    client: TestClient, api_dataset: dict[str, Any]
) -> None:
    first = client.get("/api/v1/articles", params={"page": 1, "page_size": 1}).json()
    second = client.get("/api/v1/articles", params={"page": 2, "page_size": 1}).json()
    outside = client.get("/api/v1/articles", params={"page": 99, "page_size": 1}).json()

    assert first["total"] == second["total"] == outside["total"] == 5
    assert first["items"][0]["id"] == api_dataset["articles"]["approved_high_id"].id
    assert second["items"][0]["id"] == api_dataset["articles"]["approved_low_id"].id
    assert outside["items"] == []
    assert outside["page"] == 99


def test_summary_visibility_and_preview_cap(
    client: TestClient, api_dataset: dict[str, Any]
) -> None:
    articles = api_dataset["articles"]
    approved = client.get(f"/api/v1/articles/{articles['approved_low_id'].id}").json()
    assert approved["ai_generated"] is True
    assert approved["category"] == "technology"
    assert approved["summary_preview"] == api_dataset["long_summary"][:240]
    assert len(approved["summary_preview"]) == 240
    assert approved["input_truncated"] is True
    assert approved["summary"]["keywords"] == ["kiểm thử", "technology"]
    assert approved["summary"]["summarize_model_name"] == "fixture-summarizer"

    for name in ("rejected", "pending_approved"):
        hidden = client.get(f"/api/v1/articles/{articles[name].id}").json()
        assert hidden["ai_generated"] is False
        assert hidden["summary"] is None
        for field in ("category", "summary_preview", "input_truncated"):
            assert hidden[field] is None


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/articles/0",
        "/api/v1/articles/not-an-id",
        "/api/v1/articles?page=0",
        "/api/v1/articles?page_size=0",
        "/api/v1/articles?page_size=101",
        "/api/v1/articles?source_id=0",
        "/api/v1/articles?category=invalid",
        f"/api/v1/articles?q={'x' * 201}",
    ],
)
def test_invalid_parameters_return_422(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_missing_article_returns_structured_404(client: TestClient) -> None:
    response = client.get("/api/v1/articles/999999999")
    assert response.status_code == 404
    assert response.json() == {
        "detail": {"code": "article_not_found", "message": "Article not found."}
    }


def test_database_failure_returns_redacted_503() -> None:
    secret = "postgresql://user:secret@example.invalid/database"

    class FailingSession:
        def scalar(self, _statement: object) -> None:
            raise OperationalError("SELECT secret", {"url": secret}, Exception(secret))

    def override_get_db() -> Iterator[FailingSession]:
        yield FailingSession()

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            response = test_client.get("/api/v1/articles/1")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "database_unavailable",
            "message": "Database is temporarily unavailable.",
        }
    }
    assert secret not in response.text
    assert "SELECT secret" not in response.text
