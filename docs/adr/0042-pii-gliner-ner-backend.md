# ADR-0042: Local GLiNER NER backend for PERSON/ORGANIZATION

- Status: Accepted
- Date: 2026-07-13
- Related: [ADR-0012](0012-insurance-at-de-pii-recognizers.md) (recognizer pack),
  [ADR-0013](0013-pii-candidate-validation.md) (candidate validation),
  [tool-strategy.md](../engine/tool-strategy.md), [pii-detection-quality-plan.md](../engine/pii-detection-quality-plan.md)

## Context

The PII detection & display foundation gate ([quality-gates.md](../../.ai/quality-gates.md)) requires
per-type detection quality on the private corpus before further ladder/redaction work. A measured
baseline exposed that the small spaCy CNN NER (`de_core_news_sm`) is the dominant precision drain on
dense German insurance forms: it labels medications, field labels, and addresses as PERSON/ORG
(PERSON precision 0.33 with 14 FP, ORGANIZATION recall 0.50 on the 4-doc TEST slice). Model **size**
is not the lever — an isolated spike showed `de_core_news_lg` is only marginally cleaner; the model
**class** (generic CNN NER) is the limitation.

A second spike compared GLiNER (`urchade/gliner_multi-v2.1`, zero-shot typed NER) on the same texts:
it isolated the real people and organizations almost perfectly (~13 real / ~2 spurious PERSON vs
~12 real / ~34 spurious for `sm`), with the titles attached and essentially no junk. GLiNER is the
tool-first NER upgrade that raises both PERSON precision and ORGANIZATION recall at once, and can
later cover currently-unsupported types (GIVEN_NAME/FAMILY_NAME, BIRTH_PLACE) via zero-shot labels.

## Decision

Add GLiNER as a **local, offline** NER backend for PERSON and ORGANIZATION, selected by
`PII_NER_BACKEND=gliner` (default `spacy`, so the change is opt-in and reversible):

- **Offline model, like OCR.** The model is provisioned into `GLINER_MODEL_DIR` ahead of time
  (`make ner-models` → `scripts/fetch-ner-models.sh` → `volumes/ner-models/<model>`), mounted
  read-only, and loaded with `local_files_only=True`. The backend never downloads at runtime; it
  raises `503` if the model is missing. Inference is fully local — no document text ever leaves the
  machine.
- **The backbone is provisioned too (offline correction).** `gliner_multi-v2.1` ships only the span
  head and references its transformer backbone (`microsoft/mdeberta-v3-base`) by HuggingFace id in
  `gliner_config.json`. Provisioning only the head left GLiNER fetching the backbone from the
  internet on first load — invisible while the container had egress, but a hard `503` once the
  backend network became `internal: true` (no egress) and a container restart dropped the transient
  HF cache. `fetch-ner-models.sh` now provisions **both** and rewrites the head's `model_name` to the
  container-local backbone path, and the runtime is pinned offline
  (`HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` default to `1`; `app.services.offline_ml_runtime` also
  switches Presidio's tldextract email-domain check to its bundled snapshot) so no model or
  suffix-list lookup is ever attempted at runtime. This makes the "fully local" guarantee provable,
  not incidental, and restart-safe.
- **Additive adapter.** `GlinerNerDetector` (`pii_ner_gliner.py`) owns only PERSON/ORGANIZATION.
  `PresidioAnalyzerAdapter` routes those two types to it and keeps everything else (pattern/checksum
  recognizers and DATE_TIME via spaCy) on the Presidio path, merging both candidate sets **before**
  candidate validation (ADR-0013) and overlap resolution (ADR-0028) run unchanged.
- **CPU-only torch.** `torch` is pinned to the CPU wheel index (`[tool.uv.sources]` in
  `backend/pyproject.toml`) so the image avoids the ~2 GB CUDA/nvidia tree; GLiNER runs on CPU.
- **No detection semantics change for other types.** Raw technical text remains the active detection
  input; the `pii_result` schema, profiles, review flow, and benchmark payloads are unchanged. Only
  the source of PERSON/ORGANIZATION candidates changes, plus additive `tool_versions` entries.

## Consequences

- **Positive:** large PERSON/ORGANIZATION quality gain (measured against the benchmark); the change
  is config-gated and reversible; GLiNER's zero-shot flexibility opens a path to the unsupported
  semantic types. Candidate validation still guards precision, and can be relaxed for the now-cleaner
  NER stream in a follow-up if it over-prunes.
- **Negative / cost:** a heavy dependency (torch + transformers, ~hundreds of MB even CPU-only) and
  the model files (offline, git-ignored under `volumes/`): the GLiNER head (~1 GB) **plus** the
  mdeberta-v3-base backbone (~1.3 GB). The backbone peaks ~3 GiB while loading, so `make dev` gives
  the API 4g (base `make up` stays at 1g with spaCy); slower cold start and per-document latency than
  the CNN NER. For amd64/production builds the CPU torch pinning must be kept (or a CPU/ONNX runtime
  chosen) to avoid CUDA bloat.
- **Deferred:** GIVEN_NAME/FAMILY_NAME/BIRTH_PLACE via GLiNER zero-shot; LOCATION stays out of the
  named profiles (ADR removed it); DATE_TIME stays on spaCy; a possible ONNX-runtime path to drop
  torch entirely.
