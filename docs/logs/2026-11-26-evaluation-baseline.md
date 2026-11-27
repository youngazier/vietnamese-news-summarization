# Priority 1 evaluation baseline

**Date:** 2026-11-26 · **Branch:** `feat/evaluation-baseline` · **Specs:** [summarization](../specs/summarization.md), [testing](../specs/testing.md), [database](../specs/database.md)

## Measured baseline

The current first-draft ViT5 configuration ran offline on 20 articles from the pinned VietNews test split with four CPU threads. ROUGE values are macro-average F1 on Unicode Vietnamese word tokens.

| Metric | Result |
| --- | ---: |
| ROUGE-1 | 0.4492 |
| ROUGE-2 | 0.3261 |
| ROUGE-L | 0.3574 |
| ViT5 CPU inference per article, mean | 4.38 s |
| ViT5 CPU inference per article, p50 | 4.86 s |
| ViT5 CPU inference per article, p95 | 6.53 s |
| Peak evaluation process RSS | 1,775.71 MiB |

The sampler used zero-based test TSV rows `3600, 17219, 7288, 4529, 2401, 12842, 2583, 2952, 2850, 12440, 4371, 11323, 293, 18881, 13005, 1168, 1442, 10088, 5412, 12522` from [VietAI's published test split](https://github.com/vietai/ViT5/blob/b3886e9a9f8d29837aa156b11f840977cf7565be/data/vietnews/test.tsv). The local ViT5 model manifest SHA-256 was `32464337ecc609b12d997d39ddc2d695e83bd3689330effff2b14f8a78c155a1`.

## Calibration status

| Check | Result |
| --- | --- |
| Calibration inputs | 50 stored cross-source rows (30 VnExpress, 20 Tuổi Trẻ), including 40 freshly ingested rows with preserved `<p>` paragraphs and `publisher_meta` plus one legacy RSS excerpt. |
| Extraction gate | 49 accepted and one `rss_excerpt_only` rejection. Against the 50-article AI-assisted review (`47` valid, `3` invalid: RSS excerpt, broken Tuổi Trẻ mega-story stub, VnExpress image puzzle), default thresholds scored precision `0.9592`, recall `1.0000`, F1 `0.9792` (`tp=47, fp=2, fn=0, tn=1`). |
| Frozen ViT5 drafts | 49 first drafts with model input snapshots. AI-assisted faithfulness audit on the 47 valid extractions found 18 faithful (`38.3%`), 29 unfaithful (`61.7%` — invented dates/units, flipped facts, copied `ĐỌC NGAY` text), and 15 faithful paraphrases. |
| Synthetic set | 24 labeled corruptions generated in `.evaluation/synthetic-v2.json` across the VietNews slice, covering all five mutation classes (`number_mutation`, `proper_name_swap`, `date_shift`, `clause_negation`, `cross_article_insertion`). |
| Live Gemini | Paced `--stage synthetic --request-delay 6` received HTTP 429 (`retry_deferred: true`) on its first wire request (`gemini-3.8-flash`). Judge metrics, Cohen's κ, stability, Gemini-paired gate tuning and live per-article Gemini cost wait for API quota reset. |
| Retention exemption | Migrations `0005` and `0006` applied to the dev database (`0006 (head)`); `eval protect` marked all 50 calibration rows `evaluation_exempt=True`. |

The cross-source labeled snapshot is `.evaluation/calibration-labeled.json` (SHA-256 `ec2144bee65d3b40456e666f9fed03c1426ee9bd41872e9eba4f2b19e973c55e`; labels are AI-assisted and ready for optional human spot-check). Stored publisher text, ViT5 drafts and synthetic cases remain gitignored local inputs.

## Reproduce the measured portion

Download the pinned test TSV and follow the [evaluation setup](../specs/testing.md#priority-1-evaluation) for the calibration inputs.

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked python -m app.cli.eval --local-only --calibration .evaluation/calibration-labeled.json
```

Ruff lint and formatting passed. The non-integration suite passed 308 tests with four opt-in skips. The isolated PostgreSQL 16 suite passed 118 tests. SDK fixture tests verified logical and wire counts, including retries and deferral of a long retry delay. The package build included the evaluation CLI and emitted an existing uv/uv-build version-range warning.

## Follow-up

Optionally spot-check the 50 AI-assisted labels in `.evaluation/calibration-labeled.json`, unblock the ~430–525 live Gemini calls (Tier 1 billing, higher-RPD model, or checkpointed slicing) to run `synthetic`, `calibration`, `stability` and `graph`, and compare tuned thresholds against held-out labels before changing defaults.
