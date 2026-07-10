# Tasks

## Delivered foundation

- [x] Upload, validation, separated storage, document list/delete, and immutable artifacts.
- [x] Audit and OCR/Text through L5, including per-page quality routing and optional local OCR.
- [x] Detection-only PII through L9, with L10 dev-feedback capture partial.
- [x] Production read-only review through L2 and dev-only review aids through L5.
- [x] Private benchmark/regression engine through L8.
- [x] Engine maturity model (0–19) and entity taxonomy/risk classes (P0–P5).

## Current sequence

- [x] Deliver Review L8 `review_result` with explicit stale-decision state.
- [x] Surface the stored PII candidate-validation summary in a transparency view.
- [x] Benchmark L9 — report all profiles in one invocation.
- [x] Re-scope and extend construction-time OCR lineage for unchanged post-table rows.
- [x] Complete the prerequisite checkpoint and direct lineage for PII L13 / Review L9.
- [ ] PII L14 / Review L10 — manual add of missed entities.

## Later

- [x] PII L11 — entity grouping.
- [x] PII L12 — engine-level overlap/conflict resolution.
- [ ] Keep Redaction at L0 until its documented OCR/PII/Review prerequisites are met.
- [ ] Add CI/CD gates (lint/typecheck/test/SAST/SCA/SBOM and benchmark regression).
