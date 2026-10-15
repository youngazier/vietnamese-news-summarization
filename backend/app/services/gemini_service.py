"""Stateless metadata and review calls, with a three-request wire budget per operation."""

import json

import httpx
from app.agents.prompts import METADATA_INSTRUCTION, REVIEW_INSTRUCTION
from app.agents.schemas import ArticleMetadata, NewsDraft, ReviewResult
from app.core.config import Settings
from app.models.enums import ContentOrigin
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

REQUEST_TIMEOUT_SECONDS = 30


class GeminiServiceError(RuntimeError):
    """Provider/validation failures must never become approved output."""


class GeminiService:
    def __init__(self, settings: Settings, *, http_client: httpx.Client | None = None) -> None:
        if not settings.GEMINI_API_KEY.strip() or not settings.GEMINI_MODEL.strip():
            raise ValueError("GEMINI_API_KEY and GEMINI_MODEL are required for Gemini")
        self.model_id = settings.GEMINI_MODEL
        self.client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            vertexai=False,
            http_options=types.HttpOptions(
                api_version="v1beta",
                timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                # google-genai 2.29 Interactions maps this value to *retries*.
                retry_options=types.HttpRetryOptions(
                    attempts=2,
                    initial_delay=0.5,
                    max_delay=2,
                    jitter=0,
                    http_status_codes=[429, 500, 502, 503, 504],
                ),
                httpx_client=http_client,
            ),
        )

    def metadata(
        self,
        *,
        title: str,
        source_text: str,
        content_origin: ContentOrigin,
    ) -> ArticleMetadata:
        origin = self._validate_source(title, source_text, content_origin)
        return self._request(
            "metadata",
            METADATA_INSTRUCTION,
            {"title": title, "source_text": source_text, "content_origin": origin.value},
            ArticleMetadata,
            max_output_tokens=512,
        )

    def review(
        self,
        *,
        title: str,
        source_text: str,
        content_origin: ContentOrigin,
        inference_text: str,
        input_truncated: bool,
        draft: NewsDraft,
    ) -> ReviewResult:
        origin = self._validate_source(title, source_text, content_origin)
        if not inference_text.strip() or len(inference_text) > 20_000:
            raise ValueError("Inference text must contain 1–20,000 characters")
        if type(input_truncated) is not bool:
            raise ValueError("input_truncated must be a boolean")
        candidate = NewsDraft.model_validate(draft)
        return self._request(
            "review",
            REVIEW_INSTRUCTION,
            {
                "title": title,
                "source_text": source_text,
                "content_origin": origin.value,
                "inference_text": inference_text,
                "input_truncated": input_truncated,
                **candidate.model_dump(mode="json"),
            },
            ReviewResult,
            max_output_tokens=1024,
        )

    @staticmethod
    def _validate_source(
        title: str, source_text: str, content_origin: ContentOrigin
    ) -> ContentOrigin:
        if not title.strip() or len(title) > 500:
            raise ValueError("Title must contain 1–500 characters")
        if not source_text.strip() or len(source_text) > 20_000:
            raise ValueError("Source must contain 1–20,000 characters of cleaned text")
        return ContentOrigin(content_origin)

    def _request[Response: BaseModel](
        self,
        operation: str,
        instruction: str,
        payload: dict[str, object],
        schema: type[Response],
        *,
        max_output_tokens: int,
    ) -> Response:
        try:
            interaction = self.client.interactions.create(
                model=self.model_id,
                system_instruction=instruction,
                input=json.dumps(payload, ensure_ascii=False),
                store=False,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": schema.model_json_schema(),
                },
                generation_config={"max_output_tokens": max_output_tokens},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except Exception:  # noqa: BLE001 -- SDK has a separate Interactions error hierarchy.
            raise GeminiServiceError(f"Gemini {operation} request failed") from None
        output = interaction.output_text
        if interaction.status != "completed" or not isinstance(output, str) or not output.strip():
            raise GeminiServiceError(f"Gemini {operation} response was incomplete or empty")
        try:
            return schema.model_validate_json(output)
        except ValidationError:
            raise GeminiServiceError(
                f"Gemini {operation} response failed schema validation"
            ) from None

    def close(self) -> None:
        self.client.close()
