"""One preloaded CPU ViT5 instance, bounded inference, and an offline smoke CLI."""

import argparse
import json
import resource
import time
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import Settings, get_settings
from app.services.model_artifacts import ModelArtifactError, validate_artifacts

MAX_INPUT_TOKENS = 1024
MAX_NEW_TOKENS = 256
MAX_SOURCE_CHARACTERS = 20_000

# Authored fictional text: safe for independent model/provider feasibility checks.
SMOKE_TITLE = "Thư viện thử nghiệm mở lớp kỹ năng số miễn phí"
SMOKE_TEXT = (
    "Trong bản tin giả định phục vụ kiểm thử, thư viện Bình Minh mở lớp kỹ năng số miễn phí "
    "cho người dân vào sáng thứ bảy. Lớp học hướng dẫn tìm kiếm thông tin, sử dụng thư điện tử "
    "và nhận biết các đường dẫn lừa đảo. Chương trình có 30 học viên, được chia thành ba nhóm "
    "để thực hành trên máy tính của thư viện. "
    "Theo kế hoạch thử nghiệm, bốn tình nguyện viên sẽ hỗ trợ học viên trong sáu tuần. "
    "Người tham gia được cung cấp tài liệu tiếng Việt và không phải mua thiết bị hay đóng phí. "
    "Thư viện sẽ lấy ý kiến sau mỗi buổi học để điều chỉnh nội dung phù hợp với người cao tuổi. "
    "Ban tổ chức cho biết mục tiêu của chương trình là giúp người dân tiếp cận dịch vụ công "
    "trực tuyến an toàn hơn. Đây hoàn toàn là tình huống hư cấu, không phải tin từ nhà xuất bản."
)


@dataclass(frozen=True)
class SummaryResult:
    summary: str
    inference_text: str
    input_truncated: bool
    input_tokens: int
    generated_tokens: int
    latency_seconds: float


class SummaryService:
    def __init__(self, settings: Settings) -> None:
        path = Path(settings.SUMMARIZATION_MODEL_PATH)
        validate_artifacts(path, settings.SUMMARIZATION_MODEL_ID)
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        # Too many CPU threads can make small, sequential decoder steps much slower.
        torch.set_num_threads(settings.SUMMARIZATION_CPU_THREADS)
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                path,
                local_files_only=True,
                use_fast=False,
            )
            self.model = AutoModelForSeq2SeqLM.from_pretrained(
                path,
                local_files_only=True,
            ).to("cpu")
            self.model.eval()
            if self.tokenizer.eos_token_id is None:
                raise ValueError("Tokenizer requires EOS")
        except Exception as exc:
            raise ModelArtifactError(f"Cannot load local ViT5 artifacts in {path}.") from exc
        self.model_id = settings.SUMMARIZATION_MODEL_ID

    def summarize(self, source_text: str, *, attempt: int = 1) -> SummaryResult:
        if not source_text.strip() or len(source_text) > MAX_SOURCE_CHARACTERS:
            raise ValueError("Source must contain 1–20,000 characters of cleaned text")
        if type(attempt) is not int or attempt not in {1, 2}:
            raise ValueError("At most two draft attempts are supported")
        import torch

        started = time.perf_counter()
        # T5 adds EOS itself. Reserve its slot when truncating; never add a chat prefix.
        token_ids = self.tokenizer.encode(source_text, add_special_tokens=False)
        if token_ids and token_ids[-1] == self.tokenizer.eos_token_id:
            token_ids.pop()
        truncated = len(token_ids) + 1 > MAX_INPUT_TOKENS
        retained = token_ids[: MAX_INPUT_TOKENS - 1]
        input_ids = torch.tensor([retained + [self.tokenizer.eos_token_id]], dtype=torch.long)
        inference_text = self.tokenizer.decode(retained, skip_special_tokens=True)
        with torch.inference_mode():
            output = self.model.generate(
                input_ids=input_ids,
                attention_mask=torch.ones_like(input_ids),
                max_new_tokens=MAX_NEW_TOKENS,
                num_beams=4 if attempt == 1 else 2,
                length_penalty=1.0 if attempt == 1 else 0.8,
                no_repeat_ngram_size=3,
                early_stopping=True,
                do_sample=False,
            )
        summary = self.tokenizer.decode(output[0], skip_special_tokens=True).strip()
        if not summary:
            raise RuntimeError("ViT5 produced an empty summary")
        return SummaryResult(
            summary=summary,
            inference_text=inference_text,
            input_truncated=truncated,
            input_tokens=input_ids.shape[1],
            generated_tokens=len(output[0]) - 1,
            latency_seconds=time.perf_counter() - started,
        )


@lru_cache(maxsize=1)
def get_summary_service() -> SummaryService:
    """Call at worker startup, then reuse; API modules never import/load the model."""
    return SummaryService(get_settings())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-test", action="store_true", required=True)
    parser.parse_args()
    started = time.perf_counter()
    try:
        service = get_summary_service()
        result = service.summarize(SMOKE_TEXT)
    except (ModelArtifactError, RuntimeError, ValueError) as exc:
        print(f"Local model smoke test failed: {exc}")
        return 1
    print(
        json.dumps(
            {
                "model_id": service.model_id,
                **asdict(result),
                "total_seconds": time.perf_counter() - started,
                "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
