# Target Architecture

> **Level scale (0–19).** Per-engine capability levels now use the **0–19 maturity scale**
> ([engine README](README.md#maturity-scale)). Some `OCR Lx` / `PII Lx` / `Review Lx` citations
> below still use the legacy **0–10** numbering — translate with the *Legacy scale mapping* table at
> the bottom of the relevant engine document. Full renumbering here is a tracked follow-up.

Where the engine is heading structurally. This is a target picture; nothing here is implemented by
the PR that introduces it. It complements the existing stack decision
([ADR-0001](../adr/0001-stack-and-architecture.md)) and storage separation
([ADR-0008](../adr/0008-separate-upload-and-document-data-storage.md)).

## Station pipeline (target)

```text
Upload ─▶ Audit ─▶ OCR/Text ─▶ [Layout] ─▶ [Structure] ─▶ PII (detect + validate) ─▶ Review ─▶ [Redaction]
  │        │          │            │            │                   │                    │            │
  │        │          │            │            │                   │                    │            └ later phase
  ▼        ▼          ▼            ▼            ▼                   ▼                    ▼
document  audit_   best_text_   layout_    structured_           pii_               review_   (de-identified
.json     result   result       text_res.  document_r.           result             result    output)
                   (canonical)  (readable) (tables/kv)   (entities + validation
                                                            summary, additive)
```

`[bracketed]` stations are planned. Engine-5 (candidate validation) shipped as an **additive
post-processing step inside the PII station**, not the separate `pii_validation_result` artifact
this diagram originally sketched: it filters/downgrades candidates before `pii_result` is written,
and records a privacy-safe validation summary plus per-entity `validation_status`/
`validation_reasons`/`original_score` on the same artifact. This avoided a second artifact type,
new lineage edges, and new API surface for a subtractive filter that has no independent existence
without its `pii_result` input — see
[ADR-0013](../adr/0013-pii-candidate-validation.md). Each station:

- reads its input artifact, appends an **immutable** output artifact referencing that input,
- runs **synchronously** for now (no queue), behind **adapters** for every external tool,
- stays **local** — no bytes/text/PII leave the machine,
- never mutates upstream artifacts; changed inputs mark downstream artifacts **stale**.

Current runtime shape (additive Phase 3.6 state): a React SPA behind nginx is the only public entry
point and proxies `/api/*` to a private FastAPI `api` service. The default Compose stack starts
`frontend`, `api`, and `ocr-worker`; API and OCR worker share the same runtime image and the same
file storage/job DB mounts. The staged move to an isolated worker boundary — so an OCR/PII OOM/crash
can no longer take the API down — is defined in
[ADR-0023](../adr/0023-runtime-worker-architecture.md). **Phases 1–3.6 are implemented:** OCR/PII
run through the job seam, every run writes durable metadata-only job state to SQLite, and OCR is
isolated by default via `OCR_EXECUTION_MODE=worker` — the API enqueues OCR jobs (`202`) that the
worker claims and runs out-of-process, while the frontend polls status and then reads the finished
artifact. `OCR_EXECUTION_MODE=sync` remains a development/test fallback (`201` artifact body). PII
still runs synchronously in the API; the PII worker split, concurrency/timeout/retry controls, and
any queue broker remain later phases.

## OCR/Text as an independent module (output contract)

The pipeline is no longer "synchronous OCR feeding PII." The intended shape is:

```text
external OCR/PDF tools ─▶ OCR adapter / normalization layer ─▶ stable OCR/Text artifact
  ─▶ OCR Output Contract v1 / Document Text Package ─▶ consumers
     (PII, Review UI, pseudonymization, document analysis, summarization, export, future local AI)
```

OCR/Text is becoming an **independent, reusable module with a stable, versioned output contract**
([ADR-0027](../adr/0027-ocr-output-contract-v1-strategy.md)). PII is a **consumer of that
contract**, not of OCR internals: it must not depend directly on PaddleOCR, PDF parsing,
reading-order heuristics, or worker internals, and external OCR/PDF library changes must be
normalized **before** crossing the contract boundary. The contract packages raw (authoritative),
canonical, layout, structured, and evidence layers under a `contract_version` and a
`contract_status`, so any consumer picks the right view and knows its trust level. This is proposed
strategy — a cross-cutting stabilization milestone, not a numbered engine level — and changes no
behavior yet.

## Runtime job contract

Runtime work is exposed as a **stable job contract**, separate from the OCR Output Contract above:
the API enqueues jobs, the worker performs them, and the job-status API reports progress. The
frontend **consumes job status** (`POST …/ocr` → `202` job → poll `GET /api/jobs/{job_id}` →
read the finished immutable artifact) and must **not infer worker internals**. Today the frontend
polls; future notification transports (SSE, WebSocket, an event bus) may be added later but must
**not change the OCR Output Contract**. Redis/RQ/Celery is not required yet; SQLite remains the
current durable job state for the single-node local/runtime model (ADR-0023). A future notification
system changes *how* progress is delivered, never *what* text OCR produces.

## Design invariants the engine must keep

1. **Canonical vs readable text stay separate.** PII/review always run on `best_text_result`;
   layout/AI never rewrite it (see [`engine-artifacts.md`](engine-artifacts.md#the-two-text-artifacts--why-they-are-separate)).
2. **Detection-only until a redaction phase is explicitly designed.** No station alters the source.
3. **Fail loud, never silently degrade.** A broken text layer with no OCR runtime returns `503`; it
   is never used as if it were good.
4. **Everything is auditable and lineage-linked.** Any future AI or rule effect must be recorded,
   labelled, and overridable.

## Optional Local AI / Vision / Document Understanding

A deliberately separate chapter, because these terms get conflated and the guardrails matter.

### Terms, kept distinct

| Term | What it is | Not the same as |
| --- | --- | --- |
| **OCR** | pixels → characters | understanding |
| **Layout analysis** | geometry of blocks/lines/reading order | knowing what a block *means* |
| **Document structure understanding** | sections, tables, hierarchy | field semantics |
| **Schema / key-value extraction** | "Invoice no. = X", "Policy no. = Y" | generic NER |
| **Vision-language model (VLM)** | a model reading page images + text | deterministic OCR |
| **Local AI plausibility check** | model judging a candidate in context | a detector that *adds* entities |

### Immediately: do not implement

- **No local AI in the introducing PR.** No VLM integration. No large models. This phase is docs
  only, and near-term engine work uses deterministic tools + recognizers + rules.

### Later: where AI *may* help

- Visually check hard/low-quality scan pages (OCR L9).
- Better handle handwriting / marginalia.
- Plausibilise table/form structure (OCR L6–L7 support).
- Plausibilise PII candidates in context (PII L9).
- Recognise document type / section.
- Extract key-value pairs.

### Hard rules for any AI, at every level

- **AI must never silently overwrite technical raw or canonical reading text.** Any promoted text
  change requires an explicit reviewer/rule decision and preserved source lineage.
- **AI results must be labelled `assistive` / low-confidence** and stored distinctly from
  deterministic detections and human decisions.
- **AI must run locally.** No document data may reach an external service, cached or otherwise.
- **AI must be auditable.** Every AI-influenced outcome records that it was AI-influenced, with a
  reason, and is overridable.
- **AI is additive, not authoritative.** It proposes; rules or humans dispose.

These rules apply equally to OCR L9, PII L9, and Review L9. The first concrete step is an **isolated
spike** (Engine-8 in [`roadmap.md`](roadmap.md)), not a pipeline integration.

## Database considerations

Partially implemented for runtime job metadata only. ADR-0023 Phase 2 adds a small stdlib-SQLite
job store (`DATA_JOB_STATE_DIR/jobs.sqlite3` by default — a dedicated job-state root separate from
per-document artifacts, overrideable with `JOB_STORE_DB_PATH`) plus a safe status API. It stores only ids, lifecycle timestamps/status, sanitized errors, and produced
artifact references. Artifact payloads, raw OCR/reading/layout text, structured-content contents,
PII values, and uploaded bytes remain file-based and never enter SQLite. There is still no ORM,
Alembic, or external queue/broker; Phase 3's OCR worker uses the same SQLite file as a local
DB-backed polling queue.

### When does a database become worthwhile?

When the product needs **query, history, and cross-document state** that the flat file layout makes
awkward — concretely, once **review decisions and rules** (Review L2+) must be listed, searched,
versioned, and reapplied across runs. Detection alone (audit/OCR/PII artifacts) does *not* need a
DB; the file layout serves it well.

### What stays in the filesystem

- **Original files** — always on disk (`volumes/uploads`), never in a DB.
- **Large raw artifacts** — `best_text_result`, `layout_text_result`,
  `structured_document_result`, `ocr_result` — stay as files; a DB would only ever index *metadata*
  about them, never their raw text/PII.
- **Immutable per-document detection artifacts** — fine as files for the current scope.

### What belongs in a DB over time

- **Index / lookup:** document list, artifact lineage, latest-artifact resolution, routing status.
- **Runtime jobs:** OCR/PII job status and produced-artifact references — implemented in ADR-0023
  Phase 2 as metadata only, and reused in Phase 3 as the OCR worker's durable claim/status
  mechanism (an atomic `UPDATE … RETURNING` claim under WAL, no Redis/broker).
- **Run history:** benchmark runs and their aggregate metrics over time (trend, regression gate).
- **Review state:** confirm/reject/add/comment decisions and their lineage (Review L2+).
- **Rules:** suppression/allowlist rules with scope + version (Review L5, PII L8).

### SQLite-first, PostgreSQL later

- **SQLite-first** for the local single-user MVP: zero-ops, file-based, fits the Docker-first,
  local-only model, and can live alongside `volumes/`.
- **PostgreSQL later**, only when multi-user, server deployment, or real concurrency arrives.

### Which engine levels actually need a DB

| Need | Level | DB really required? |
| --- | --- | --- |
| Detection (audit/OCR/PII) | OCR L1–L8, PII L1–L6 | No — files suffice |
| Persisted review decisions | Review L2–L4 | Recommended (files possible at first) |
| Rules / reusable decisions | Review L5–L6, PII L8 | Yes in practice |
| Run history / trend / CI gate | benchmark maturity L3 | Helpful |
| Policy tracking / audit workflow | Review L8–L10 | Yes |

### Explicitly out of scope (introducing PR)

No DB build, no migration, no ORM, no schema. The **DB architecture spike** is Engine-7 in
[`roadmap.md`](roadmap.md), scheduled around when Review persistence (Engine-6) needs it.
