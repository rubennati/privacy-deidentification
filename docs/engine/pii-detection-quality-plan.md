# PII Detection & Display Quality Plan (foundation-first)

> **Purpose.** PII maturity (grouping/overlap/review/manual-add, L11–L14) advanced *ahead of*
> detection quality. This plan makes **detection + raw↔canonical display quality** an explicit
> **foundation gate** that must be met on the private corpus before PII advances to L15+ or any
> redaction work begins. It is the PII counterpart to OCR's "contract-first" discipline.
>
> See the binding gate in [`.ai/quality-gates.md`](../../.ai/quality-gates.md#pii-detection--display-foundation-gate)
> and the level ladder in [`pii-engine-levels.md`](pii-engine-levels.md).

## Frozen baseline (2026-07-02, `review-heavy`, 12 corpus docs, 209 ground-truth entities)

Global: **P = 0.47 · R = 0.67 · F1 = 0.55** (140 TP / 158 FP / 69 FN). The average hides that the
error is highly concentrated. Per-type, grouped by problem:

| Bucket | Types (baseline) | Root cause |
| --- | --- | --- |
| ✅ Strong | IBAN 7/7, IP 4/4, BIC 4/4, PHONE R0.86/P0.90, EMAIL R0.89/P0.89, DATE_TIME R0.92 | structured regex + checksum recognizers work |
| 🔴 Precision (over-tagging) | **LOCATION 0 exp / 69 FP**, PERSON P0.27 (27 FP), URL P0.31 (9 FP), ORG P0.43 → NER group **120 FP** | weak `de_core_news_sm` over-tags; LOCATION is not a ground-truth target; missing cross-type precedence |
| 🟠 Critical-ID recall holes (R=0) | **SVNR_AT 0/3**, ID_CARD 0/2, PASSPORT 0/1, LICENSE_PLATE 0/2, CREDIT_CARD 0/1, PROJECT_ID/USER_ID 0/1, TAX_ID R0.33 | context/label-gated recognizers too strict |
| 🟠 NER recall | ORG **R0.28** (23 FN), PERSON 5 FN | model weakness |
| ⚫ Unsupported (structural FN) | BIRTH_DATE 0/4, BIRTH_PLACE 0/2, FAMILY_NAME 0/1, GIVEN_NAME 0/1 | no recognizer exists |

This baseline maps 1:1 onto the reviewer-observed defects: names missed while their email is found
(PERSON/ORG recall), an email substring also tagged as a domain/URL (URL 9 FP + no cross-type
precedence), a table/heading line tagged ADDRESS (ADDRESS 10 FP), and pervasive over-tagging
(LOCATION 69 FP, NER 120 FP).

## Scope decisions

- **Bare `LOCATION` is not a standalone target type.** It produced 69 FP / 0 TP. Personal
  *residence* location is already captured by `ADDRESS` (street + `PLZ Ort`); *birthplace* is the
  only genuinely sensitive single location and is handled by a context-gated `BIRTH_PLACE`
  recognizer (see below). Remove blanket `LOCATION` from `review-heavy`; do not redact every city.
- The four currently-unsupported ground-truth types (`BIRTH_DATE`, `BIRTH_PLACE`, `FAMILY_NAME`,
  `GIVEN_NAME`) are in scope for the gate and need recognizers/context rules.

## Tool-first principle

Prefer upgrading/adding proven local open-source tools behind the existing Presidio adapter over
hand-written recognizers. Deterministic pattern/context recognizers remain allowed where documented,
tested, and benchmarkable (per [`AGENTS.md`](../../AGENTS.md)). No cloud/external calls, ever.

## Prioritized action list (by measured impact)

1. **Remove blanket `LOCATION`** from the profile — removes 69 FP; global precision 0.47 → ~0.65.
   *(scope/config, no model)*
2. **Harden critical-ID recognizers to ~100% recall** — `SVNR_AT`, `ID_CARD_NUMBER`,
   `PASSPORT_NUMBER`, `LICENSE_PLATE_AT`, `CREDIT_CARD`, `TAX_ID_AT`. Widen their context/label
   coverage (currently they only fire on an exact adjacent label/separator). These are P3; a miss is
   a leak. *(deterministic recognizer tuning)*
3. **NER upgrade spike (tool-first)** — benchmark GLiNER vs. `de_core_news_lg` vs.
   `de_dep_news_trf`; adopt the winner behind the adapter for PERSON/ORGANIZATION recall. Add an
   **email-local-part → name corroboration** recognizer (derive "Franz Hubermeier" from
   `franzhubermeier@…`, confirm by presence in the text). *(tool + deterministic enrichment)*
4. **Cross-type precedence** in `pii_overlap.py` — email > inner URL/domain; ADDRESS > LOCATION.
   The precedence table deferred in [ADR-0028](../adr/0028-pii-intake-document-text-package-v1.md).
5. **Close the 4 unsupported types** — `BIRTH_PLACE`/`BIRTH_DATE` via context rules on the
   place/date candidate; `GIVEN_NAME`/`FAMILY_NAME` via PERSON sub-typing or the NER model.
6. **Re-tune candidate validation** — only after the NER upgrade, so the aggressive NER score-downs
   (`ORG_WITHOUT_ORG_SIGNAL`, `LOCATION_WITHOUT_LOCATION_SIGNAL`) do not eat the recall gain.
7. **Display parity (L17 lineage)** — raise raw↔canonical highlight parity to the gate threshold;
   remaining declines must carry an explicit reason code, never be silent.

Each step is measured against the gate before the next; no step tunes to corpus-specific values.

## Corpus layout (private, never committed)

The corpus lives under `volumes/test-corpus/`, so it is git-ignored by the existing `/volumes/*` rule
(the whole `volumes/` tree is the private data root, `DATA_ROOT`); real documents and ground truth
never enter the repo. It holds two distinct corpora:

- `volumes/test-corpus/reading-text/` — the **OCR reading-text** acceptance fixtures (`source.*` +
  `expected-reading-text.md` + `acceptance.md` per document). Local OCR validators mount this as
  `/corpus` (they read `/corpus/reading-text`).
- `volumes/test-corpus/pii-benchmark/documents/` — the **PII detection** source documents (drop
  folder). The PII ground-truth annotations live in
  `volumes/benchmark/ocr_pii_benchmark_pii_groundtruth.json`. The benchmark matches uploaded
  documents to ground truth by display filename, so files must keep the ground-truth's canonical
  names.

Only the 4 synthetic `TEST_0x` documents overlap between the two corpora.

## Measurement protocol

1. Place the PII source documents in `volumes/test-corpus/pii-benchmark/documents/` (canonical
   filenames matching the ground truth).
2. Upload each through the app (`upload → OCR → PII`, `review-heavy`), preserving the filename.
3. `make benchmark-private` → per-type P/R/F1 (privacy-guarded; no raw text in reports).
4. Compare against the per-type gate thresholds; a regression on any met type fails the change.

The corpus is small (~12 docs); completing ground truth for the 4 unsupported types and expanding
toward ~20–30 documents is a parallel workstream to make a 95% claim statistically meaningful.
