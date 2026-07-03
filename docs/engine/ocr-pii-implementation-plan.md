# OCR / PII Implementation Plan & Checkpoint Loop

An operative plan that turns the [0–19 maturity ladders](README.md#maturity-scale) into an ordered,
reviewable PR sequence for the two core engines — **OCR/Text** and **PII/Sensitive-Data** — and a
checkpoint loop that re-validates the plan after every PR.

This document is the OCR/PII-focused, operative companion to [`roadmap.md`](roadmap.md). Where the
roadmap gives the authoritative near-term order, this plan adds the cadence rule, the checkpoint
loop, and the OCR-vs-PII sequencing rationale. It **invents no new level numbers** — every level here
is defined in [`ocr-engine-levels.md`](ocr-engine-levels.md) and
[`pii-engine-levels.md`](pii-engine-levels.md).

The output-model contract for technical raw `text_result.text`, canonical `reading_text`, internal
`pii_input_text`, legacy `readable_text`, and `layout_text_result`, tied by a future
`text_lineage_map`, is fixed in [`ocr-layout-text-contract.md`](ocr-layout-text-contract.md).

## Purpose

- **OCR/Text and PII/Sensitive-Data are the core engines.** Everything else — Review, Feedback,
  Benchmark, Audit, and later Redaction — exists to support and measure these two.
- The plan exists to **prevent ad-hoc feature work**: agents (Codex, Claude Code, others) advance
  OCR/PII systematically along the ladders instead of adding whatever seems locally convenient.
- Each planned step names the engine, the level it advances, its goal, its non-scope, and a testable
  acceptance criterion, so a PR maps to exactly one level transition (or an explicit non-level
  hardening step).

## Core principle

- **OCR/Text stays 2–3 maturity levels ahead of PII/Redaction.** PII detection, review, feedback, and
  later redaction all consume clean text, structure, source-lineage, confidence, and (later) bounding
  boxes. If OCR lags, everything above it is built on sand.
- **PII must not be built on poor OCR/Text structure.** A PII step that depends on an OCR capability
  which is not yet at the required level is **blocked** until that OCR level lands.
- **Redaction is blocked** until OCR/Text, PII, and Review are jointly stable — concretely until
  reviewed decisions (Review L8–L9), stable/resolved PII spans (PII L17–L18), and OCR
  text-to-geometry mapping (OCR L10/L15) exist. Redaction is intentionally the last engine.

## Current standing

Copied from the per-engine docs and [`roadmap.md`](roadmap.md) — not re-derived here.

| Engine | Current level | Next |
| --- | --- | --- |
| OCR / Text | **L11 done (built on the L10.5 contract step)** | PII L11 grouping → PII L12 overlap |
| PII / Sensitive-Data | **L9 done; L10 partial** (dev-only feedback capture) | L11 grouping → L12 overlap |
| Review / Human-Feedback | **L2 production; L3–L5 dev-only** | L6 grouping → L8 `review_result` |
| Benchmark / Regression | **L8 done; L10 slice out of order** | L9 per-profile metrics |
| Redaction / De-Identification | **L0 by design** | blocked (see core principle) |

OCR/Text (L11, built on the L10.5 contract step) is currently ahead of the *binding* PII/review
frontier (PII L10 partial,
Review L2 prod). The 2–3-levels-ahead rule is comfortably satisfied today; the risk is PII deep work
(grouping/overlap/review) outrunning the OCR text-quality/geometry it will eventually need.

## OCR / Text roadmap

Priority order. Level numbers are the authoritative ones from
[`ocr-engine-levels.md`](ocr-engine-levels.md); the parenthetical notes reconcile the informally
labelled goals in the request.

1. **OCR L6 — OCR confidence foundation — delivered.** Capture engine-reported confidence per OCR
   page (and per line where available), additively on `text_result`, as metrics only. Immutable
   `audit_result` artifacts remain unchanged.
2. **OCR L7 — `quality_report` — delivered.** A metrics-only per-document summary (source mix,
   coverage, low-confidence counts, confidence summary) with exact original/audit/text lineage; no
   page text.
3. **OCR L8 — human-readable text / `best_text_result` split — delivered.** Introduce a readable
   rendering while keeping today's `text_result` as the canonical `best_text_result`. PII offsets
   keep referencing only the canonical text.
4. **OCR L9 — layout-aware blocks — delivered.** Preserve `layout_text_result` and add deterministic
   ordered/typed review blocks with coarse normalized page bounds from existing pypdf positions or
   transient PaddleOCR polygons — still not the PII input and not L10 geometry.
5. **OCR L10 — bounding boxes / span geometry — delivered.** Additive `text_geometry` maps canonical
   line spans to page-local line boxes (`pdf_points`/`image_pixels`) with per-page status and overall
   coverage, plus an internal `resolve_span_geometry` canonical-offset → page-box lookup. Offsets are
   matched against the immutable canonical text, so canonical/page text stays byte-stable and PII
   still runs on canonical text only. This provides line-level source anchoring and traceability, and
   a foundation for future placeholder mapping toward AI-ready pseudonymized document generation.
   Word-level geometry and a full `text_lineage_map` remain open. *(Per-page source lineage already
   exists at OCR L2; this adds line-geometry-level mapping — it is not new lineage from scratch.)*
6. **OCR L10.5 — canonical reading text / raw-text contract — delivered intermediate step.** Keep
   `text_result.text` byte-stable as technical raw text and the current PII offset basis; add
   optional versioned `reading_text` as the deterministic, block-aware main text with explicit
   heuristic/fallback metadata. User View defaults to reading text; Dev View keeps raw, reading, and
   layout access. No PII switch, lineage claim, structured JSON, placeholder mapping, or export.
   This is an explicitly named prerequisite between defined levels, not a replacement 0–19 level.
7. **OCR L11 — table / form reconstruction — delivered.** Optional versioned
   `structured_content` adds span-backed rows/cells, label/value fields, and sections across PDF,
   OCR/image, and DOCX paths. Conservative deterministic heuristics flag uncertainty and reuse L10
   line bounds/L9 headings when available. Technical raw text and active PII input remain unchanged.
8. **OCR L13 — document understanding.** Document-type / section / zone semantics to inform PII,
   review, and later redaction.
9. **OCR L15+ — redaction-ready text/geometry mapping.** The stable canonical-offset ↔ page-pixel
   mapping that a future Redaction engine requires (with L12 multi-engine selection and L14 local-AI
   assist as optional branches).

Points to describe explicitly as these levels are built:

- **Page boundaries.** The readable rendering must mark where one page ends and the next begins,
  without those markers corrupting canonical offsets.
- **Header / footer representation.** Running headers/footers should be identifiable (and separable)
  in the readable/layout output, not silently interleaved into body text.
- **Readable page transitions.** Cross-page paragraphs should read continuously in the readable
  rendering while the canonical text stays byte-stable.
- **Tables in readable text form.** Tables must render in a human-readable, row/column-aligned way in
  `layout_text_result` (L9) before full structural reconstruction (L11) — readability first,
  structure later.
- **Address blocks.** Header/address blocks should be recognisable as blocks (feeds PII ADDRESS and
  the header/address-block context hardening the PII engine already uses).
- **Source lineage.** Per-page source (`text_layer`/`paddleocr`) is already delivered (OCR L2);
  layout/geometry work extends it to per-block lineage.
- **OCR confidence.** First-class from L6 on `text_result.pages[]`, surfaced additively and consumable by the benchmark
  without reading raw text.
- **Human-readable but offset-safe text.** Reading/readable/layout renderings must **never** mutate
  technical raw `text_result.text`; PII continues to run only on raw text so offsets never drift.

## PII / Sensitive-Data roadmap

Priority order, authoritative levels from [`pii-engine-levels.md`](pii-engine-levels.md).

1. **Finish PII L10 — feedback capture operational use.** Make the existing dev-only per-entity
   feedback reliable (fingerprint/lineage validation, restore/lock correctness) before anything is
   built on its data. No new level; a hardening step (this is roadmap.md's "feedback integrity
   hardening").
2. **PII L11 — entity grouping + occurrences.** Present each distinct entity once with its
   occurrences/offsets grouped beneath it, with clickable per-occurrence jump-to-text. Grouping only;
   detection is unchanged.
3. **PII L12 — overlap / entity resolution.** Deterministic, auditable engine-level precedence for
   duplicate/nested/overlapping candidates (not the display-only highlight resolver).
4. **PII validation transparency report.** Surface the *already-stored* candidate-validation summary
   (kept/dropped/score_down + reason codes from `pii_result`) as a readable transparency view. No new
   detection, no benchmark-logic change.
5. **PII L13 — review confirm / reject.** Binding confirm/reject persisted in a `review_result`
   overlay bound to lineage (jointly with Review L8–L9); `pii_result` stays immutable.
6. **PII L14 — manual add / missed entities.** Let a reviewer add a missed span (`origin = human`),
   producing a recall signal.
7. **PII L15 — feedback-to-regression.** Promote confirmed/rejected/added decisions into the private
   benchmark ground truth (locally, never leaving `volumes/`).
8. **PII L17/L18 — stable entity model / redaction-ready spans.** A stable, resolved, lineage-complete
   entity model whose spans (with OCR L10/L15 geometry) are redaction-ready.

Points to describe explicitly as these levels are built:

- **`ADDRESS` should suppress an overlapping `LOCATION`.** A structured address span should win over a
  bare NER `LOCATION` covering the same text (overlap resolution, L12).
- **`EMAIL_ADDRESS` should suppress URL/domain fragments.** A URL/domain fragment inside an e-mail
  address must not survive as a competing entity (L12).
- **Precise deterministic recognizers win over broad NER.** On overlap, structured/domain ids
  (`IBAN`/`UID`/`FN`/policy/claim…) take precedence over generic NER spans (L12) — deterministic
  precision beats statistical recall where they conflict.
- **Repeated entities are grouped with clickable occurrences.** One entity, many offsets, each
  clickable to its span (L11); feedback can attach per occurrence or per group.
- **Feedback guides future regression tests.** Captured/confirmed feedback (L10 → L15) becomes
  regression ground truth so recurring detection errors are caught automatically, not rediscovered.

## Interleaving rule

- **Standard cadence: 2 OCR/Text PRs, then 1 PII/Review PR.** This keeps OCR/Text structurally ahead
  of the PII/review frontier (the core principle).
- **PII/Review PRs may run earlier** only when they do **not** depend on missing OCR/Text maturity —
  e.g. entity grouping (L11), overlap resolution (L12), and feedback hardening (L10) operate on
  existing canonical text and need no new OCR capability, so they can interleave.
- **Redaction PRs are blocked** until the prerequisites are explicitly satisfied (reviewed decisions,
  stable/resolved PII spans, OCR text-to-geometry mapping). No redaction PR is scheduled here.

The concrete [next-12-PR list](#next-12-prs) front-loads three OCR foundation PRs (confidence,
`quality_report`, `best_text_result`) before interleaving PII grouping, because the deeper PII/review
chain (overlap → review → redaction) structurally depends on OCR text quality and geometry that must
exist first. This is the cadence applied, not an exception to it.

## Checkpoint loop

**After every PR**, answer:

1. Which engine level changed (or which explicit non-level hardening was done)?
2. Is OCR/Text still sufficiently ahead of PII/Redaction (2–3 levels)?
3. Did benchmark or feedback data reveal a new priority?
4. Did the PR introduce config or artifact drift (settings not recorded, lineage gaps, schema drift)?
5. Are the docs and `.ai/state.md` updated to match the new standing?
6. Is the next planned PR still valid, or does the sequence need re-ordering?

**After every third PR**, additionally:

- Re-read this implementation plan and [`roadmap.md`](roadmap.md) and confirm or adjust the **next 3
  PRs**.
- Check whether feedback reports reveal recurring PII/OCR issues that should be promoted in priority.
- Check whether benchmark metrics actually support the next planned step (e.g. do not add OCR
  benchmark columns before OCR L6/L7 provide the source metrics).

## Next 12 PRs

`Level advanced` cites the authoritative OCR/PII levels; a "v1"/"foundation"/"report" PR may deliver
a slice of a level rather than fully completing it. PR 1 is this document. This list is consistent
with [`roadmap.md`](roadmap.md)'s near-term sequence (its items 2–5 correspond to the feedback
hardening + OCR L6/L7 here).

| Order | PR title | Engine | Level advanced | Goal | Non-scope | Acceptance |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | OCR/PII implementation plan + checkpoint loop | Planning | none | This doc + cadence + checkpoint loop | code, recognizers, API/UI, benchmark, DB, redaction | plan doc merged; links valid; agents can follow it |
| 2 | OCR confidence foundation (delivered) | OCR/Text | **OCR L6** | capture per-page (and per-line where available) OCR confidence, additively | routing changes, `quality_report`, geometry, tables, new OCR tool | OCR pages carry confidence when reported; canonical text + routing unchanged; benchmark reads the metric without raw text |
| 3 | OCR `quality_report` (delivered) | OCR/Text | **OCR L7** | metrics-only per-document quality summary with lineage | page text, layout, geometry, redaction | each OCR/Text run has an immutable `quality_report` with no page text or raw PII |
| 4 | OCR `best_text_result` v1 (delivered) | OCR/Text | **OCR L8** | readable rendering seed; canonical `best_text_result` unchanged | layout order, geometry, tables, AI rewriting | a readable rendering exists beside a byte-stable canonical text; PII offsets still reference canonical text |
| 5 | PII entity grouping + occurrences | PII | **PII L11** | group repeated same-type occurrences with clickable offsets | detection changes, overlap resolution, review persistence | repeated mentions render as one group with correct per-occurrence offsets; no detection dropped/invented |
| 6 | OCR layout-aware blocks (delivered) | OCR/Text | **OCR L9** | layout-aware reading order + typed blocks; coarse normalized bounds; page boundaries/headers/footers | precise line/word geometry (L10), tables (L11), lineage map, redaction | multi-column/header-footer pages produce deterministic review blocks; canonical text remains the PII input |
| 7 | PII overlap / entity resolution | PII | **PII L12** | deterministic engine-level precedence (ADDRESS>LOCATION, EMAIL>URL-fragment, structured>NER) | new detection, NER retuning, AI | overlapping candidates resolve deterministically without dropping distinct entities; decisions are auditable |
| 8 | PII validation transparency report | PII | none (surfaces L6 data) | readable view of stored validation counts/reason codes | new detection, benchmark-logic change, DB | a transparency view reflects `pii_result` validation summary; no raw candidate text; no new metrics computed |
| 9 | OCR span geometry (delivered) | OCR/Text | **OCR L10** | additive `text_geometry` mapping canonical line spans to page-local line boxes + `resolve_span_geometry` lookup | word-level geometry, tables, lineage map, pseudonymization/placeholder mapping/export | line geometry maps to canonical coordinates; per-page lineage and canonical text remain unchanged |
| 9a | OCR canonical reading text (delivered prerequisite) | OCR/Text | **L10.5 intermediate** | versioned block-aware `reading_text`; relabel legacy `text` as technical raw; exact synthetic quote fixture | PII input switch, lineage map, structured content, pseudonymization/export | User View defaults to useful reading text; raw/page text and PII behavior remain unchanged |
| 10 | Review result artifact | Review / PII | **Review L8 (→ PII L13)** | immutable, lineage-bound `review_result` overlay | confirm/reject UI actions (next), rules, DB migration | a `review_result` persists bound to `pii_result`+`text_result` and re-renders; `pii_result` immutable; re-extraction marks it stale |
| 11 | OCR table/form reconstruction (delivered) | OCR/Text | **OCR L11** | additive span-backed tables, fields, and sections with conservative confidence/flags | PII-input switch, pseudonymization/placeholder mapping/export, UI | representative PDF/OCR/DOCX structures resolve to raw/reading spans; raw text and PII input remain unchanged |
| 12 | Feedback-to-regression workflow | PII / Review | **PII L15 / Review L14** | promote reviewed corrections into private benchmark ground truth | exporting PII outside `volumes/`, benchmark scoring changes | corrections become private benchmark data without leaving `volumes/`; ground truth improves |

Sequencing notes: PR 4 (`best_text_result` split) precedes PR 6 (`layout_text_result`); PR 6
precedes PR 9 (span geometry), and PR 9a (`reading_text`) is required before PR 11 (structured
content). PR 10 (`review_result`) is the
prerequisite for binding PII confirm/reject (PII L13) and for PR 12. None of these unblock Redaction
on their own — Redaction stays L0 until the full prerequisite set is met.

**Latest checkpoint (OCR L11):** L11 adds no dependency, engine setting, routing change, canonical
text change, PII-input switch, quality-report change, or benchmark-report payload. Its versioned
structured-content schema is legacy compatible and the benchmark loader ignores raw structured
data. OCR L11 remains sufficiently ahead of PII L10 partial/Redaction L0; no benchmark or feedback
signal changes priority. After this third OCR structure PR (L9–L11), the next three remain PII L11
grouping, PII L12 overlap resolution, and the lineage-bound Review L8 artifact foundation.

## References

- [`README.md`](README.md) — engine capability model + 0–19 maturity scale
- [`roadmap.md`](roadmap.md) — authoritative near-term sequence (this plan is its OCR/PII companion)
- [`ocr-engine-levels.md`](ocr-engine-levels.md) / [`pii-engine-levels.md`](pii-engine-levels.md) —
  the authoritative level definitions
- [`review-feedback-levels.md`](review-feedback-levels.md),
  [`benchmark-engine-levels.md`](benchmark-engine-levels.md),
  [`redaction-engine-levels.md`](redaction-engine-levels.md) — supporting engines
- [`engine-settings.md`](engine-settings.md) — settings/artifact drift to watch in the checkpoint loop
- [`entity-taxonomy.md`](entity-taxonomy.md) — what is detected and how sensitive it is
- [ADR-0018](../adr/0018-ocr-pii-implementation-plan.md) — the decision behind this plan
