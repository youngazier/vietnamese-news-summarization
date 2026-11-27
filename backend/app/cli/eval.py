"""Evaluate the MVP pipeline and manage local, frozen calibration inputs."""

import argparse
import json
import resource
import sys
from collections import Counter
from dataclasses import asdict
from math import isfinite
from pathlib import Path

from app.core.config import get_settings
from app.evaluation.baseline import (
    EVALUATION_STAGES,
    MeasuredGemini,
    calibrate_gate,
    gate_reasons,
    local_benchmark,
    online_benchmark,
    prepare_labels,
    synthetic_batches,
)
from app.evaluation.corpus import (
    VIETNEWS_REVISION,
    VIETNEWS_URL,
    freeze_snapshot,
    protect_snapshot,
    read_snapshot,
    read_vietnews,
    sha256,
    write_private_json,
    write_snapshot,
)
from app.services.model_artifacts import MANIFEST_NAME, ModelArtifactError
from app.services.summary_service import get_summary_service
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

DATA_DIR = Path(".evaluation")
CALIBRATION = DATA_DIR / "calibration.json"
VIETNEWS = DATA_DIR / "vietnews-test.tsv"


def positive_int(value: str) -> int:
    integer = int(value)
    if integer < 1:
        raise argparse.ArgumentTypeError("Expected a positive integer")
    return integer


def request_delay(value: str) -> float:
    seconds = float(value)
    if not isfinite(seconds) or seconds < 0:
        raise argparse.ArgumentTypeError("Expected a finite, nonnegative delay in seconds")
    return seconds


def report(sections: dict[str, object]) -> str:
    lines = ["# Priority 1 evaluation baseline", ""]
    for section, values in sections.items():
        lines.extend([f"## {section}", "", "```json"])
        lines.append(json.dumps(values, ensure_ascii=False, indent=2, allow_nan=False))
        lines.extend(["```", ""])
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    vietnews = []
    if args.stage in {"all", "synthetic"}:
        vietnews = read_vietnews(args.vietnews, args.vietnews_limit)
        if not vietnews:
            raise ValueError("Empty VietNews slice")
    snapshot = read_snapshot(args.calibration) if args.calibration.exists() else None
    if snapshot is None and not args.local_only and args.stage != "synthetic":
        raise ValueError("Online evaluation requires a frozen calibration snapshot")
    items = snapshot.items if snapshot else []
    model = get_summary_service() if args.stage in {"all", "graph"} else None
    sections = {
        "Inputs": {
            "vietnews_test_revision": VIETNEWS_REVISION,
            "vietnews_rows": [row[0] for row in vietnews],
            "calibration_sha256": sha256(args.calibration) if snapshot else None,
            "calibration_sources": dict(Counter(item.source for item in items)),
            "calibration_human_extraction_labels": sum(
                item.extraction_valid is not None for item in items
            ),
            "calibration_human_summary_labels": sum(
                item.summary_faithful is not None for item in items
            ),
            "calibration_accepted_full_text_summaries": sum(
                bool(item.accepted_summary) for item in items
            ),
            "calibration_candidate_model": snapshot.candidate_model if snapshot else None,
            "summarizer": model.model_id if model is not None else None,
            "model_manifest_sha256": (
                sha256(Path(settings.SUMMARIZATION_MODEL_PATH) / MANIFEST_NAME)
                if model is not None
                else None
            ),
            "cpu_threads": settings.SUMMARIZATION_CPU_THREADS if model is not None else None,
            "stage": args.stage,
            "request_delay_seconds": args.request_delay,
            "mvp_max_drafts": settings.MAX_GRAPH_DRAFT_ATTEMPTS,
            "synthetic_reference_limit_per_corpus": args.synthetic_limit,
        },
        **(
            {"ViT5 held-out VietNews": local_benchmark(model, vietnews)}
            if args.stage == "all"
            else {}
        ),
        "Deterministic extraction gate": {
            "passing": sum(not gate_reasons(item) for item in items),
            "rejection_reasons": dict(
                Counter(reason for item in items for reason in gate_reasons(item))
            ),
            **calibrate_gate(items, {}),
        },
    }
    failed = False
    if args.local_only:
        sections["Gemini"] = {"status": "Skipped by --local-only"}
    elif not (settings.GEMINI_API_KEY.strip() and settings.GEMINI_MODEL.strip()):
        sections["Gemini"] = {"status": "Gemini is unconfigured"}
        failed = True
    else:
        provider = MeasuredGemini(settings, request_delay=args.request_delay)
        try:
            online = online_benchmark(
                provider,
                model,
                snapshot,
                vietnews,
                max_drafts=settings.MAX_GRAPH_DRAFT_ATTEMPTS,
                synthetic_limit=args.synthetic_limit,
                stage=args.stage,
            )
            sections["Gemini"] = online
            if "gate" in online:
                sections["Deterministic extraction gate"].update(online.pop("gate"))
            failed = bool(online.get("provider_failure_stage"))
            if args.stage in {"all", "calibration"}:
                failed |= (
                    online.get("summary_human_gemini_kappa") is None
                    or online.get("real_paraphrase_false_reject_rate") is None
                    or sections["Deterministic extraction gate"].get("tuned") is None
                )
            if args.stage in {"all", "stability"}:
                failed |= online["stability_pairs"] == 0
            if args.stage in {"all", "graph"}:
                failed |= not online.get("mvp_graph", {}).get("outcomes")
            if args.stage in {"all", "synthetic"}:
                failed |= online["synthetic"]["catch_rate"] is None
            online["status"] = "Incomplete" if failed else "Measured"
        finally:
            provider.close()
    kilobytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    sections["Resources"] = {
        "peak_process_rss_mib": kilobytes / (1024**2 if sys.platform == "darwin" else 1024)
    }
    markdown = report(sections)
    if args.output:
        args.output.write_text(markdown, encoding="utf-8")
    else:
        print(markdown)
    return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        nargs="?",
        default="run",
        choices=("run", "freeze", "prepare-labels", "protect", "synthetic", "vietnews-url"),
    )
    parser.add_argument("--calibration", type=Path, default=CALIBRATION)
    parser.add_argument("--vietnews", type=Path, default=VIETNEWS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=positive_int, default=50)
    parser.add_argument("--vietnews-limit", type=positive_int, default=20)
    parser.add_argument("--synthetic-limit", type=positive_int, default=10)
    parser.add_argument("--legacy-schema", action="store_true", help="Freeze from pre-0005 schema")
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--stage", choices=EVALUATION_STAGES, default="all")
    parser.add_argument(
        "--request-delay",
        type=request_delay,
        default=6.0,
        help="Minimum seconds between Gemini HTTP requests, including retries (default: 6)",
    )
    args = parser.parse_args()
    if args.local_only and args.stage != "all":
        parser.error("--local-only cannot be combined with an individual online stage")

    try:
        match args.action:
            case "vietnews-url":
                print(VIETNEWS_URL)
            case "freeze":
                snapshot = freeze_snapshot(args.limit, legacy_schema=args.legacy_schema)
                write_snapshot(args.calibration, snapshot)
                print(f"Froze {len(snapshot.items)} stored articles.")
            case "prepare-labels":
                if args.output is None:
                    parser.error("prepare-labels requires --output for a new snapshot")
                snapshot = read_snapshot(args.calibration)
                write_snapshot(args.output, prepare_labels(snapshot, get_summary_service()))
                print(f"Prepared {len(snapshot.items)} frozen articles for human labeling.")
            case "protect":
                print(
                    f"Marked {protect_snapshot(read_snapshot(args.calibration))} articles exempt."
                )
            case "synthetic":
                if args.output is None:
                    parser.error("synthetic requires --output for a new local file")
                items = read_snapshot(args.calibration).items if args.calibration.exists() else []
                batches = list(
                    synthetic_batches(
                        items,
                        read_vietnews(args.vietnews, args.vietnews_limit),
                        args.synthetic_limit,
                    )
                )
                write_private_json(args.output, [asdict(batch) for batch in batches])
                print(f"Generated {sum(len(batch.cases) for batch in batches)} synthetic cases.")
            case "run":
                return run(args)
    except (OSError, ValidationError, ValueError, SQLAlchemyError, ModelArtifactError) as exc:
        # Validation, DB and provider diagnostics may contain article text or credentials.
        print(f"Evaluation {args.action} failed ({type(exc).__name__}).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
