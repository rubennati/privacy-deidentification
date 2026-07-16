# Current State

> If this file conflicts with the current branch or commits, **trust git.** This is the current
> snapshot. The condensed milestone log is at the end; decisions and **rejected paths** are in
> `decisions.md`; deep design lives in `docs/adr/` and `docs/engine/`.

## Where we are (2026-07-15)

**Phase:** quality-first, **detection-only** PII on a customer-ready local app. No redaction or
pseudonymization exists yet.

**Runs fully local & offline** (`docker compose up -d` → <http://localhost:8080>; `api` + `ocr-worker`
sit on an `internal: true` network with **no internet egress**):

- Upload, document list/delete, structural **Audit**, worker-based **OCR/Text** (clean reading text),
  **detection-only PII**, and a **manual review** workflow — grouped per-entity decisions
  (pseudonymize / keep / false-positive) plus manual add of a missed entity, recorded in an immutable
  `review_result`.
- Durable SQLite job state, isolated OCR worker, runtime recovery (leases / bounded retries / fenced
  writes), fully offline GLiNER (backbone provisioned).

**Detection input = raw text only.** Highlights are projected **precisely per entity** onto a separate
reading text (see the anchor reversal below).

**Measured quality — first baseline (2026-07-15, `make benchmark-private`, synthetic corpus):**
recall **0.90** / precision **0.85** / f1 0.88; structured identifiers (IBAN, e-mail, phone, UID,
SVNR, tax-nr, …) near 100 %. Guiding principle: **recall ≫ precision** — a missed PII is dangerous,
an over-mark is one review click. Real gaps = **ORGANIZATION + DATE** recall. The PERSON "11 FP" were
verified to be **real names** → do **not** tune PERSON down.

## Current focus / next

1. **Release `dev` → `main`.** The Windows installer hardening (below) is in `dev`, not yet on `main`;
   customers install from `main`.
2. **Redaction L0 → L1** — the app's headline promise (**context-preserving pseudonymization +
   export**) does **not** exist yet. L1 = a **design / threat-model** doc, **Track A = text-first**
   (typed placeholders `[[Person-1]]` in a copy + reversible mapping; buildable on today's review
   decisions + precise projection). Track B (pixel-perfect visual PDF redaction) needs OCR/PII
   geometry (L15/L18) and stays **parked**. See `decisions.md`.
3. **PII tuning toward 95 %** — ORG/DATE recall; optional reference-list **gazetteers**
   (WKO/Firmenbuch/GeoNames) as a *soft, additive, human-in-the-loop* signal for the long tail (never
   a deny list).

## The two-text model + the anchor reversal (read before re-adding complexity)

Detection is on the faithful **raw** text; the **reading text** is a separate, deliberately **lossy**,
readability-optimised view (dedups repeated footers, drops table noise). A 2026-07-15 scan experiment
**confirmed** detection must stay on raw. The earlier **anchor-bound display** used a block-granular
anchor "envelope" as the reading-view range → **over-marking** (one ~390-char block range shared by 5
entities). **#95 retired the anchor envelope for display** and replaced it with **precise per-entity
reading offsets** (`reading_start/end_offset`, `projection_status`, offset-map + ordinal-disambiguated
text-match) — browser-verified, 100 % precise on prose, 0 over-wide.

**Not fully removed (open cleanup):** the Text Anchor Graph (`document_text_anchors.py`, still built in
`ocr.py`), `pii_anchor_binding.py`, and the `GET …/pii/entity-contract` endpoint still exist and are
partly wired. Removing the dormant anchor machinery ("cut anchor complexity") is a **pending decision**,
not done — do not describe the anchor model as fully retired.

## Windows local app (in `dev`; release to `main` pending — #100/#101/#102)

The `irm … | iex` installer now: (a) enables local script execution under the default `Restricted`
policy (`CurrentUser=RemoteSigned` + `Process=Bypass`); (b) **auto-detects public vs private repo** and
signs in via `gh auth login --web` for a private repo (no separate installer repo); (c) prints guided
**coloured** step output; plus a "fully remove an old version" doc. The repo is **still public**. Going
private needs one **real Windows `gh`-login test** + the owner's visibility/collaborator actions
(access control). See `docs/windows-local-app.md` and `decisions.md`.

## Branch policy

Feature/docs PRs target **`dev`**; **`main`** is the curated user-stable branch; Windows install/update
tooling always follows `main`. A human merges every PR.

## Product snapshot

- Docker Compose: React/Vite SPA behind nginx, a private FastAPI `api` (runs PII synchronously), and a
  private `ocr-worker` (isolated OCR, one job at a time). `api` + `worker` have no internet egress.
- Originals, metadata, and immutable derived artifacts use separate validated storage boundaries under
  a single `DATA_ROOT` (default `./volumes`).
- OCR/Text routes each page between a usable text layer and adapter-bound PaddleOCR; DOCX includes
  paragraphs/tables/headers/footers; artifacts carry additive layers (readable text, layout, structured
  content, geometry, quality evidence). **It does not redact, anonymize, or pseudonymize.**
- PII uses GLiNER (default NER, PERSON/ORG) + Presidio/spaCy pattern recognizers behind adapters, named
  profiles, AT/DE + domain recognizers, subtractive candidate validation, deterministic overlap
  resolution. **Raw text is the only active detection input.**
- The local private benchmark measures routing + PII quality from existing artifacts (synthetic
  committed data; private corpus stays under git-ignored `volumes/`).

## Engine maturity snapshot (0–19)

Levels per [ADR-0016](../docs/adr/0016-engine-maturity-levels-0-19.md); details in
[`docs/engine/`](../docs/engine/README.md).

- **OCR/Text: L15.** Immutable raw `text_result.text` + additive derived layers: canonical
  `reading_text` (L10.5, with L12 multi-column + L13 table/form reconstruction v2), `readable_text`
  (L8), `layout_text_result`/`layout_blocks` (L9), `text_geometry` (L10), `structured_content`
  (L11/L13), `quality_report` (L7), `quality_evidence` (L14 lineage coverage + L15 noise/token
  evidence), and construction-time cell lineage (ADR-0040). Display-only layers make no PII-input claim.
- **PII/Sensitive-Data: L14 (L10 partial).** Detection-only on raw text. Entity grouping (L11), intake
  adapter + deterministic overlap resolution (L12), review-decision overlay (default `pseudonymize`;
  opt out via `keep`/`false_positive`), direct decision lineage (L13), manual add of a missed entity
  (L14). GLiNER default NER (ADR-0042); structural-context FP suppression (ADR-0043, default-off);
  context-gated BIRTH recognizers (ADR-0044). Display = precise per-entity reading projection (#95).
- **Review/Human-Feedback: L2 production; L3–L5 dev-only; L6–L10 done.** Immutable `review_result`
  snapshot after every decision; superseded decisions surfaced as stale and never reapplied.
- **Benchmark/Regression: L10.** One read-only invocation reports every profile's newest PII artifact +
  OCR confidence/coverage; first measured baseline recorded 2026-07-15.
- **Redaction/De-Identification: L0 by design.** This is the app's headline promise and the biggest
  unbuilt piece — next is L1 (design/threat-model, Track A). See `decisions.md`.

## Dev feedback boundary

- With `ENABLE_DEV_ENGINE_SETTINGS=true`, per-entity feedback appends to
  `volumes/document-store/<id>/feedback/pii_feedback.jsonl`. New writes must match an entity in the
  referenced `pii_result` (type/offsets/recognizer). A gated analysis side-channel — not a learning
  system and not the binding review artifact. Excludes raw document/entity text (optional `text_hash` =
  SHA-256 only).

## Governance checkpoint

- Core OCR / NER / redaction / pseudonymization intelligence comes from established tools behind adapters.
- Adapter-bound Presidio recognizers, context rules, candidate validation, and small deterministic
  heuristics are permitted only when documented, tested, benchmarkable, reviewable, and auditable.
- Major architecture/dependency changes, large opaque rule systems, or ad-hoc intelligence require human
  approval before implementation.

## Milestone log (condensed)

Newest last. Deep detail in the linked ADRs; **rejected paths in `decisions.md`**. The binding OCR/PII
sequence lives in [`docs/engine/ocr-pii-implementation-plan.md`](../docs/engine/ocr-pii-implementation-plan.md)
([ADR-0018](../docs/adr/0018-ocr-pii-implementation-plan.md)).

**Checkpoint loop:** after every engine PR record which level changed, confirm OCR/Text stays ahead of
PII/Redaction, check for benchmark/feedback re-prioritisation and config/artifact drift, and update this
file; re-confirm the next three PRs every third PR.

- OCR L10.5 → L11 → L12 (multi-column) → L13 (table/form v2) → L14 (quality evidence) → L15
  (noise/token evidence) — ADR-0019/0024/0025/0026.
- Runtime architecture: Phase 2 (SQLite job state/status API) → Phase 3 (isolated OCR worker) → 3.5
  (persistence audit) → 3.6 (default worker stack) — ADR-0023.
- OCR Output Contract v1 / Document Text Package (ADR-0027) → PII L12 intake adapter + overlap
  resolution (ADR-0028).
- PII L11 entity grouping + review-decision overlay (ADR-0021).
- Anchor-bound PII entity model v1 (ADR-0029/0031) → anchor-first highlight conformance fix →
  text-anchor feasibility audit (docs) → geometry-backed reading projection v1.
- Runtime Job UX / in-app notifications v1 (ADR-0030).
- Reading-text row construction lineage v1 (ADR-0032) → v2 → construction-time canonical lineage v3 /
  cell identity (ADR-0040).
- PII binding quality suite (Phases 2–3) → Review L8 `review_result` (ADR-0034) → Review Result v1
  unified stable entries → PII validation transparency report.
- Benchmark L9 per-profile reporting (→ L10).
- PII L13 / Review L9 direct decision lineage → PII L14 / Review L10 manual add (ADR-0035) → unified
  Dev View entity review cards.
- Runtime recovery & compatibility integrity v1 (ADR-0041).
- Local GLiNER NER backend for PERSON/ORG (ADR-0042); GLiNER made genuinely offline (backbone
  provisioned, #85).
- PII structural-context validation, default-off (ADR-0043); context-gated BIRTH_DATE/PLACE recognizers
  (ADR-0044).
- Frontend data-layer rebuild to TanStack Query (#90); ADDRESS over-capture fix (#91); jump-nav
  dead-target fix (#92); Layout-Text view retired.
- Infra/build stabilization: dropped `COPY --chown` on the 2.6 GB venv (~16 min stall → ~4 min build,
  #94); coherent Makefile lifecycle (up/dev/update/rebuild/stop/down/prune).
- **Precise per-entity reading-view projection; anchor display envelope retired (#95)** — see the
  reversal section above.
- Customer-ready docs: README update path + architecture graphic + status/roadmap (#96/#98/#99 → main);
  TAX_ID recall 0.33→1.0 (#97).
- **First measured PII baseline (2026-07-15):** recall 0.90 / precision 0.85; ORG/DATE the real gaps;
  PERSON "FP" are real names.
- **Landing-page promise gap analysed:** the sold "kontextbewahrende Pseudonymisierung" is unbuilt
  (Redaction L0) → decided next milestone L0→L1, Track A. See `decisions.md`.
- Windows installer hardening: uninstall doc (#100), ExecutionPolicy fix (#101), public/private
  auto-detect + gh-auth + coloured output (#102) — released to `main` (#104) with the `.ai`
  workspace refresh (#103).
- **Mixed-page OCR supplement:** a text-layer PDF page carrying a significant embedded image (a
  pasted scan — Word → PDF exports) additionally gets a full-page OCR pass; the deduplicated
  remainder is appended to the page text so PII detection sees the image's content. Failures
  degrade to the working text layer with an honest per-page status (`ocr_supplement_status`),
  never a 503. Detection heuristic reads XObject dictionaries only (no image decode).

## Dev maintenance

- `make docker-df` is a read-only Docker disk-usage check. Prune/cleanup targets were removed (Phase
  3.6) to keep the runtime surface small and avoid broad Docker cleanup in project commands.

## Active constraints

- Docker-first; no host-local application toolchain is required.
- Keep changes focused and `.ai/` files concise.
- Do not read or commit private material under `volumes/`.
