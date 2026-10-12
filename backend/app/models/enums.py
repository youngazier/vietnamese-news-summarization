from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class ProcessingStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class ContentOrigin(StrEnum):
    EXTRACTED = "extracted"
    RSS_EXCERPT = "rss_excerpt"


class Category(StrEnum):
    POLITICS = "politics"
    ECONOMY = "economy"
    TECHNOLOGY = "technology"
    SOCIETY = "society"
    SPORTS = "sports"
    OTHER = "other"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"


def string_enum(enum_class: type[StrEnum], *, name: str) -> SAEnum:
    """Persist enum values as VARCHAR(20) with a named database check."""
    return SAEnum(
        enum_class,
        values_callable=lambda members: [member.value for member in members],
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=20,
        name=name,
    )
