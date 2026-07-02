# Current State

> If this file conflicts with the current branch or commits, trust git.

- Current phase: **engine documentation foundation cleanup**.
- Current objective: keep repository guidance and planning aligned with the 0–19 maturity model
  before advancing another engine level.
- Branch policy: feature and documentation PRs target `dev`; `main` is the curated user-stable
  branch. Windows install/update tooling always follows `main`.

## Product snapshot

- Docker Compose runs a React/Vite SPA behind nginx and a private FastAPI backend.
- The product supports upload, document listing/deletion, Audit, OCR/Text, detection-only PII, and
  lineage-safe manual inspection. It does not redact, anonymize, or pseudonymize documents.
- Originals, metadata, and immutable derived artifacts use separate validated storage boundaries.
- OCR/Text routes each PDF page between a usable text layer and the adapter-bound PaddleOCR runtime;
  DOCX extraction includes paragraphs, tables, headers, and footers.
- PII uses Presidio/spaCy behind an adapter, named profiles, AT/DE and domain recognizers, candidate
  validation, and reproducible engine settings.
- The local private benchmark measures routing and PII quality from existing artifacts. Its
  committed test suite uses synthetic data; private corpus data remains under git-ignored volumes.

## Engine maturity snapshot (0–19)

- **OCR/Text: L5 done.** L6 OCR confidence and L7 `quality_report` are next.
- **PII/Sensitive-Data: L9 done; L10 partial.** Dev-only human-feedback capture exists; grouping
  (L11), overlap resolution (L12), and binding review (L13) remain open.
- **Review/Human-Feedback: L2 production; L3–L5 dev-only.** Grouping (L6) and a lineage-bound
  `review_result` overlay (L8) remain open.
- **Benchmark/Regression: L8 done.** L9 per-profile reporting in one run is next.
- **Redaction/De-Identification: L0 by design.** It remains blocked on mature OCR, PII, and review
  foundations.

See [`docs/engine/`](../docs/engine/README.md),
[ADR-0016](../docs/adr/0016-engine-maturity-levels-0-19.md), and
[ADR-0017](../docs/adr/0017-entity-taxonomy-and-risk-classes.md).

## Dev feedback boundary

- When `ENABLE_DEV_ENGINE_SETTINGS=true`, per-entity feedback is appended locally to
  `volumes/document-data/<document_id>/feedback/pii_feedback.jsonl`.
- This is a gated analysis side-channel, not a learning system and not the binding review artifact.
- The structured fingerprint excludes raw document/entity text. Optional comments and future opaque
  fields can still contain sensitive input, so the file belongs inside the protected document-data
  boundary and must not be described as privacy-safe by construction.

## Governance checkpoint

- Core OCR, NER, redaction, and pseudonymization intelligence comes from established tools behind
  adapters.
- Adapter-bound Presidio pattern recognizers, context rules, candidate validation, domain
  recognizers, and small deterministic heuristics are permitted only when documented, tested,
  benchmarkable, reviewable, and auditable.
- Major architecture/dependency changes, large opaque rule systems, or ad-hoc intelligence require
  human approval before implementation.

## Immediate next steps

The binding OCR/PII sequence, cadence, and next-12-PR list live in
[`docs/engine/ocr-pii-implementation-plan.md`](../docs/engine/ocr-pii-implementation-plan.md)
([ADR-0018](../docs/adr/0018-ocr-pii-implementation-plan.md)). **Current priority: OCR/Text
confidence (L6) + `quality_report` (L7) before further deep PII work**, so the core text engine stays
2–3 levels ahead of the PII/review frontier.

The OCR L8/L9 text-layer work (canonical `best_text_result` vs new `readable_text` vs
`layout_text_result`) is contract-first: the output model and invariants are fixed in
[`docs/engine/ocr-layout-text-contract.md`](../docs/engine/ocr-layout-text-contract.md) **before**
any implementation. `best_text_result` stays canonical/offset-stable; the readable and layout layers
are additive and never a PII input.

1. Fix feedback integrity as a focused bugfix (finish dev-only PII L10 / Review L5 operational use).
2. Advance OCR/Text to **L6 — OCR confidence**.
3. Advance OCR/Text to **L7 — `quality_report`**.
4. Then interleave PII **L11 grouping** / **L12 overlap** per the plan's cadence.

**Checkpoint loop:** after every engine PR, record which level changed, confirm OCR/Text is still
sufficiently ahead of PII/Redaction, check for benchmark/feedback-driven re-prioritisation and
config/artifact drift, and update state/docs; after every third PR, re-confirm or adjust the next
three PRs (see the plan's checkpoint loop).

## Active constraints

- Docker-first; no host-local application toolchain is required.
- Keep changes focused and `.ai/` files concise.
- Do not read or commit private material under `volumes/`.
- Follow the approval, branch, and PR rules in [`AGENTS.md`](../AGENTS.md).
