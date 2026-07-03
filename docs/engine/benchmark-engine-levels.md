# Benchmark / Regression Engine — Levels 0–19

The benchmark engine makes OCR/Text and PII quality **measurable and non-regressing**. It is not a
product surface; it is the instrument that tells every other engine "where are we, and did the last
change help or hurt". It reads existing artifacts only — it never triggers processing and never
holds raw text or PII values.

Hard constraints:

- **Local-only, private inputs.** The corpus, its metadata, and the candidate PII ground truth live
  only under the git-ignored `volumes/benchmark/`. Nothing real is ever committed.
- **Privacy-guarded output.** `privacy_guard.py` blocks any report write containing a forbidden
  field name or a PII-shaped string. Reports carry aggregate metrics only.
- **Read-only.** It reads `document.json`/`audit_result`/`text_result`/`quality_report`/`pii_result`; missing
  artifacts are reported as `missing`, never generated.

Level numbers are cumulative and **not** comparable to the other ladders. This engine uses the
**0–19 maturity scale** ([why 0–19](README.md#maturity-scale)).

**Current standing:** **L8 done (L0–L8); L9 next, with an out-of-order L10 slice.** The stdlib-only runner
([ADR-0010](../adr/0010-private-benchmark-runner.md), `scripts/benchmark/`,
`make benchmark-private`) delivers corpus matching, OCR/text routing correctness, PII P/R/F1 per
doc/type/group/global, privacy-guarded and deterministic reports, candidate-validation counts, and
lineage-matched OCR confidence/coverage columns with legacy fallback. Per-profile runs in one
invocation, OCR runtime columns, trend/history, and a CI gate are open.

---

## 0–19 at a glance

| Band | Levels | Theme |
| --- | --- | --- |
| Foundations | 0–3 | No benchmark → private corpus + ground truth → coverage/matching |
| Core metrics | 4–8 | Routing correctness, PII P/R/F1, privacy guard, determinism, validation-aware |
| Breadth | 9–12 | Per-profile PII, OCR confidence, OCR runtime/memory, multi-engine comparison |
| Trend + gate | 13–15 | Run history/trend, regression thresholds, CI gate |
| Loop-closing | 16–19 | Feedback-derived ground truth, curated GT, redaction completeness, production suite |

---

## Level 0 — No benchmark

- **Description:** quality is unmeasured; changes are judged by eyeballing.
- **Acceptance:** n/a.
- **Boundary to L1:** L1 introduces any repeatable manual inspection.

## Level 1 — Ad-hoc manual inspection

- **Description:** a human opens a few documents and judges output by hand.
- **Acceptance:** a documented manual spot-check procedure exists.
- **Boundary to L2:** L2 defines a machine-readable corpus + ground-truth format.

## Level 2 — Private corpus + candidate ground truth  ✅ *done*

- **Description:** a private benchmark input format (document metadata + candidate PII ground truth)
  under `volumes/benchmark/`.
- **Artifacts:** `volumes/benchmark/ocr_pii_benchmark_*.json` (git-ignored).
- **Acceptance:** the format captures expected routing category and candidate PII spans per document,
  without committing anything real.
- **Boundary to L3:** L2 defines inputs; L3 matches them to produced artifacts.

## Level 3 — Corpus coverage / artifact matching  ✅ *done*

- **Description:** map each benchmark document to its produced artifacts and report coverage.
- **Acceptance:** documents with missing `audit_result`/`text_result`/`pii_result` are reported as
  `missing`, not generated; coverage is summarised.
- **Boundary to L4:** L3 knows what exists; L4 scores OCR/text routing.

## Level 4 — OCR/text routing correctness  ✅ *done*

- **Description:** score per-page routing (text-layer vs OCR) against the expected category and report
  the page-status distribution.
- **Acceptance:** routing correctness and GOOD/LOW/BROKEN/EMPTY distribution appear per document and
  aggregate.
- **Boundary to L5:** L4 scores routing; L5 scores PII detection quality.

## Level 5 — PII P/R/F1  ✅ *done — reporting baseline*

- **Description:** precision/recall/F1 per document, per type, per group, and global, against the
  candidate ground truth.
- **Acceptance:** a run reports TP/FP/FN and P/R/F1 at all four granularities from existing
  `pii_result` artifacts.
- **Boundary to L6:** L5 produces numbers; L6 guarantees they never leak raw content.

## Level 6 — Privacy-guarded reports  ✅ *done*

- **Description:** guarantee reports can never contain raw text or PII values.
- **Acceptance:** `privacy_guard.py` blocks a write with a forbidden field name or PII-shaped string;
  `make benchmark-test` covers it.
- **Boundary to L7:** L6 makes output safe; L7 makes it reproducible.

## Level 7 — Deterministic / reproducible runs  ✅ *done*

- **Description:** identical inputs produce identical reports (timestamps aside).
- **Acceptance:** two consecutive `make benchmark-private` runs produce byte-identical reports up to
  timestamps.
- **Boundary to L8:** L7 stabilises the numbers; L8 adds validation-stage metrics.

## Level 8 — Validation-aware metrics  ✅ *done*

- **Description:** aggregate the PII candidate-validation stage corpus-wide (kept/dropped/score_down
  + reason-code counts).
- **Acceptance:** a run reports validation counts and reason-code histograms without any candidate
  text.
- **Boundary to L9:** L8 covers one profile per invocation; L9 runs all profiles in one.

## Level 9 — Per-profile PII metrics in one invocation  ⛔ *open (next)*

- **Description:** run every configured profile and compare P/R/F1 side by side in one command.
- **Acceptance:** one invocation emits per-profile metrics; today this requires a rerun per configured
  profile. Completes the PII L2/L9 "per-profile validation posture" reporting.
- **Boundary to L10:** L9 broadens PII coverage; L10 adds OCR quality columns.

## Level 10 — OCR confidence / coverage columns  ⏳ *delivered out of order*

- **Description:** add per-document OCR confidence and coverage to the report (needs OCR L6–L7).
- **Acceptance:** met for L7 artifacts: confidence and pages-without-text coverage appear in JSON,
  markdown, and CSV summaries; lineage mismatches fall back to legacy audit/text metrics. The
  cumulative benchmark level remains L8 until L9 is delivered.
- **Boundary to L11:** L10 measures OCR quality; L11 measures OCR cost.

## Level 11 — OCR runtime / memory / performance columns  ⛔ *open*

- **Description:** add runtime-per-page and peak-memory columns (needs OCR L17).
- **Acceptance:** performance columns appear and can be budgeted.
- **Boundary to L12:** L11 measures one engine; L12 compares engines.

## Level 12 — Multi-engine comparison metrics  ⛔ *open*

- **Description:** compare OCR engines (CER/WER on synthetic GT, runtime, memory) to support OCR L12
  selection.
- **Acceptance:** per-engine quality/cost metrics let the pipeline justify a per-page selection.
- **Boundary to L13:** L12 compares within a run; L13 compares across time.

## Level 13 — Run history / trend  ⛔ *open*

- **Description:** persist runs and compare metrics over time.
- **Acceptance:** a stored run history lets a change be attributed to a metric delta.
- **Boundary to L14:** L13 shows trends; L14 sets pass/fail thresholds.

## Level 14 — Regression thresholds  ⛔ *open*

- **Description:** define thresholds that a metric must not drop below.
- **Acceptance:** a run flags a metric that regressed past its threshold.
- **Boundary to L15:** L14 defines thresholds; L15 enforces them in CI.

## Level 15 — CI regression gate  ⛔ *open*

- **Description:** run the benchmark (synthetic/private) in CI and block a merge on regression.
- **Acceptance:** an intentional regression fails the gate; a neutral change passes. Feeds OCR L18
  and PII L19.
- **Boundary to L16:** L15 gates on hand-authored GT; L16 improves the GT from review.

## Level 16 — Feedback-derived ground truth  ⛔ *open*

- **Description:** ingest human review corrections (Review L14) into the benchmark inputs.
- **Acceptance:** confirmed/rejected/added decisions improve the candidate GT without exporting PII
  outside `volumes/`.
- **Boundary to L17:** L16 grows the GT; L17 curates its quality.

## Level 17 — Curated ground-truth quality  ⛔ *open*

- **Description:** track GT quality/agreement (candidate GT → curated GT with confidence).
- **Acceptance:** metrics distinguish curated from candidate GT; agreement is recorded.
- **Boundary to L18:** L17 curates detection GT; L18 measures redaction.

## Level 18 — Redaction completeness metrics  ⛔ *open*

- **Description:** measure masked-span coverage vs reviewed spans (needs the Redaction engine).
- **Acceptance:** redaction completeness (residual-PII-after-redaction = 0) is measurable on a corpus.
- **Boundary to L19:** L18 adds redaction metrics; L19 unifies everything into a production suite.

## Level 19 — Production regression suite  ⛔ *open*

- **Description:** full trend + thresholds + CI across OCR, PII, and redaction.
- **Acceptance:** every engine's key metrics are trended, thresholded, and gated in CI.
- **Boundary:** top of the ladder.

---

## Where the project stands (Benchmark/Regression)

| Level | State | Evidence |
| --- | --- | --- |
| 0–1 | ✅ superseded | manual inspection replaced by the runner |
| 2 Private corpus + GT | ✅ done | `volumes/benchmark/ocr_pii_benchmark_*.json` |
| 3 Coverage / matching | ✅ done | reports `missing` artifacts, coverage |
| 4 Routing correctness | ✅ done | routing category + page-status distribution |
| 5 PII P/R/F1 | ✅ done | per doc/type/group/global |
| 6 Privacy-guarded | ✅ done | `privacy_guard.py` + `make benchmark-test` |
| 7 Deterministic | ✅ done | identical reports across runs |
| 8 Validation-aware | ✅ done | kept/dropped/score_down + reason codes |
| 9 Per-profile in one run | ⛔ next | today: rerun per configured profile |
| 10 OCR confidence columns | ⛔ open | needs OCR L6–L7 |
| 11 OCR runtime/memory | ⛔ open | needs OCR L17 |
| 12 Multi-engine comparison | ⛔ open | single OCR engine |
| 13 Run history / trend | ⛔ open | single snapshot |
| 14 Regression thresholds | ⛔ open | — |
| 15 CI gate | ⛔ open | not wired into CI |
| 16 Feedback-derived GT | ⛔ open | GT hand-authored |
| 17 Curated GT quality | ⛔ open | candidate GT only |
| 18 Redaction completeness | ⛔ open | no redaction engine yet |
| 19 Production suite | ⛔ open | — |

**Next:** per-profile PII metrics in one invocation (L9), then OCR confidence/coverage columns (L10)
once OCR L6–L7 land. See [`roadmap.md`](roadmap.md) (Engine-1 done; trend/CI folded into Engine-2 +
a later CI task).

---

## Legacy scale note

The previous engine snapshot rated the benchmark at "L2 (reproducible metrics)" on an informal
scale. On the 0–19 scale the same capability set (matching, routing, P/R/F1, privacy guard,
determinism, validation counts) maps to **L8** — the finer scale simply resolves what was one coarse
level into several testable ones.
