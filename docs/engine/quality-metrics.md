# Quality Metrics

This document defines how OCR/Text, PII, review, and benchmark quality are measured. Current
planning uses the **0–19 maturity scale**. `make benchmark-private` reads existing local artifacts;
private inputs and reports remain under git-ignored `volumes/`.

Legend: ✅ covered today · ⏳ partially covered · ⛔ not yet measured.

## OCR / Text metrics

| Metric | Meaning | Today |
| --- | --- | --- |
| CER / WER | character/word error against a reference transcript | ⛔ — planned for synthetic ground truth at OCR L12 |
| Character-count deviation | extracted vs expected character count | ⏳ — final count reported; no expected baseline |
| Word-count deviation | extracted vs expected word count | ⏳ — final count reported; no expected baseline |
| Page coverage | pages with/without final text | ✅ — persisted in `quality_report` and benchmarked |
| OCR confidence | engine confidence per OCR page/line | ✅ — L6 metrics; L7 document summary |
| Source per page | text layer vs OCR | ✅ |
| Routing correctness | actual routing vs expected category | ✅ |
| Page-status distribution | GOOD/LOW_CONFIDENCE/BROKEN/EMPTY counts | ✅ |
| Document quality summary | source mix, coverage, low-confidence counts | ✅ — immutable OCR L7 `quality_report` |
| Readability | paragraphs, line breaks, de-hyphenation | ⛔ — OCR L8 |
| Layout order | blocks, columns, headings | ⛔ — OCR L9 |
| Table/form reconstruction | structured region quality | ⛔ — OCR L11 |
| Runtime / memory | wall-clock time and peak memory | ⛔ — OCR L17 |

CER/WER requires reference text. Real customer-document transcripts are not stored for this purpose;
use synthetic or explicitly approved private ground truth only.

## PII metrics

| Metric | Meaning | Today |
| --- | --- | --- |
| expected / detected | ground-truth and pipeline candidate counts | ✅ |
| TP / FP / FN | matched, extra, and missed candidates | ✅ |
| precision / recall / F1 | detection quality | ✅ |
| per-type / per-group metrics | quality by entity type and type group | ✅ |
| per-profile metrics | named profiles compared in one invocation | ⏳ — one active artifact set per run; Benchmark L9 open |
| unsupported types | ground-truth types absent from the run's configured types | ✅ |
| validation reasons | candidate-validation kept/dropped/score-down counts | ✅ |
| review-derived FP/FN reasons | binding human decisions categorised for regression | ⛔ — requires Review L8–L14 |

The dev-only PII feedback JSONL captures per-entity verdicts and issue types for later analysis. It
is not a `review_result`, does not change the immutable `pii_result`, and is not yet consumed as
benchmark ground truth or a binding review-correction metric.

## Benchmark / regression metrics

| Metric | Meaning | Today |
| --- | --- | --- |
| repository version | code revision used for a report | ⏳ — repository commit, not per-engine version |
| model version | OCR/PII model identity | ⏳ — available in artifacts, not fully surfaced in reports |
| profile | active PII profile | ⏳ — recorded in `pii_result`, not compared in one invocation |
| corpus and artifact coverage | matched/missing documents and artifacts | ✅ |
| routing mismatch | routing vs expectation | ✅ |
| validation-stage aggregates | kept/dropped/score-down reason counts | ✅ |
| deterministic output | identical result for identical inputs | ✅ |
| run history / trend | compare metrics over time | ⛔ — Benchmark L13 |
| regression thresholds | explicit pass/fail limits | ⛔ — Benchmark L14 |
| CI gate | block regressions during review | ⛔ — Benchmark L15 |

## Current benchmark coverage

`make benchmark-private` covers artifact matching, OCR routing and page-status distribution, source
mix, OCR confidence/coverage, final character/word counts, PII TP/FP/FN and P/R/F1 per document/type/group/global,
unsupported types, candidate-validation aggregates, and the privacy guard.

The next metric steps are:

1. Benchmark L9: compare all configured PII profiles in one invocation.
2. Benchmark L13–L15: history, thresholds, and CI enforcement.
3. Review L14 / Benchmark L16: promote curated binding review decisions into private ground truth.

## Aggregate private benchmark snapshot

The current snapshot covers a 12-document private corpus plus one unsupported input. Figures are
aggregate regression signals against candidate ground truth, not validated accuracy claims.

- OCR routing matched the expected category for 10 of 12 documents; the two differences were more
  conservative all-page OCR decisions on poor scans.
- PII L6 candidate validation raised `review-heavy` global precision from 0.1964 to 0.4487 while
  recall changed from 0.5694 to 0.5646.
- For `insurance-at-de`, candidate validation raised precision from 0.7064 to 0.7404 with unchanged
  recall of 0.3684.
- PII L8 address/contact-line coverage reached P=0.6667, R=0.8462, F1=0.7458 for the new group and
  reduced unsupported labels to `BIRTH_DATE`, `BIRTH_PLACE`, `FAMILY_NAME`, and `GIVEN_NAME`.
- Consecutive runs per profile were deterministic apart from timestamps.

No document names, extracted text, or raw entity values are reproduced here.
