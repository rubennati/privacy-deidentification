# Engine Settings — Classification & Level Mapping

This document classifies every runtime setting that touches the OCR/Text and PII engines, so it is
clear which settings are **operational runtime config**, which are **part of the engine's maturity**,
which must be **recorded in the artifact** for reproducibility, and which may be **dev-selectable**
vs **production-only from `.env`**.

Settings are read from environment variables via [`backend/app/config.py`](../../backend/app/config.py)
(12-factor); [`.env.example`](../../.env.example) is the annotated source of truth. This doc does not
change any behaviour — it is planning/reference material for the 0–19 ladders.

## Classification axes

Each setting is rated on five axes:

- **Class** — `runtime` (operational/provisioning), `maturity` (a fachlich engine-reife capability),
  or `both`.
- **In artifact?** — must the effective value be recorded in the result artifact to make a result
  reproducible/traceable?
- **Dev-selectable?** — may the dev UI override it per run (only under `ENABLE_DEV_ENGINE_SETTINGS`)?
- **Prod source** — where the value must come from in production (always server-side `.env`).
- **Affects** — P/R (precision/recall), OCR-Q (OCR quality), Repro (reproducibility).

**Golden rule:** in production, **all** of these come only from server-side `.env`/compose. The dev
gate never lets the browser write defaults; it only allows a **one-run** override of selected PII
settings and enables feedback capture. See PII
[L9](pii-engine-levels.md#level-9--reproducible-engine-settings--dev-engine-settings---done).

---

## PII settings

| Setting | Class | Level | In artifact? | Dev-selectable? | Affects |
| --- | --- | --- | --- | --- | --- |
| `PII_PROFILE` | maturity | [L2](pii-engine-levels.md#level-2--profile--config-system---done) | ✅ yes (`engine_settings.pii_profile`) | ✅ yes (one run) | P/R |
| `PII_ENTITY_TYPES` | maturity | [L2](pii-engine-levels.md#level-2--profile--config-system---done) | ✅ yes (as profile `custom`) | ⚠️ not exposed (advanced override) | P/R |
| `PII_LANGUAGE` | both (base) | [L3](pii-engine-levels.md#level-3--ner--model-integration---done) | ✅ recommended | ❌ no (model-coupled) | P/R, Repro |
| `PII_SPACY_MODEL` | both (runtime) | [L3](pii-engine-levels.md#level-3--ner--model-integration---done) | ✅ recommended | ❌ no | P/R, Repro |
| `PII_SCORE_THRESHOLD` | maturity | [L9](pii-engine-levels.md#level-9--reproducible-engine-settings--dev-engine-settings---done) | ✅ yes (`engine_settings`) | ⚠️ candidate (not yet) | P/R, Repro |
| `PII_CANDIDATE_VALIDATION_ENABLED` | maturity | [L6](pii-engine-levels.md#level-6--candidate-validation--false-positive-suppression---done) | ✅ yes (`engine_settings`) | ⚠️ candidate | P/R, Repro |
| `ENABLE_DEV_ENGINE_SETTINGS` | runtime (dev-ops) | [L9](pii-engine-levels.md#level-9--reproducible-engine-settings--dev-engine-settings---done) / Review [L4](review-feedback-levels.md#level-4--dev-engine-settings-surface---done-gated) | ❌ (it *is* the gate) | ❌ no | — |
| `engine_settings` (artifact block) | maturity | [L9](pii-engine-levels.md#level-9--reproducible-engine-settings--dev-engine-settings---done) | — (it *is* the record) | — | Repro |

Notes:

- **`PII_CANDIDATE_VALIDATION_ENABLED` is not merely a flag** — it toggles a **distinct
  post-detection pipeline stage** (candidate validation, PII L6). It belongs in the maturity model,
  not the runtime bucket, and its effective value is recorded in `engine_settings` so a result's
  precision posture is reproducible.
- **`PII_PROFILE`** drives the *breadth* of detection (which types are active) and therefore
  precision/recall directly; it is the primary dev-selectable knob.
- **`PII_SCORE_THRESHOLD`** shifts the precision/recall operating point. It is recorded in the
  artifact; making it dev-selectable is a reasonable future step but must stay a one-run override.
- **`PII_LANGUAGE` / `PII_SPACY_MODEL`** are base/runtime settings coupled to the installed model.
  They are not dev-selectable (changing them needs the right model present) but should be recorded so
  NER capability is reproducible. Today `de` / `de_core_news_sm`.
- **`PII_ENTITY_TYPES`** is a backwards-compatible allowlist override; when set it replaces
  `PII_PROFILE` and is recorded as profile `custom`. It is intentionally *not* surfaced in the dev UI
  (advanced/debug only).

### Which PII settings influence what

- **Precision/Recall:** `PII_PROFILE`, `PII_ENTITY_TYPES`, `PII_SCORE_THRESHOLD`,
  `PII_CANDIDATE_VALIDATION_ENABLED`, and (via NER capability) `PII_LANGUAGE`/`PII_SPACY_MODEL`.
- **Reproducibility:** everything recorded in `engine_settings` (profile, candidate validation, score
  threshold, source) plus the model/language pair. Two runs with identical inputs + recorded settings
  must yield identical entities.

---

## OCR settings

| Setting | Class | Level | In artifact? | Dev-selectable? | Affects |
| --- | --- | --- | --- | --- | --- |
| `OCR_MODEL_DIR` | runtime (provisioning) | [L3](ocr-engine-levels.md#level-3--basic-ocr-runtime---done) | ⚠️ path not meaningful to record | ❌ no | — |
| `OCR_DETECTION_MODEL_NAME` | both (repro) | [L3](ocr-engine-levels.md#level-3--basic-ocr-runtime---done) / [L16](ocr-engine-levels.md#level-16--reproducible-ocr-engine-settings-in-artifact---open) | ✅ should (L16, not yet) | ❌ no | OCR-Q, Repro |
| `OCR_RECOGNITION_MODEL_NAME` | both (repro) | [L3](ocr-engine-levels.md#level-3--basic-ocr-runtime---done) / [L16](ocr-engine-levels.md#level-16--reproducible-ocr-engine-settings-in-artifact---open) | ✅ should (L16, not yet) | ❌ no | OCR-Q, Repro |
| `INSTALL_OCR` (build/profile) | runtime | [L3](ocr-engine-levels.md#level-3--basic-ocr-runtime---done) | ❌ no | ❌ no | — |
| OCR runtime provisioning (`make ocr-models`, read-only mount, Poppler, tmpfs, MKL-DNN-off) | runtime | [L3](ocr-engine-levels.md#level-3--basic-ocr-runtime---done) | ❌ no | ❌ no | OCR-Q (stability) |
| Text-layer quality-gate thresholds (`text_quality.py`) | maturity | [L4](ocr-engine-levels.md#level-4--text-layer-quality-gate---done) | verdict recorded on `audit_result` | ❌ no (code-level, unit-tested) | OCR-Q (routing) |
| OCR fallback behaviour (`503`-not-garbage) | maturity | [L5](ocr-engine-levels.md#level-5--page-level-ocr-routing--fallback---done--current-baseline) | routing recorded | ❌ no | OCR-Q |
| `BACKEND_MEMORY_LIMIT` | runtime | — | ❌ no | ❌ no | OCR-Q (OOM avoidance) |

Notes:

- **`OCR_MODEL_DIR`, `INSTALL_OCR`, provisioning, `BACKEND_MEMORY_LIMIT`** are pure
  runtime/provisioning: they decide *whether and where* OCR runs, not *how good* the result is in a
  fachlich sense. They stay server-side and are not recorded as engine reproducibility state (a
  container path is not meaningful across machines).
- **`OCR_DETECTION_MODEL_NAME` / `OCR_RECOGNITION_MODEL_NAME`** determine which recognition capability
  ran (e.g. Latin recognizer for German umlauts/ß vs the default). They **affect OCR quality** and
  are a **reproducibility** concern — they *should* be recorded in the text/quality artifact at OCR
  L16 (not yet implemented; today only PII records `engine_settings`).
- **Text-layer quality gate** thresholds are deliberately **code-level** and unit-tested rather than
  env-tunable, so routing behaviour is stable and reviewable. The per-page verdict is recorded on
  `audit_result` (metrics only, never page text).
- **OCR fallback** (`needs_ocr` routing; `503` when a needed runtime is missing) is a maturity
  behaviour (OCR L5), not a tunable — it exists to never silently trust broken input.

### Which OCR settings influence what

- **OCR quality:** model pair (detection/recognition), the quality-gate thresholds, and runtime
  stability settings (MKL-DNN-off, memory limit, tmpfs render workspace).
- **Reproducibility:** the model names + pinned engine/model versions — targeted for OCR L16
  (`engine_settings` on the text/quality artifact), mirroring PII L9.

---

## Summary answers to the review questions

- **Pure runtime/default config:** `OCR_MODEL_DIR`, `INSTALL_OCR`, provisioning, `BACKEND_MEMORY_LIMIT`,
  `ENABLE_DEV_ENGINE_SETTINGS` (a dev-ops gate). These decide *whether/where* engines run.
- **Fachlich part of engine maturity:** `PII_PROFILE`, `PII_ENTITY_TYPES`, `PII_SCORE_THRESHOLD`,
  `PII_CANDIDATE_VALIDATION_ENABLED` (its own pipeline stage), the quality-gate thresholds, OCR
  fallback, and the OCR/NER model choices.
- **Must be stored in the artifact for traceability:** PII → `engine_settings` (profile, candidate
  validation, score threshold, source) **is** stored today; language/model pair recommended. OCR →
  detection/recognition model names + engine versions, targeted at OCR L16 (**not yet**).
- **Should be dev-selectable (one run, gated):** `PII_PROFILE` today; `PII_SCORE_THRESHOLD` and
  `PII_CANDIDATE_VALIDATION_ENABLED` are reasonable future one-run overrides.
- **Production only from server-side `.env`:** **all** of the above — the dev gate never writes
  defaults and only overrides selected PII settings for a single local run.
- **Influence precision/recall:** `PII_PROFILE`, `PII_ENTITY_TYPES`, `PII_SCORE_THRESHOLD`,
  `PII_CANDIDATE_VALIDATION_ENABLED`, NER model/language.
- **Influence OCR quality:** detection/recognition model pair, quality-gate thresholds, runtime
  stability settings.
- **Influence reproducibility:** everything recorded in `engine_settings` (PII, today) and the
  model/version pins (OCR, planned L16); determinism is verified by the benchmark
  ([Benchmark L7](benchmark-engine-levels.md#level-7--deterministic--reproducible-runs---done)).
