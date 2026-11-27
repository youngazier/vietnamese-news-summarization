"""Deterministic benchmark inputs and metrics without publishers or fitted models."""

import httpx
import pytest
from app.core.config import Settings
from app.evaluation import corpus
from app.evaluation.baseline import MeasuredGemini, calibrate_gate
from app.evaluation.corpus import CalibrationItem, CalibrationSnapshot, read_vietnews, sha256
from app.evaluation.metrics import classification, cohen_kappa, rouge
from app.evaluation.synthetic import inject_errors
from app.models import ContentOrigin
from app.services.gemini_service import GeminiServiceError
from app.services.summary_service import SMOKE_TEXT, SMOKE_TITLE


def test_synthetic_corruptions_change_one_labeled_sentence_each():
    reference = (
        "Thư viện Bình Minh tổ chức lớp miễn phí cho 30 học viên. "
        "Chương trình khai giảng ngày 28 tháng 2 năm 2024."
    )
    donor = "Đại học Hà Nội công bố kết quả tuyển sinh đợt mới."
    cases = inject_errors(reference, reference, donor)
    assert cases == inject_errors(reference, reference, donor)
    assert {case.kind for case in cases} == {
        "number_mutation",
        "proper_name_swap",
        "date_shift",
        "clause_negation",
        "cross_article_insertion",
    }
    originals = (
        "Thư viện Bình Minh tổ chức lớp miễn phí cho 30 học viên.",
        "Chương trình khai giảng ngày 28 tháng 2 năm 2024.",
    )
    for case in cases:
        assert case.supported.count(False) == 1
        assert [sentence for sentence, label in zip(case.sentences, case.supported) if label] == [
            sentence for index, sentence in enumerate(originals) if case.supported[index]
        ]
    assert "ngày 6 tháng 3 năm 2024" in next(c.text for c in cases if c.kind == "date_shift")
    assert "40 học viên" in next(c.text for c in cases if c.kind == "number_mutation")


@pytest.mark.parametrize(
    ("before", "after"),
    [("25/11", "02/12"), ("25-11", "02-12"), ("28/12/2026", "04/01/2027")],
)
def test_synthetic_numeric_dates_keep_their_precision(before, after):
    reference = f"Thư viện thông báo khai giảng vào ngày {before}."
    cases = {case.kind: case for case in inject_errors(reference, reference, "")}
    assert cases["date_shift"].text == reference.replace(before, after)
    assert "number_mutation" not in cases


def test_synthetic_number_at_sentence_end_keeps_nonzero_leading_digit():
    reference = "Thư viện thông báo tổng số học viên là 90."
    cases = {case.kind: case for case in inject_errors(reference, reference, "")}
    assert cases["number_mutation"].text.endswith("80.")


def test_rouge_and_binary_agreement_have_known_values():
    assert rouge("học tiếng Việt", "học tiếng Việt") == pytest.approx((1, 1, 1))
    assert rouge("học tiếng Việt", "tiếng Việt hay") == pytest.approx((2 / 3, 0.5, 2 / 3))
    labels = [(True, True), (True, False), (False, False), (False, False)]
    assert cohen_kappa(labels) == pytest.approx(0.5)
    assert cohen_kappa([(True, True)]) is None
    assert classification(labels)["precision"] == 1
    assert classification(labels)["recall"] == 0.5
    assert classification([])["recall"] is None


def calibration_item(article_id, good):
    return CalibrationItem(
        article_id=article_id,
        source="Fixture",
        url=f"https://example.com/{article_id}",
        title=SMOKE_TITLE,
        description=None,
        text=SMOKE_TEXT if good else "Thiếu văn bản",
        origin=ContentOrigin.EXTRACTED if good else ContentOrigin.RSS_EXCERPT,
        extraction_valid=good,
    )


def test_tuning_uses_paired_labels_and_a_separate_holdout():
    items = [calibration_item(index, index % 2 == 0) for index in range(1, 11)]
    labels = {item.article_id: item.extraction_valid for item in items}
    assert calibrate_gate(items, {})["tuned"] is None
    result = calibrate_gate(items, labels)
    assert (result["training_pairs"], result["heldout_pairs"]) == (8, 2)
    assert result["tuned"]["heldout_vs_human"]["precision"] == 1
    assert result["tuned"]["heldout_vs_gemini"]["recall"] == 1


def test_snapshot_protects_frozen_inputs_and_vietnews_checks_digest(tmp_path, monkeypatch):
    path = tmp_path / "calibration.json"
    snapshot = CalibrationSnapshot(items=[calibration_item(1, True)])
    corpus.write_snapshot(path, snapshot)
    assert corpus.read_snapshot(path) == snapshot
    with pytest.raises(FileExistsError):
        corpus.write_snapshot(path, snapshot)

    test = tmp_path / "test.tsv"
    test.write_text('"Thư_viện"\tTóm_tắt\nVăn bản\tBản tin\n', encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        read_vietnews(test, 1)
    monkeypatch.setattr(corpus, "VIETNEWS_SHA256", sha256(test))
    rows = read_vietnews(test, 2)
    assert sorted(rows) == [(0, '"Thư viện"', "Tóm tắt"), (1, "Văn bản", "Bản tin")]
    assert read_vietnews(test, 1) == rows[:1]


@pytest.mark.parametrize("defer_retry", [False, True])
def test_measured_calls_count_retry_requests(monkeypatch, defer_retry):
    calls = []

    def transport(request):
        calls.append(request)
        if defer_retry:
            return httpx.Response(429, headers={"Retry-After": "3600"})
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "id": "fixture-interaction",
                "status": "completed",
                "steps": [
                    {
                        "type": "model_output",
                        "content": [{"type": "text", "text": '{"valid":true}'}],
                    }
                ],
            },
        )

    client = httpx.Client
    now = 0.0
    send_times = []

    def sleep(seconds):
        nonlocal now
        now += seconds

    def record_request(request):
        send_times.append(now)
        return transport(request)

    monkeypatch.setattr(
        "app.evaluation.baseline.httpx.Client",
        lambda **kwargs: client(transport=httpx.MockTransport(record_request), **kwargs),
    )
    monkeypatch.setattr("app.evaluation.baseline.perf_counter", lambda: now)
    monkeypatch.setattr("app.evaluation.baseline.sleep", sleep)
    service = MeasuredGemini(
        Settings(_env_file=None, GEMINI_API_KEY="fixture", GEMINI_MODEL="fixture"),
        request_delay=6,
    )
    try:
        if defer_retry:
            with pytest.raises(GeminiServiceError):
                service.extraction_valid(calibration_item(1, True))
            assert service.retry_deferred
            assert (service.logical, service.wire, service.statuses) == (1, 1, {429: 1})
            assert send_times == [0]
        else:
            assert service.extraction_valid(calibration_item(1, True))
            assert not service.retry_deferred
            assert (service.logical, service.wire, service.statuses) == (1, 3, {503: 2, 200: 1})
            assert send_times == [0, 6, 12]
    finally:
        service.close()


def test_online_baseline_measures_graph_stability_and_synthetic_cases():
    from unittest.mock import Mock

    from app.agents.schemas import ArticleMetadata, ReviewResult
    from app.evaluation.baseline import online_benchmark
    from app.services.summary_service import SummaryResult

    reference = "Thư viện Bình Minh tổ chức lớp miễn phí cho 30 học viên."
    model = Mock()
    model.summarize.return_value = SummaryResult(reference, SMOKE_TEXT, False, 100, 12, 0.1)
    provider = Mock()
    provider.model_id = "fixture"
    provider.logical = provider.wire = 0
    provider.statuses = {}
    provider.retry_deferred = False

    def metadata(**_kwargs):
        provider.logical += 1
        provider.wire += 1
        return ArticleMetadata(category="society", keywords=["thư viện", "lớp học", "kỹ năng"])

    def review(**kwargs):
        provider.logical += 1
        provider.wire += 1
        approved = kwargs["draft"].summary == reference
        return ReviewResult(approved=approved, feedback="Fixture judgment")

    provider.metadata.side_effect = metadata
    provider.review.side_effect = review
    provider.extraction_valid.return_value = True
    item = calibration_item(1, True).model_copy(
        update={
            "candidate": reference,
            "inference_text": SMOKE_TEXT,
            "summary_faithful": True,
            "real_paraphrase": True,
            "accepted_summary": reference,
        }
    )
    report = online_benchmark(
        provider,
        model,
        CalibrationSnapshot(items=[item]),
        [(0, SMOKE_TEXT, reference)],
        max_drafts=2,
        synthetic_limit=1,
    )
    assert report["provider_failure_stage"] is None
    assert report["mvp_graph"]["outcomes"] == {"approved": 1}
    assert report["mvp_graph"]["logical_calls_per_article"] == 2
    assert report["mvp_graph"]["wire_calls_per_article"] == 2
    assert report["summary_human_gemini_pairs"] == 1
    assert report["real_paraphrase_false_reject_rate"] == 0
    assert report["stability_agreement"] == 1
    assert report["synthetic"]["catch_rate"] == 1
    assert report["synthetic"]["false_accept_rate"] == 0


@pytest.mark.parametrize(
    ("stage", "audit_calls", "review_calls"),
    [("calibration", 1, 1), ("stability", 0, 2), ("synthetic", 0, 4)],
)
def test_online_stages_can_run_without_model_or_other_stage_calls(stage, audit_calls, review_calls):
    from unittest.mock import Mock

    from app.agents.schemas import ArticleMetadata, ReviewResult
    from app.evaluation.baseline import online_benchmark

    provider = Mock(
        model_id="fixture",
        logical=0,
        wire=0,
        statuses={},
        retry_deferred=False,
    )
    provider.metadata.return_value = ArticleMetadata(
        category="society",
        keywords=["thư viện", "lớp học", "kỹ năng"],
    )
    provider.extraction_valid.return_value = True
    provider.review.return_value = ReviewResult(approved=True, feedback="Fixture judgment")
    reference = "Thư viện Bình Minh tổ chức lớp học miễn phí cho 30 học viên."
    item = calibration_item(1, True).model_copy(
        update={
            "candidate": reference,
            "inference_text": SMOKE_TEXT,
            "summary_faithful": True,
            "real_paraphrase": True,
        }
    )
    report = online_benchmark(
        provider,
        None,
        CalibrationSnapshot(items=[item]),
        [(0, SMOKE_TEXT, reference)],
        max_drafts=2,
        synthetic_limit=1,
        stage=stage,
    )
    assert report["provider_failure_stage"] is None
    assert "mvp_graph" not in report
    assert provider.extraction_valid.call_count == audit_calls
    assert provider.review.call_count == review_calls
    assert ("gate" in report) == (stage == "calibration")
    assert ("stability_pairs" in report) == (stage == "stability")
    assert ("synthetic" in report) == (stage == "synthetic")
