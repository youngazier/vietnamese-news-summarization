

# 12/10

`@lru_cache`
Example:
```python
from functools import lru_cache

@lru_cache
def get_engine() -> Engine
```
- `lru_cache` remembers a function's return value. When you call that function again with the same arguments, Python returns the saved value instead of executing the function again.

---

`factory`
Example:
```python
@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
    )

factory = get_session_factory()
session = factory()
```
- A factory is an object you can call to create another object  
- Cache the factory, because its configuration is reusable. Each call to `factory()` creates a new session
- `expire_on_commit=False` keeps already-loaded attribute values available after committing, rather than expiring them for a later reload

---

# 17/10 - Phase 3: RSS feed -> DB Articles

## RSS
RSS = **Really Simple Syndication** - a structured feed that a website publishes so applications can discover new content automatically.

Instead of opening a news homepage and inspecting its HTML, your application requests a feed such as:
```
https://vnexpress.net/rss/tin-moi-nhat.rss
```
The response is **XML**, containing a list of published items: A simplified example:
```xml
<rss version="2.0">
  <channel>
    <title>Publisher’s latest news</title>
    <link>https://publisher.example/</link>
    <description>Latest articles</description>

    <item>
      <title>New community library opens</title>
      <link>https://publisher.example/news/library-123</link>
      <description>A short introduction to the article...</description>
      <pubDate>Sat, 17 Oct 2026 08:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
```

A feed typically contains a recent window of articles, rather than the publisher's complete archieve. An application checks it periodically to discover updates; RSS does not automatically push each article to your application.

In this project, the flow is:
```
Request RSS URL
    → receive XML bytes
    → parse with feedparser
    → create FeedEntry objects
    → insert new articles into PostgreSQL
```


---

# Pydantic
Pydantic is the project's data validation and serialization layer. It helps answer three questions:
1. Does incoming data have the excepted structure and values?
2. Can we turn it into useful Python objects?
3. Can we turn those objects into dictionaries, JSON, or a schema describing the expected data?

## `BaseModel` - define a validated data structure
A regular Python type hint does not automatically validate values:
```python
def collect(limit: int):
    return limit

collect("twenty") # Python itself does not enforce the annotation
```

A Pydantic model does:
```python
from pydantic import BaseModel

class CollectionOptions(BaseModel):
    limit: int

options = CollectionOptions(limit=20)
print(options.limit) # 20
```
Invalid data raises `ValidationError`:
```python
CollectionOptions(limit="twenty")
```
By default, Pydantic can convert compatible values:
```python
options = CollectionOptions(limit="20")
print(options.limit) # 20
print(type(options.limit)) # <class 'int'>
```

## `ConfigDict` - configure how the model behaves
Phase 3 uses: `model_config = ConfigDict(extra="forbid", strict=True)`
- `model_config` is a special configuration attribute recognized by Pydantic. These settings apply to the model.
- `extra="forbid"` rejects unexpected fields
```python
from pydantic import BaseModel, ConfigDict

class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int

Options(limit=20, limti=30)  # ValidationError: unexpected "limti"
```
- `strict=True` prevents many automatic type conversions:
```python
class StrictOptions(BaseModel):
    model_config = ConfigDict(strict=True)
    limit: int

StrictOptions(limit=20)    # Valid
StrictOptions(limit="20")  # ValidationError
```
### Note: JSON validation vs. Python-object validation
JSON has no native data type, so a data string such as `"2026-10-18"` can be accepted for a `date` field during JSON validation. Strict validation of a Python dictionary generally expects an actual `date` object for that field.

That matters when choosing between `model_validate()` and `model_validate_json()` later.

## `Field` - add constraints, defaults, and field metadata
Example 1: `name: str = Field(min_length=1, max_length=120)`

Example 2: `attempts: int = Field(ge=1, le=2)`

The main numeric constraints are:

|Argument|Meaning|
|-|-|
|`gt=0`|Greater than zero|
|`ge=1`|Greater than or equal to one|
|`lt=10`|Less than ten|
|`le=2`|Less than or equal to two|

## `@model_validator` - validate relationships between fields
Fields contraints handle individual values. Some rules depend on multiple fields.

My `SourceConfig` needs rules such as:
```
If extraction is enabled:
    the source must be active
    an extraction policy must exist
```
That is why it uses:
```python
@model_validator(mode="after")
def validate_review(self) -> "SourceConfig":
    ...
    return self
```
- `model="after"` means the individual fields have already been validated, so the method can inspect their parsed values through `self`.

Here is a simplified example:
```python
from pydantic import BaseModel, model_validator

class ExtractionOptions(BaseModel):
    enabled: bool
    selector: str | None = None

    @model_validator(mode="after")
    def require_selector(self) -> "ExtractionOptions":
        if self.enabled and not self.selector:
            raise ValueError("Enabled extraction requires a selector")
        return self
```

```python
ExtractionOptions(enabled=False)  # Valid

ExtractionOptions(
    enabled=True,
    selector="article.news-body",
)  # Valid

ExtractionOptions(enabled=True)  # ValidationError
```

The same pattern appears ion `ReviewResult`:
```python
if not self.approved and not self.feedback:
    raise ValueError("Rejected drafts require feedback")
```


## `@field_validator` - apply custom validation to one field

Example: The AI schema uses this for keywords:
```python
@field_validator("keywords")
@classmethod
def distinct_keywords(cls, keywords: list[str]) -> list[str]:
    normalized = [
        unicodedata.normalize("NFC", keyword)
        for keyword in keywords
    ]

    if len({keyword.casefold() for keyword in normalized}) != len(normalized):
        raise ValueError("Keywords must be distinct")

    return normalized
```
This function:
1. Receives the validated keyword list.
2. Normalizes Unicode representations.
3. Checks for case-insensitive duplicates.
4. Returns the normalized list.

For example:
```python
ArticleMetadata(
    category="technology",
    keywords=["AI", "ai", "Dữ liệu"],
)
```
is rejected because `"AI"` and `"ai"` are treated as duplicated.

The return value becomes the field's value. A validator can therefore both check and normalize data.

`@classmethod` is a Python feature, not a Pydantic import. It supplies the class as `cls`; there is no completed instance to receive as `self` in this field validator.

The practical choice is:

|Requirement|Use|
|-|-|
|Check or normalize one field|`field_validator`|
|Check relationships across fields|`model_validator`|

## `TypeAdapter` - validate a type without creating a wrapper model
Phase 3 needs to validatae a JSON array:
```json
[
  {"name": "Source A", "...": "..."},
  {"name": "Source B", "...": "..."}
]
```
The outer structure is a `list[SourceConfig]`, not a single `SourceConfig`.

The code uses: `TypeAdapter(list[SourceConfig]).validate_json(json_text)`

This validates:
- The outer list
- Every source object
- Each nested extraction policy
- All applicable custom validators






# Supabase
## Project initialization
- Enable automatic RLS (Row Level Security): ordinary API users cannot read or modify their rows
    - React calls FastAPI, and FastAPI connects through SQLAlchemy using the Supabase `postgres` database account. That privileged account bypasses RLS, so this setting should not block your database probe or backend operations.

## Connect to your project
- Direct
    - Connection method: **Session pooler**
    - Type: **URI**


## Day 2 migration progress — 2026-10-12

- D2.3: lazy engine/session factory implemented; 14 session tests. Full foundation suite previously passed 37 tests.
- D2.4: Alembic reads DATABASE_URL from settings rather than the generated `driver://` INI placeholder. Model metadata comes from the shared Base.
- D2.5: revision 0001 generated and reviewed. Autogeneration produced repeated enum CHECKs; fixed using VARCHAR(20) plus one explicit CHECK per enum in the migration. The ORM keeps its enum helper.
- Offline SQL matches all model constraint names and indexes. The developer reports the corrected upgrade working. Hosted enforcement tests were subsequently implemented and reported passing on 2026-10-14.
- The next task at this point was D2.6–D2.7; these are now complete as recorded below.


## Day 2 progress — 2026-10-14

- D2.1–D2.7 complete in the checklist. Hosted D2.7 success is developer-reported; no new hosted run was performed during the documentation update.
- `tests/integration/conftest.py` creates one generated disposable schema per test, supplies the migration connection/version-table schema, binds sessions to that connection, and cleans up its owned schema.
- 28 collected cases cover migration lifecycle, uniqueness, foreign keys, enum/check constraints, defaults/relationships, timestamp round trips, transaction rollback and deletion rules.
- Moved migration files to `backend/alembic/` and configuration to `backend/alembic.ini`. Root `[tool.alembic]` in `pyproject.toml` keeps `uv run --locked alembic ...` working from the repository root; integration fixture paths were updated.
- Verified root/default migration discovery and offline migration SQL. Current head is `0002`; it renames `model_name` to `summarize_model_name` and has data-preservation lifecycle coverage.
- Dependencies remain managed by root `pyproject.toml`/`uv.lock`: clone and run `uv sync --locked`. The temporary requirements export/helper were removed.
- D2.8–D2.9: response schemas and registered source/list/detail routes are implemented, including literal title search, filters, stable ordering, pagination, matching counts, and approved-summary visibility rules.
- D2.10: repeatable inactive source configuration seeding and a fictional PostgreSQL API fixture are implemented. The focused hosted run passed 2 tests; health/session regression passed 15 tests.
- D2.11–D2.12 complete: 14 API cases cover 404/422/503, redaction, filter/page ordering, literal wildcard search, preview limits, and approved/rejected/not-ready summary visibility. README records the final setup. Unit suite: 37 passed; complete hosted PostgreSQL suite: 44 passed.


## Day 3 progress — 2026-10-14

- D3.2–D3.9 are implemented. D3.1 remains open because Thanh Niên reuse is unresolved; its source stays inactive.
- `config/sources.json` records dated official-feed evidence, exact host allowlists, attribution and separate RSS-reader/extraction/AI decisions. VnExpress and Tuổi Trẻ are active only for the reviewed RSS-reader scope.
- `rss_collector.py` uses an explicit user agent, a 15-second HTTP timeout, a shared three-request retry/redirect budget, bounded backoff, a 2 MiB decoded-body limit and exact-host redirect validation.
- Feed parsing produces cleaned title/link/optional date/RSS description records. Invalid entries are skipped, malformed feeds fail explicitly and valid empty feeds succeed.
- URL normalization removes fragments, default ports and known tracking parameters while preserving path/query distinctions that may identify different articles.
- `ingestion.py` uses PostgreSQL `ON CONFLICT DO NOTHING RETURNING id`; duplicates preserve existing rows and do not consume the 20-new-article cap. Network work occurs outside the write transaction.
- Five hosted ingestion tests cover repeat ingestion, REST visibility, preservation of an existing processed row, insertion-cap behavior, rollback and a two-session race. The complete suite passed 127 tests.
- Live VnExpress verification parsed 51 usable entries, inserted 20, replayed those 20 with zero new rows, and returned the pending article through source/list/detail REST calls.
- D4 is next: evaluate permitted extraction or RSS fallback, persist source-text provenance and reject inadequate text without an AI call.
