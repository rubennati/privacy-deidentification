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
| false-positive categories | *why* something was a FP (stopword/generic/no-context) | ⏳ — Engine-5 `dropped_by_reason`/`score_down_by_reason` cover *validator* reasons; review-sourced FP reasons still need Review L4 |
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
types per document, corpus-wide candidate-validation counts (kept/dropped/score_down + reason-code
breakdowns), and the privacy-guard pass/fail gate.

**Missing (mapped to the level that adds it):**
- OCR **confidence**, **runtime/page**, **peak memory** → OCR L4 / L8.
- **CER/WER** on a synthetic corpus (privacy-safe) → OCR L4+ (synthetic only).
- **Layout readability**, **table reconstruction quality** → OCR L5–L7.
- Benchmark comparison across **multiple profiles** in one run → PII L4. Review-sourced FP/FN
  categories (*why a human rejected/added* a candidate) → Review L4.
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
- **PII global (`review-heavy`), Engine-4 final → Engine-5 (candidate validation on)** — expected
  stayed 209. Detected 606 → 263, TP 119 → 118, FP 487 → 145, FN 90 → 91, precision
  0.1964 → 0.4487, recall 0.5694 → 0.5646, F1 0.2920 → 0.5000.
- **PII global (`insurance-at-de`), Engine-4 final → Engine-5** — expected 209, detected 109 → 104,
  TP 77 → 77, FP 32 → 27, FN 132 → 132, precision 0.7064 → 0.7404, recall unchanged 0.3684,
  F1 0.4843 → 0.4920. NER is intentionally unsupported by this profile.
- **PII, structured group** — unchanged by Engine-5 in both profiles: precision 0.7937, recall
  0.8772, F1 0.8333 (light/pass-through types).
- **PII, NER group (`review-heavy`)** — 42 TP / 455 FP / 29 FN (P≈0.08, R≈0.59) →
  41 TP / 118 FP / 30 FN (P=0.2579, R=0.5775, F1=0.3565): FP fell 74% for one lost true positive.
- **PII, domain-sensitive group (both profiles)** — 27 TP / 19 FP / 20 FN (P=0.5870, R=0.5745) →
  27 TP / 14 FP / 20 FN (P=0.6585, R=0.5745, F1=0.6136): 5 unlabelled `BIC` candidates scored down.
- **Candidate validation (`review-heavy`)** — kept=263, dropped=14, score_down=329 across 12/12
  documents with validation enabled. Dropped by reason: `TOO_SHORT_SINGLE_TOKEN`=10,
  `GENERIC_DOCUMENT_WORD`=2, `NER_SINGLE_COMMON_WORD`=1, `NUMERIC_ONLY_FOR_NER`=1. Score-down by
  reason: `ORG_WITHOUT_ORG_SIGNAL`=147, `LOCATION_WITHOUT_LOCATION_SIGNAL`=108,
  `MISSING_REQUIRED_CONTEXT`=69, `BIC_WITHOUT_FINANCIAL_CONTEXT`=5.
- **Determinism** — two consecutive runs per profile produced identical reports (timestamps aside).

Interpretation: Engine-4 materially improved structured/domain recall; Engine-5 then more than
doubled global precision on `review-heavy` (FP −70%) and lifted `insurance-at-de` precision
slightly, both for negligible true-positive loss (1 TP each) — confirming candidate validation is
the correct lever for NER noise rather than turning NER off. Address/contact-line and the other
five semantic labels remain unsupported. Reports stay private under `volumes/`; rerun with
`make benchmark-private` after generating PII artifacts for the profile being compared.
