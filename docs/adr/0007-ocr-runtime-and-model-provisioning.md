# ADR-0007: OCR runtime provisioning, model choice, and build profiles

## Status

Accepted — 2026-07-01. Build-profile parts superseded by ADR-0023 Phase 3.6; model
provisioning, model choice, local-only runtime downloads, and OCR adapter hardening remain current.

## Context

The OCR/Text station ([ADR-0004](0004-ocr-workstation.md)) routes scanned PDF pages and images to
PaddleOCR behind an adapter, but the runtime was never made usable end to end:

- The optional OCR image installed `paddleocr`/`paddlepaddle` yet the slim runtime lacked the
  native libraries they need (`libGL`, glib, `libgomp`), so importing PaddleOCR failed.
- PaddlePaddle 3.x enables MKL-DNN (oneDNN) for CPU by default, which crashes on the PP-OCRv5
  models with `ConvertPirAttribute2RuntimeAttribute not support`.
- No models were provisioned and PaddleOCR 3.x rejects a non-default local model unless its
  **name** is passed alongside the directory, so a German-capable recognizer could not be loaded.
- `make up` built the heavy extras whenever `.env` enabled them, blurring dev/CI vs OCR/PII runs.

## Decision

- **Model provisioning:** `scripts/fetch-ocr-models.sh` (via `make ocr-models`) idempotently
  downloads models from the official Hugging Face `PaddlePaddle/*` repositories into
  `./volumes/ocr-models/{text_detection,text_recognition}`. No runtime downloads; the backend
  still returns `503` when models are missing. Models are never committed (`/volumes/*`).
- **Model choice:** default to the CPU-friendly **mobile** PP-OCRv5 pair — `PP-OCRv5_mobile_det`
  and `latin_PP-OCRv5_mobile_rec` (~13 MB). The Latin recognizer covers German/Latin-script text
  including umlauts and ß, which the default CN/EN recognizer does not. The `*_server_*` variants
  are a documented future option, not the default.
- **Adapter/config hardening:** pass the model **names** to PaddleOCR (configurable via
  `OCR_DETECTION_MODEL_NAME`/`OCR_RECOGNITION_MODEL_NAME`) and set `enable_mkldnn=False` for the
  CPU path. Install `libgl1`, `libglib2.0-0`, `libgomp1` in the runtime image only for OCR builds.
- **Compose/env:** mount `./volumes/ocr-models:/models/ocr:ro`, default `OCR_MODEL_DIR=/models/ocr`
  (harmless in slim mode), and make the backend memory limit configurable so OCR/PII get headroom.
- **Historical profiles:** this originally introduced `up`/`up-pii`/`up-ocr`/`up-full` build
  profiles. ADR-0023 Phase 3.6 later removed those profiles: the default image now includes the
  required OCR and PII runtimes, while `ocr-smoke`/`pii-smoke` still exercise the real runtimes
  outside normal unit tests.
- **Proxy timeout:** raise nginx `/api/` `proxy_read_timeout` to 600 s, since synchronous CPU OCR
  of multi-page scans legitimately runs for minutes.

## Consequences

- The OCR runtime works end to end on `linux/amd64`: a 2-page scan was recognized in ~196 s at a
  peak of ~0.7 GB RAM. Apple Silicon/ARM support depends on PaddlePaddle wheels and is unverified.
- OCR model initialization remains lazy and quality gates stay model-free. The runtime dependencies
  are now part of the default Docker image; missing model files still fail cleanly with `503`.
- Refines [ADR-0004](0004-ocr-workstation.md); no change to anonymization/redaction scope.
