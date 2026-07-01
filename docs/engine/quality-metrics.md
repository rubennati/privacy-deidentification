# Quality Metrics

How engine quality is measured. Each metric lists what it means and whether it is **covered today**
by `make benchmark-private` (the private local benchmark runner, `scripts/benchmark/`) or still
**missing**. Numbers only ever leave the machine as aggregates — `privacy_guard.py` blocks any
report containing raw text or a PII-shaped value.

Legend: ✅ covered by `make benchmark-private` today · ⏳ partially covered · ⛔ not yet measured.

## OCR / Text metrics

| Metric | Meaning | Today |
| --- | --- | --- |
| CER (character error rate) | char edit distance vs a reference transcript | ⛔ — needs reference text we deliberately do not store |
| WER (word error rate) | word edit distance vs reference | ⛔ — same reason |
| Character-count deviation | extracted vs expected char count | ⏳ — final char count reported; no expected baseline compared |
| Word-count deviation | extracted vs expected word count | ⏳ — final word count reported; no baseline |
| Page coverage | share of pages that produced usable text | ⏳ — derivable from per-page status; not a single metric yet |
| OCR confidence | engine confidence per page/line | ⛔ — **not captured** (OCR L4 gap) |
| Source per page | text_layer vs OCR per page | ✅ — per-page `text_source`, OCR/text-layer page counts |
| Routing correctness | actual routing vs expected routing category | ✅ — `routing_matches_expectation`, mismatch list |
| Page-status distribution | GOOD/LOW_CONFIDENCE/BROKEN/EMPTY counts | ✅ — aggregate page-status counts |
| Layout readability | is the text humanly readable (line/hyphenation) | ⛔ — no layout stage yet (OCR L5–6) |
| Table reconstruction quality | cell precision/recall for tables | ⛔ — no table stage (OCR L7) |
| Runtime per page | wall-clock per page | ⛔ — not measured |
| Peak memory | peak RSS during extraction | ⛔ — not measured |

**CER/WER note.** A true CER/WER needs a per-page reference transcript. Storing reference text of
real customer documents would defeat the privacy model, so CER/WER are only meaningful on a
**synthetic** corpus (known input text). This is an explicit choice, not an oversight.

## PII metrics

| Metric | Meaning | Today |
| --- | --- | --- |
| expected | ground-truth candidate count | ✅ |
| detected | pipeline-detected count | ✅ |
| tp / fp / fn | true/false positives, false negatives | ✅ |
| precision | tp / (tp+fp) | ✅ |
| recall | tp / (tp+fn) | ✅ |
| f1 | harmonic mean | ✅ |
| per-entity-type metrics | P/R/F1 per type | ✅ — per-type table |
| per-profile metrics | P/R/F1 per named profile | ⏳ — profile is recorded; runner still reports one active artifact set |
| unsupported types | GT types with no recognizer for a document | ✅ — from each doc's `configured_entity_types` |
| false-positive categories | *why* something was a FP (stopword/generic/no-context) | ⛔ — needs candidate validation + review reasons (PII L5, Review L4) |
| false-negative categories | *why* something was missed (no recognizer/format) | ⏳ — inferable from per-type FN + unsupported list; not categorised |
| review corrections | confirm/reject/add counts from humans | ⛔ — no review persistence (Review L2+) |

Grouping today: metrics are aggregated into `structured_types`, `ner_types`,
`domain_sensitive_types`, and `other_types` groups, plus per-type and global totals.

## Benchmark / regression metrics

| Metric | Meaning | Today |
| --- | --- | --- |
| run_id | identifier for a benchmark run | ⏳ — timestamped report dir; not a stored id |
| engine version | OCR/PII code version | ⏳ — `repo_commit` captured; not per-engine |
| model version | OCR/spaCy model versions | ⏳ — tool versions live in artifacts, not surfaced in the report |
| profile | active PII profile | ⏳ — recorded in new `pii_result`; not surfaced in benchmark report yet |
| document count | corpus size | ✅ |
| artifact coverage | which docs have audit/text/pii artifacts | ✅ — coverage + `missing` list |
| routing mismatch | routing vs expectation mismatches | ✅ |
| privacy guard pass/fail | did the safety check pass | ✅ — enforced before any write |

## What `make benchmark-private` covers today — summary

**Covered:** corpus coverage & matching, per-page and aggregate text-layer status distribution,
routing correctness vs expectation, text source per page/document, final char/word counts, PII
TP/FP/FN + precision/recall/F1 per document / per type / per group / global, unsupported entity
types per document, and the privacy-guard pass/fail gate.

**Missing (mapped to the level that adds it):**
- OCR **confidence**, **runtime/page**, **peak memory** → OCR L4 / L8.
- **CER/WER** on a synthetic corpus (privacy-safe) → OCR L4+ (synthetic only).
- **Layout readability**, **table reconstruction quality** → OCR L5–L7.
- Benchmark comparison across **multiple profiles** and **FP/FN categories** → PII L4/L5,
  Review L4.
- **Review corrections** as a metric → Review L2+.
- **Trend/history** across runs and a **CI regression gate** → benchmark maturity L3.

## Benchmark snapshot (aggregate private before/after run)

From one local `make benchmark-private` run over a 12-document private corpus (plus 1 unsupported
`.txt`). These are **aggregate regression signals against a candidate ground truth**, not a
validated accuracy claim, and no document names, text, or PII values are reproduced here.

- **OCR/text routing** — page statuses: 31 GOOD, 1 LOW_CONFIDENCE, 9 BROKEN, 11 EMPTY; 20 pages
  routed to OCR. Routing matched the expected category on 10/12 documents; the 2 mismatches were the
  gate routing *all* pages of a bad scan to OCR where a partial fallback was expected — more
  conservative, not incorrect.
- **PII global** — expected stayed 209. Detected 523 → 621, TP 63 → 120, FP 460 → 501,
  FN 146 → 89, precision 0.1205 → 0.1932, recall 0.3014 → 0.5742, F1 0.1721 → 0.2892.
- **PII, structured group** — precision 0.9130 → 0.6757, recall 0.3684 → 0.8772, F1
  0.5250 → 0.7634.
- **PII, NER group** (run with NER opt-in enabled) — recall ≈ 0.59 but precision ≈ 0.08: heavy
  over-tagging of `LOCATION`/`ORGANIZATION`/`PERSON`.
- **PII, domain-sensitive group** — zero coverage → 28 TP / 22 FP / 19 FN (precision 0.5600,
  recall 0.5957, F1 0.5773). Canonical mapping moved four expected labels out of `other_types`, so
  the group denominator changed from 43 to 47.

Interpretation: Engine-4 materially improves structured/domain recall. NER remains deliberately
opt-in and still needs candidate validation (PII L5); address/contact-line and related semantic
types remain unsupported. Reports stay private under `volumes/`; rerun with
`make benchmark-private` after generating PII artifacts for the profile being compared.
