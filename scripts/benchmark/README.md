# Private OCR/PII Benchmark Runner

A local-only tool that measures how well the current audit/OCR/PII pipeline performs against a
private local document corpus, without ever committing that corpus, its metadata, or any
extracted PII to the repository.

## What it does

`private_benchmark.py` reads three kinds of **already-computed, local-only** data:

1. Local document metadata and audit/OCR/PII artifacts from `volumes/document-data/<id>/`
   (written by the running app — see the root [README](../../README.md#storage-layout)).
2. A private benchmark metadata file describing the expected OCR/text-layer behavior of each
   sample document (page counts, expected pipeline routing, text-quality buckets).
3. A private candidate PII ground-truth file (entity type, page, and offset per candidate
   entity — **no unmasked values**).

It matches local documents to benchmark/ground-truth entries by filename, computes OCR/text
routing metrics and PII precision/recall/F1 against the candidate ground truth, compares the
newest available immutable result for every configured PII profile side by side, and writes a
markdown + JSON report that contains **only counts, statuses, types, and offsets** — never
extracted text, never a masked or unmasked PII value.

It **never** triggers audit/OCR/PII processing, calls the API, or modifies/deletes a document.
Missing artifacts — including profile-specific PII results — are reported as `missing`, not
generated. Run the desired profiles through the product before benchmarking them.

## Where private inputs and outputs live

```text
volumes/benchmark/
├── ocr_pii_benchmark_metadata.json           # private input, not committed
├── ocr_pii_benchmark_metadata.md              # private input, not committed
├── ocr_pii_benchmark_pii_groundtruth.json     # private input, not committed
├── ocr_pii_benchmark_pii_groundtruth.md       # private input, not committed
└── reports/
    └── <timestamp>/
        ├── benchmark_report.md
        ├── benchmark_report.json
        ├── benchmark_summary.csv
        └── benchmark_profiles.csv
```

Everything under `volumes/` (including `volumes/benchmark/`) is covered by the repo's
`/volumes/*` `.gitignore` rule and is never committed: the private benchmark inputs, the local
document corpus, and every generated report are local-only. This is deliberate — the corpus is
built from real customer-style documents and the ground truth is a candidate PII annotation of
their content, neither of which belongs in version control.

## Running it

```bash
make benchmark-private          # markdown + JSON + CSV summary
make benchmark-private-json     # JSON report only
```

Or directly:

```bash
python scripts/benchmark/private_benchmark.py \
  --uploads-dir volumes/uploads \
  --document-data-dir volumes/document-data \
  --metadata volumes/benchmark/ocr_pii_benchmark_metadata.json \
  --groundtruth volumes/benchmark/ocr_pii_benchmark_pii_groundtruth.json \
  --output-dir volumes/benchmark/reports
```

Useful flags:

| Flag | Effect |
| --- | --- |
| `--fail-on-missing-input` | Exit non-zero if the metadata or ground-truth file is missing. |
| `--json-only` / `--markdown-only` | Write only one report format (mutually exclusive). |
| `--no-pii` | Skip PII benchmark metrics. |
| `--no-ocr` | Skip OCR/text quality metrics. |

The runner has **no third-party dependencies** (standard library only), so it runs in a plain
`python:3.12-slim` container — see the `BENCHMARK_RUN` variable in the root `Makefile`.

There is currently no `--refresh-missing` flag: if artifacts are missing, the runner reports
`missing` and stops there. A future PR may add an opt-in flag to trigger the missing
station(s) via the API before reporting — deliberately not implemented here.

## Document matching

Local `document.json` filenames rarely match the benchmark filenames exactly, because uploading
the same file twice (or the source export process) appends a `(1)`/`(2)` copy suffix. Matching
tries, in order, and never guesses on ambiguity:

1. exact filename
2. normalized filename (Unicode NFC + whitespace trim only)
3. filename with a trailing `(1)`/`(2)` suffix stripped
4. file size as a plausibility check, only to disambiguate an otherwise-tied step 2/3 result

Anything left over is reported as `unmatched_local_documents`, `unmatched_benchmark_entries`,
`unsupported_file_type_entries` (currently just `.txt` — not a supported upload type), or
`ambiguous_matches` (with every candidate listed, so a human can resolve it).

## PII matching and "candidate ground truth"

The ground-truth file is explicitly a **candidate** benchmark: entity anchors produced by
deterministic heuristics over extracted page text, not a manually validated legal/PII gold
standard. Treat precision/recall/F1 numbers here as a **regression signal**, not an absolute
accuracy claim — some "false positives" may be entities the heuristic ground truth simply missed,
and some "false negatives" may be entity types the ground truth captured that a human reviewer
would not consider PII.

Matching rules:

- Entity types are mapped to a canonical name (`pii_matching.CANONICAL_TYPE_MAP`), e.g.
  `EMAIL` / `EMAIL_ADDRESS` → `EMAIL_ADDRESS`, `PERSON_NAME` → `PERSON`. Mapping is intentionally
  conservative — `BIRTH_DATE` is kept distinct from `DATE_TIME` rather than merged, because the
  pipeline has no dedicated birth-date recognizer and merging would inflate recall without the
  pipeline actually distinguishing the two.
- Entities are grouped into `structured_types`, `ner_types`, `domain_sensitive_types`, and
  `other_types` (`pii_matching.TYPE_GROUPS`) for aggregate reporting.
- A ground-truth type is `unsupported_by_current_pipeline` for a document when it is not in that
  document's actual `configured_entity_types` (read from its own `pii_result` artifact, not
  hardcoded) — today that is every `domain_sensitive_types`/`other_types` entry plus
  `BIRTH_DATE`, since the pipeline has no recognizer for any of them.
- **`page_aware` matching** (used whenever the document's text has page structure, i.e. every PDF
  in this benchmark): a detected entity matches a ground-truth entity if they share a canonical
  type, the same page, and their page-local offsets overlap by at least 50% of the shorter span,
  or their start offsets are within 10 characters of each other.
- **`document_level` matching** (fallback for text without page structure, e.g. DOCX): entities
  are matched by canonical-type counts only, since there is no reliable offset to compare.

No `masked_value`, `source`, `value_length`, or raw `text` field from either the ground truth or
the detected `pii_result` artifacts is ever loaded past the point where a count is taken — see
`artifact_loader.py`'s and `document_matching.py`'s narrow dataclasses.

## Building gold ground truth (from a proposal)

The shipped ground truth is a *candidate* signal; a manually validated **gold** standard is needed
to quantify precision/boundary gains (e.g. the structural-context stage, ADR-0043). To seed one:

```
python scripts/benchmark/build_groundtruth_proposal.py \
    --document-data-dir volumes/document-store \
    --out volumes/benchmark/gt-proposal.local.json \
    --filenames "TEST_01_....pdf,TEST_02_....pdf"
```

`build_groundtruth_proposal.py` emits the current detections as a *proposal* in the exact ground-
truth schema (`load_groundtruth` reads it directly), each entity flagged `review_status: "proposed"`.
A human then confirms / rejects / corrects offsets / adds missed entities and freezes the result as
the gold GT. The exporter is **offset-only and never reads or writes document text** — it reuses the
text-free loader, so a reviewer judges each anchor in the Review UI, which renders the document. The
proposal output belongs under the git-ignored `volumes/` tree, never the repo.

### Harvesting gold GT from Review-UI decisions

Rather than hand-editing the proposal, the preferred path is to **review the documents in the app**
(binding decision `keep` / `false_positive` / `pseudonymize` per entity, plus manual additions for
missed ones) and then harvest those decisions:

```
python scripts/benchmark/harvest_groundtruth.py \
    --document-data-dir volumes/document-store \
    --out volumes/benchmark/gold-gt.local.json
```

`harvest_groundtruth.py` reads the latest immutable `pii_review_result` snapshot per document (saved
after every decision) and emits gold GT: confirmed detections (`accepted`/`kept`) plus accepted
manual additions, **minus `rejected` false positives**. It is offset-only and reads no document text
— the snapshot is text-free, and the referenced text artifact is read only for per-page char counts,
used to map the snapshot's global raw offsets onto page-local benchmark coordinates. Documents with
no review snapshot are listed under `skipped_without_review` (review them first). A detection *kept*
at its detected boundary bakes that boundary into the GT; for boundary-exact GT, reject an
over-capture and re-add the correct span rather than merely keeping it.

The full loop: review in the app → `harvest_groundtruth.py` → point `--groundtruth` at the harvested
file → `make benchmark-private` reports per-type P/R/F1 **and** boundary accuracy (IoU/exact/
near-exact) against real gold GT, so a structural-context A/B (flag off vs on) can finally show FP↓
with no true-positive loss.

### Two review channels (don't confuse them)

The Review UI records reviewer input in **two separate channels**, with different purposes:

| Channel | UI control | Purpose | On disk | Consumed by |
| --- | --- | --- | --- | --- |
| **Binding decision** | *Bindende Entscheidung* (`keep`/`false_positive`/`pseudonymize`) + *Manuell hinzufügen* | the **truth** (what is PII, exactly where) → **gold GT** | `review/pii_review_decisions.jsonl` → `pii_review_result` snapshot | `harvest_groundtruth.py` |
| **Dev feedback** | *Review-Feedback (dev)* ("Problem auswählen" + comment) | the **error diagnosis** (which errors occur, how often) | `feedback/pii_feedback.jsonl` | `analyze_feedback.py` |

Both are text-free (offsets, types, codes). A reviewer often uses mostly one channel — that is fine,
they answer different questions. Use the binding decision to *build the gold standard*, and the dev
feedback to *see what to fix*.

### Analysing the dev feedback

```
python scripts/benchmark/analyze_feedback.py --document-data-dir volumes/document-store
```

`analyze_feedback.py` turns the dev-feedback channel into a text-free **error-taxonomy + consistency
report**: verdict counts, issue types sorted by frequency (`span_too_long_right`, `overlap_conflict`,
…), affected entity types, and a **recognizer issue-rate** ranking (the fix candidates — a recognizer
with a high issue share is a systematic detector problem). It is tolerant of reviewer mistakes: the
log is append-only, so it reads the **latest verdict per entity** (a revision wins) and reports how
many entities were revised, so a slip can be re-checked rather than trusted blindly. It never emits
the free-text comment — only whether one exists.

## Persistence model: private corpus vs. shared committed dataset

A recurring question: how do these annotations become a **persistent repository asset** everyone
benefits from, rather than sitting in local `volumes/`?

- **Real customer documents + their ground truth stay private** (`volumes/`, git-ignored). Even
  though the harvested GT is text-free (offsets/types), it is tied to real documents and their
  filenames, is useless to anyone who does not have those documents, and carries residual risk — so
  it is **local validation only**.
- **The shareable, committed dataset is built on synthetic documents** — realistic fixtures with
  *fake* PII (like the `TEST_0x` docs), whose full content and gold GT contain no real personal data
  and can safely live in the repo. Anyone who clones/pulls gets the corpus **and** its gold GT, runs
  the same benchmark, and is protected against regressions. That is the "everyone profits" asset.

This is **not** machine learning that auto-updates weights. It is a **human-in-the-loop quality
benchmark**: annotations → measured gaps + the error taxonomy above → deliberate code fixes
(recognizer tuning, cross-type precedence, the structural-context flag) → those *fixes* land in the
repo. The shared synthetic gold GT is the yardstick that makes the improvement measurable and keeps
it from regressing.

## Privacy guard

`privacy_guard.py` is a last-resort, defense-in-depth check run immediately before anything is
written to disk (`private_benchmark.main`):

- `assert_report_is_safe(report)` — recursively rejects the JSON report if any forbidden field
  name appears (`value`, `text`, `entity_text`, `raw_text`, `full_text`, `masked_value`,
  `page_text`, `ocr_text`, `source_text`, `snippet`, `excerpt`) or any string value looks like an
  email, IBAN, phone number, credit-card number, or IPv4 address.
- `assert_text_is_safe(markdown)` — the same PII-pattern scan applied to the rendered markdown
  text.

If either check fails, **no report file is written** and the process exits non-zero. The
violation message itself only ever contains JSON paths and pattern names, never the matched
value, so the guard cannot leak the thing it is blocking.

This is deliberately redundant with the loaders never reading those fields in the first place —
the guard exists to fail loudly if a future change accidentally reintroduces one.

## Module layout

```text
scripts/benchmark/
├── private_benchmark.py   # CLI entry point and orchestration
├── artifact_loader.py     # reads document.json + latest audit/text/pii artifacts (narrow, no raw text)
├── document_matching.py   # filename matching + benchmark/ground-truth JSON loading
├── ocr_metrics.py         # per-document/aggregate OCR/text-layer quality metrics
├── pii_matching.py        # entity type mapping, overlap matching, TP/FP/FN, precision/recall/F1
├── privacy_guard.py       # forbidden-field + PII-pattern report safety check
├── report_builder.py      # assembles the shared report dict; renders markdown from it
└── tests/                 # synthetic-data-only pytest suite (`make benchmark-test`)
```

Every module is standard-library only; sibling modules import each other as flat modules (not a
Python package), matching how `private_benchmark.py` is actually invoked
(`python scripts/benchmark/private_benchmark.py`, not `python -m`).
