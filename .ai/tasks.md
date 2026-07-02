# Tasks

## Delivered foundation

- [x] Upload, validation, separated storage, document list/delete, and immutable artifacts.
- [x] Audit and OCR/Text through L5, including per-page quality routing and optional local OCR.
- [x] Detection-only PII through L9, with L10 dev-feedback capture partial.
- [x] Production read-only review through L2 and dev-only review aids through L5.
- [x] Private benchmark/regression engine through L8.
- [x] Engine maturity model (0–19) and entity taxonomy/risk classes (P0–P5).

## Current sequence

- [ ] Reconcile repository documentation with the 0–19 engine model.
- [ ] Fix feedback integrity in a focused bugfix.
- [ ] Prepare the next OCR/PII implementation plan.
- [ ] Advance OCR/Text to L6 — OCR confidence.
- [ ] Advance OCR/Text to L7 — `quality_report`.

## Later

- [ ] Benchmark L9 — report all profiles in one invocation.
- [ ] PII L11 — entity grouping.
- [ ] PII L12 — engine-level overlap/conflict resolution.
- [ ] Review L8 — lineage-bound `review_result` overlay.
- [ ] Keep Redaction at L0 until its documented OCR/PII/Review prerequisites are met.
- [ ] Add CI/CD gates (lint/typecheck/test/SAST/SCA/SBOM and benchmark regression).
