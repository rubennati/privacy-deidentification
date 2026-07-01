# Target Architecture

Where the engine is heading structurally. This is a target picture; nothing here is implemented by
the PR that introduces it. It complements the existing stack decision
([ADR-0001](../adr/0001-stack-and-architecture.md)) and storage separation
([ADR-0008](../adr/0008-separate-upload-and-document-data-storage.md)).

## Station pipeline (target)

```text
Upload ─▶ Audit ─▶ OCR/Text ─▶ [Layout] ─▶ [Structure] ─▶ PII ─▶ [Validation] ─▶ Review ─▶ [Redaction]
  │        │          │            │            │           │          │            │            │
  │        │          │            │            │           │          │            │            └ later phase
  ▼        ▼          ▼            ▼            ▼           ▼          ▼            ▼
document  audit_   best_text_   layout_    structured_  pii_    pii_valid.   review_   (de-identified
.json     result   result       text_res.  document_r.  result  result       result    output)
                   (canonical)  (readable) (tables/kv)
```

`[bracketed]` stations are planned. Each station:

- reads its input artifact, appends an **immutable** output artifact referencing that input,
- runs **synchronously** for now (no queue), behind **adapters** for every external tool,
- stays **local** — no bytes/text/PII leave the machine,
- never mutates upstream artifacts; changed inputs mark downstream artifacts **stale**.

Current runtime shape (unchanged): a React SPA behind nginx is the only public entry point and
proxies `/api/*` to a FastAPI backend that is not published to the host. Optional OCR/PII runtimes
are heavy build profiles (slim / pii / ocr / full).

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

- **AI must never silently overwrite the canonical text.** Canonical text changes only via an
  explicit reviewer/rule decision.
- **AI results must be labelled `assistive` / low-confidence** and stored distinctly from
  deterministic detections and human decisions.
- **AI must run locally.** No document data may reach an external service, cached or otherwise.
- **AI must be auditable.** Every AI-influenced outcome records that it was AI-influenced, with a
  reason, and is overridable.
- **AI is additive, not authoritative.** It proposes; rules or humans dispose.

These rules apply equally to OCR L9, PII L9, and Review L9. The first concrete step is an **isolated
spike** (Engine-8 in [`roadmap.md`](roadmap.md)), not a pipeline integration.

## Database considerations

Not implemented, and **not** part of the introducing PR. No migration, no SQLAlchemy/Alembic, no
schema change here. This section only frames the decision.

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

### What should later move to (or be indexed in) a DB

- **Index / lookup:** document list, artifact lineage, latest-artifact resolution, routing status.
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
