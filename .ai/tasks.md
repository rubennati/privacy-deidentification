# Tasks

Current open work. Delivered history is condensed in `state.md` (Milestone log) and `decisions.md`.

## Now / next

- [ ] **Release `dev` → `main`** — carry #100/#101/#102 (Windows installer hardening) so customers on
  `main` get the ExecutionPolicy fix + guided install. `dev` is ahead of `main`.
- [ ] **Redaction L0 → L1** — write the design/threat-model doc: define "removed / leak /
  pseudonymized", pick **Track A** (text-first typed placeholders + reversible mapping + export),
  specify the placeholder scheme, the (sensitive, offline) mapping artifact, and the
  consistency/grouping rule. **No redaction code yet.** Update `docs/engine/redaction-engine-levels.md`
  + a new ADR.
- [ ] **PII tuning toward 95 %** — ORG + DATE recall (the real, dangerous gaps). Do **not** tune PERSON
  down (its benchmark "FP" are verified real names).

## Evaluate / decide

- [ ] **Reference-list gazetteers** (WKO / Firmenbuch / GeoNames) as an additive, soft,
  human-in-the-loop signal for the long tail — roadmap building block; assess licensing / offline
  loading / maintenance. Additive only (never a deny list).
- [ ] **Remove the dormant anchor machinery** (Text Anchor Graph, `pii_anchor_binding.py`,
  `GET …/pii/entity-contract`) now that display is precise per-entity projection — decide scope; "cut
  anchor complexity".
- [ ] **Windows repo → private** — needs one real Windows `gh auth login --web` test; then the owner
  flips visibility + invites the collaborator (access control, owner action). Installer already
  auto-detects public/private.
- [ ] **PII worker split** — give PII its own worker like OCR as the pipeline grows (deferred).

## Later

- [ ] Keep Redaction gated on its documented OCR/PII/Review prerequisites for **Track B** (visual PDF
  redaction).
- [ ] CI/CD gates (lint / typecheck / test / SAST / SCA / SBOM + benchmark regression).

## Delivered foundation (condensed)

Upload / validation / separated storage / list / delete + immutable artifacts; Audit + OCR/Text L15;
detection-only PII L14; Review L10; Benchmark L10; engine maturity model (0–19) + entity taxonomy
(P0–P5). Full history in `state.md`.
