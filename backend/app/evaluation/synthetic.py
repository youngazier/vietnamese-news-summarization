"""Generate deterministic one-error candidates with sentence-level edit labels."""

import re
from dataclasses import dataclass
from datetime import date, timedelta

from app.services.article_quality import split_sentences, words

LETTER = r"[^\W\d_]"
NAME = re.compile(rf"(?<!\w)(?:[A-ZÀ-Ỹ]{LETTER}+[ \t]+){{1,3}}[A-ZÀ-Ỹ]{LETTER}+(?!\w)")
DATE = re.compile(r"(?<![\w/.-])(\d{1,2})([/.-])(\d{1,2})\2(\d{4})(?![\w/-]|\.\d)")
SHORT_DATE = re.compile(r"(?<![\w/.-])(\d{1,2})([/-])(\d{1,2})(?![\w/-]|\.\d)")
VIET_DATE = re.compile(r"\bngày (\d{1,2}) tháng (\d{1,2})(?: năm (\d{4}))?\b", re.IGNORECASE)
NUMBER = re.compile(r"(?<![\w/.-])\d+(?:[.,]\d+)*(?![\w/]|[.,-]\d)")
VERB = re.compile(
    r"\b(?:không )?(?:đã |sẽ )?(?:tổ chức|triển khai|phê duyệt|ghi nhận|"
    r"đạt được|công bố|xác nhận|phát hiện|cho phép|tiếp tục|tham gia)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SyntheticCase:
    kind: str
    sentences: tuple[str, ...]
    supported: tuple[bool, ...]

    @property
    def text(self) -> str:
        return " ".join(self.sentences)


def _shift_date(match: re.Match[str], *, viet: bool) -> str | None:
    if viet:
        day, month, year = match.groups()
    else:
        day, _, month, *years = match.groups()
        year = years[0] if years else None
    try:
        shifted = date(int(year or 2000), int(month), int(day)) + timedelta(days=7)
    except (ValueError, OverflowError):
        return None
    if viet:
        suffix = f" năm {shifted.year}" if year is not None else ""
        return f"ngày {shifted.day} tháng {shifted.month}{suffix}"
    delimiter = match[2]
    suffix = f"{delimiter}{shifted.year:04}" if year is not None else ""
    return f"{shifted.day:02}{delimiter}{shifted.month:02}{suffix}"


def _edits(sentence: str, source: str, names: tuple[str, ...]):
    dates = sorted(
        [*DATE.finditer(sentence), *SHORT_DATE.finditer(sentence), *VIET_DATE.finditer(sentence)],
        key=lambda match: match.start(),
    )
    for match in NUMBER.finditer(sentence):
        if not any(start.start() <= match.start() < start.end() for start in dates):
            first = int(match[0][0])
            value = f"{8 if first == 9 else first + 1}{match[0][1:]}"
            if not re.search(rf"(?<!\d){re.escape(value)}(?!\d)", source):
                yield "number_mutation", match.span(), value
                break
    for match in NAME.finditer(sentence):
        original = match[0].casefold()
        if original in source:
            replacement = next((name for name in names if name.casefold() not in source), None)
            if replacement is not None:
                yield "proper_name_swap", match.span(), replacement
                break
    for match in dates:
        value = _shift_date(match, viet=match.re == VIET_DATE)
        if value and value.casefold() not in source:
            yield "date_shift", match.span(), value
            break
    if match := VERB.search(sentence):
        value = match[0]
        value = value[6:] if value.casefold().startswith("không ") else f"không {value}"
        yield "clause_negation", match.span(), value


def inject_errors(
    summary: str, source: str, donor_summary: str, *, source_title: str = ""
) -> list[SyntheticCase]:
    sentences = tuple(split_sentences(summary))
    if not sentences:
        return []
    cases = {}
    source = f"{source_title}\n{source}".casefold()
    donor_names = tuple(
        dict.fromkeys([*(match[0] for match in NAME.finditer(donor_summary)), "Nguyễn Minh An"])
    )
    for index, sentence in enumerate(sentences):
        for kind, (start, end), value in _edits(sentence, source, donor_names):
            if kind in cases:
                continue
            changed = sentence[:start] + value + sentence[end:]
            cases[kind] = SyntheticCase(
                kind,
                (*sentences[:index], changed, *sentences[index + 1 :]),
                tuple(i != index for i in range(len(sentences))),
            )
    for donor_sentence in split_sentences(donor_summary):
        if (
            len(words(donor_sentence)) >= 5
            and donor_sentence.casefold() not in source
            and donor_sentence.casefold() not in summary.casefold()
        ):
            kind = "cross_article_insertion"
            cases[kind] = SyntheticCase(
                kind, (*sentences, donor_sentence), (True,) * len(sentences) + (False,)
            )
            break
    return list(cases.values())
