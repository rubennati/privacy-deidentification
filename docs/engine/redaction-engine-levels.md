# Redaction / De-Identification Engine — Levels 0–19

Redaction is the **payoff** of the whole pipeline: actually removing or replacing sensitive spans in
an exported document. It is deliberately the **last** engine to be built, because a missed span
leaks PII — correctness here is safety-critical.

**Current standing: Level 0.** The system is **detection-only** by design. No redaction, masking, or
pseudonymisation exists, and building it now would be premature: the prerequisites are not yet in
place.

Level numbers are cumulative and **not** comparable to the other ladders. This engine uses the
**0–19 maturity scale** ([why 0–19](README.md#maturity-scale)).

## Why Level 0 is the correct current level

Redaction can only be trustworthy once the engines it depends on are mature. Today they are not:

| Prerequisite | Provided by | Status |
| --- | --- | --- |
| **Stable canonical spans** | PII [L17 stable entity model](pii-engine-levels.md#level-17--stable-entity-model-with-lineage---open) | ⛔ open |
| **Review decisions** (what to redact) | Review [L8–L9 `review_result` + confirm/reject](review-feedback-levels.md#level-8--review_result-artifact-model---open-first-binding-step) | ⛔ open |
| **Bounding boxes / geometry** | OCR [L10 geometry](ocr-engine-levels.md#level-10--bounding-boxes--span-geometry---open) + [L15 redaction-ready mapping](ocr-engine-levels.md#level-15--redaction-ready-textgeometry-mapping---open) | ⛔ open |
| **Redaction-ready entity model** | PII [L18 redaction-ready spans](pii-engine-levels.md#level-18--redaction-ready-entity-spans---open) | ⛔ open |

Until a reviewed decision can be mapped to an exact, stable span **and** its page geometry, a
redaction engine cannot verifiably remove the right thing. Starting earlier would build masking on
shifting offsets and unreviewed guesses — exactly the failure mode that leaks PII.

---

## 0–19 at a glance

| Band | Levels | Theme |
| --- | --- | --- |
| Not yet | 0 | Detection-only by design (**current**) |
| Foundations | 1–4 | Requirements/threat model, adapter boundary, text-masking prototype, reviewed-span gating |
| Geometry & formats | 5–8 | Box-based redaction, offset↔box mapping, multi-format, entity-model-driven |
| Guarantees | 9–13 | Pseudonymisation option, verification, no-leak, irreversibility, audit trail |
| Policy & scale | 14–18 | Policy-driven, keyed pseudonymisation, batch, performance, regression metrics |
| Production | 19 | Production-grade local de-identification |

---

## Level 0 — No redaction (detection-only)  ✅ *current, by design*

- **Description:** the pipeline labels; it never anonymises or alters source documents.
- **Acceptance:** no export path mutates a document; detection/review remain the only outputs.
- **Boundary to L1:** L1 begins design work (requirements + threat model), still no redaction code.

## Level 1 — Requirements & threat model  ⛔ *open*

- **Description:** define what "removed" means and what a leak is (visible text, copyable text,
  metadata, hidden layers, thumbnails).
- **Acceptance:** a written threat model + acceptance definition for "a span is redacted".
- **Boundary to L2:** L1 defines the target; L2 introduces the tool boundary.

## Level 2 — Adapter boundary for a redaction tool  ⛔ *open*

- **Description:** a port/interface for a redaction backend (e.g. PyMuPDF) — no implementation.
- **Acceptance:** an adapter interface exists so a redaction tool can be swapped without touching
  business logic; licensing (e.g. AGPL) is reviewed.
- **Boundary to L3:** L2 defines the seam; L3 builds a text-only prototype behind it.

## Level 3 — Text-only masking prototype  ⛔ *open*

- **Description:** replace canonical-text spans in a copy (text output only), to prove the span→mask
  path.
- **Acceptance:** given spans, a text copy has those spans masked/replaced; the original is
  untouched.
- **Boundary to L4:** L3 masks arbitrary spans; L4 restricts to reviewed spans only.

## Level 4 — Reviewed-span gating  ⛔ *open*

- **Description:** only spans approved in a `review_result` (Review L9) may be redacted.
- **Acceptance:** an unreviewed candidate is never redacted; redaction requires an approved decision
  bound to the exact lineage.
- **Boundary to L5:** L4 works on text; L5 works on page geometry.

## Level 5 — Geometry-based redaction  ⛔ *open*

- **Description:** black out page regions using bounding boxes (needs OCR L10).
- **Acceptance:** a reviewed span's page region is covered in a rendered/exported page.
- **Boundary to L6:** L5 uses boxes directly; L6 links canonical offsets to boxes reliably.

## Level 6 — Char-offset ↔ box mapping  ⛔ *open*

- **Description:** resolve canonical-text offsets to page coordinates with no drift (needs OCR L15).
- **Acceptance:** for any reviewed span, the exact covering page region(s) are returned deterministically.
- **Boundary to L7:** L6 handles one format's geometry; L7 handles all supported formats.

## Level 7 — Multi-format redaction  ⛔ *open*

- **Description:** redact PDF, DOCX, and image inputs consistently.
- **Acceptance:** each supported format redacts a reviewed span correctly on representative documents.
- **Boundary to L8:** L7 redacts spans; L8 redacts by resolved entity across all occurrences.

## Level 8 — Entity-model-driven redaction  ⛔ *open*

- **Description:** redact by resolved entity (all grouped occurrences), not one span at a time (needs
  PII L17–L18).
- **Acceptance:** approving an entity redacts every occurrence of it in the document.
- **Boundary to L9:** L8 masks; L9 adds substitution/pseudonymisation.

## Level 9 — Pseudonymisation / substitution  ⛔ *open*

- **Description:** consistent replacement (e.g. `PERSON_1`) instead of only black-box masking.
- **Acceptance:** a substituted entity reads consistently throughout the document; masking remains an
  option.
- **Boundary to L10:** L9 produces output; L10 verifies it.

## Level 10 — Redaction verification  ⛔ *open*

- **Description:** re-extract the redacted output and assert zero residual PII spans for redacted
  entities.
- **Acceptance:** re-running OCR/PII on the redacted file finds no redacted entity; verified
  automatically.
- **Boundary to L11:** L10 verifies visible text; L11 covers hidden channels.

## Level 11 — No-leak guarantees  ⛔ *open*

- **Description:** scrub metadata/XMP/hidden layers/annotations/thumbnails.
- **Acceptance:** no redacted content survives in any non-visible channel of the export.
- **Boundary to L12:** L11 removes hidden copies; L12 makes removal irreversible.

## Level 12 — Irreversibility guarantees  ⛔ *open*

- **Description:** flatten/rasterize so the original text is truly gone, not merely covered.
- **Acceptance:** the redacted region contains no recoverable underlying text.
- **Boundary to L13:** L12 guarantees removal; L13 records who decided it.

## Level 13 — Redaction audit trail  ⛔ *open*

- **Description:** record which span, which decision, which actor produced each redaction.
- **Acceptance:** every redaction traces to a reviewed decision, actor, and lineage.
- **Boundary to L14:** L13 audits actions; L14 drives them by policy.

## Level 14 — Policy-driven redaction  ⛔ *open*

- **Description:** redact per policy/profile required types (Review L15).
- **Acceptance:** a named policy determines which entity types must be redacted; completeness is
  measurable.
- **Boundary to L15:** L14 masks/removes per policy; L15 adds controlled reversibility.

## Level 15 — Reversible / keyed pseudonymisation  ⛔ *open, optional*

- **Description:** optional keyed substitution allowing controlled re-identification.
- **Acceptance:** re-identification is possible only with the key, under explicit control; default
  stays irreversible.
- **Boundary to L16:** L15 handles one document; L16 handles many.

## Level 16 — Batch / bulk redaction  ⛔ *open*

- **Description:** redact many documents reliably in one operation.
- **Acceptance:** a batch redacts consistently with per-document audit trails.
- **Boundary to L17:** L16 scales throughput; L17 hardens performance.

## Level 17 — Performance & scale hardening  ⛔ *open*

- **Description:** bound runtime/memory for large documents and batches.
- **Acceptance:** redaction meets a performance budget on the corpus.
- **Boundary to L18:** L17 hardens performance; L18 measures completeness as regression.

## Level 18 — Redaction regression metrics  ⛔ *open*

- **Description:** completeness vs reviewed spans, gated in the benchmark (Benchmark L18).
- **Acceptance:** redaction completeness is trended and gated; a regression fails the gate.
- **Boundary to L19:** L18 gates redaction; L19 is the production engine.

## Level 19 — Production-grade local de-identification  ⛔ *open*

- **Description:** reliable, verified, auditable redaction across formats, driven by reviewed
  decisions, gated by regression.
- **Acceptance:** approved spans are verifiably removed from an exported document with a full audit
  trail, meeting agreed thresholds.
- **Boundary:** top of the ladder and of the north star.

---

## Where the project stands (Redaction)

| Level | State |
| --- | --- |
| 0 Detection-only | ✅ current, by design |
| 1–19 | ⛔ open — blocked on PII L17–L18, Review L8–L9, OCR L10/L15 |

See [`roadmap.md`](roadmap.md) (Engine-9) — redaction is intentionally the final roadmap item.
