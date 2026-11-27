"""Vietnamese lexical ROUGE and agreement metrics with explicit denominators."""

from collections import Counter
from collections.abc import Sequence

from app.services.article_quality import words


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def classification(labels: Sequence[tuple[bool, bool]]) -> dict[str, int | float | None]:
    tp = sum(expected and predicted for expected, predicted in labels)
    fp = sum(not expected and predicted for expected, predicted in labels)
    fn = sum(expected and not predicted for expected, predicted in labels)
    tn = len(labels) - tp - fp - fn
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": ratio(tp, tp + fp),
        "recall": ratio(tp, tp + fn),
        "f1": ratio(2 * tp, 2 * tp + fp + fn),
    }


def cohen_kappa(labels: Sequence[tuple[bool, bool]]) -> float | None:
    count = len(labels)
    actual_yes = sum(expected for expected, _ in labels)
    predicted_yes = sum(predicted for _, predicted in labels)
    expected_agreement = actual_yes * predicted_yes + (count - actual_yes) * (count - predicted_yes)
    observed_agreement = count * sum(expected == predicted for expected, predicted in labels)
    denominator = count * count - expected_agreement
    return (observed_agreement - expected_agreement) / denominator if denominator else None


def _lcs(left: list[str], right: list[str]) -> int:
    scores = [0] * (len(right) + 1)
    for token in left:
        diagonal = 0
        for index, other in enumerate(right, start=1):
            previous = scores[index]
            scores[index] = diagonal + 1 if token == other else max(previous, scores[index - 1])
            diagonal = previous
    return scores[-1]


def rouge(candidate: str, reference: str) -> tuple[float, float, float]:
    left, right = words(candidate), words(reference)
    scores = []
    for size in (1, 2):
        left_grams = Counter(tuple(left[i : i + size]) for i in range(len(left) - size + 1))
        right_grams = Counter(tuple(right[i : i + size]) for i in range(len(right) - size + 1))
        overlap = sum((left_grams & right_grams).values())
        scores.append(
            ratio(2 * overlap, sum(left_grams.values()) + sum(right_grams.values())) or 0.0
        )
    return scores[0], scores[1], ratio(2 * _lcs(left, right), len(left) + len(right)) or 0.0
