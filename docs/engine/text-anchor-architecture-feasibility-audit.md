# Text Anchor Architecture — End-to-End Feasibility Audit

> **Scope.** An architecture and implementation conformance audit of the Text Anchor Identity
> approach ([ADR-0031](../adr/0031-text-identity-anchor-lineage-architecture.md)) as implemented on
> `dev` after PR #59 (anchor-first E2E conformance fix). It audits; it does not implement. All
> examples are synthetic. Audited surface: `document_text_package.py`, `document_text_anchors.py`,
> `reading_text_projection.py`, `pii_input.py`, `pii_overlap.py`, `pii_service.py`,
> `pii_anchor_binding.py`, `pii_entity_contract.py`, the `/text-package`, `/text-anchors`, and
> `/pii/entity-contract` endpoints, the frontend contract consumers
> (`piiEntityContract.ts`, `piiHighlights.ts`, `PiiTextViewer.tsx`, `ReviewTextViewer.tsx`,
> `DocumentDetailPage.tsx`), and their test suites.

## 1. Executive summary

The anchor architecture is **conceptually sound and correctly staged**, and the implemented v1 is
**honest about what it is** — but it is **not yet anchor-first**. It is best described as
**anchor-derived with contract-enforced consumption**:

- **Identity is minted from offsets, after the fact.** An `anchor_id` is a hash of
  `(document_id, source_name, start, end, kind)` — a raw offset in disguise. Anchors are created by
  re-tokenizing the finished raw string, not at text-construction time. Entity identity
  (`anchor_exact` → hash of ordered anchor ids + type) is therefore *transitively* offset-derived:
  stable across identical re-runs, invalidated by any raw-text change and by any tokenizer change.
- **The lineage the whole graph stands on is a post-hoc string alignment.** Canonical ranges attach
  exclusively through `reading_text_map`, and `build_reading_text_map` builds that map by matching
  **globally unique whitespace tokens** between the raw and reading strings after both exist. The
  reading-text builder *knows* the source row/geometry of every fragment it renders and discards
  that knowledge; lineage is then reconstructed by string equality. This is the single deepest gap
  between the ADR's intent and the implementation.
- **The consumption side genuinely enforces the architecture.** PII binds by offset overlap against
  the graph (never by string), missing/partial/ambiguous states are explicit and reason-coded,
  repeated values are never married, evidence-only fallback is visible, the frontend renders only
  contract-supplied view ranges, and a real end-to-end conformance test
  (`test_anchor_bound_pii_e2e_conformance.py`) locks the raw→canonical propagation promise.

**Verdict in one line:** keep the architecture, treat v1 as a legitimate transitional layer, and
make the next structural move **construction-time lineage** (the reading-text builder emitting its
own map) — not persistence, not pseudonymization, not more diagnostics.

## 2. Current implementation classification

Using the audit's five-way scale:

| Classification | Fits? | Evidence |
| --- | --- | --- |
| Anchor-first (anchors created at OCR/Text construction; views are projections) | **No** | Anchors are derived in `document_text_anchors.py` from the finished `DocumentTextPackageV1`; the OCR pipeline (`ocr_service._text_content`) builds `text` → `reading_text` → `reading_text_map` first, with no anchor concept at construction time. |
| **Anchor-derived** (anchors derived after the fact from package/lineage, consumed as identity) | **Yes — this is the current model** | Graph derived per request from the package; PII binds detections to it; the entity contract exposes anchor-derived identity; frontend consumes only that contract. |
| Anchor-assisted (anchors as optional enrichment) | Partly, at the display layer | The ADR-0029 projection fields (`projection_status`, `text_match` fallback) still coexist as a second, non-anchor display mechanism (see §8.3). |
| Offset-first with anchor metadata | Transitively true for *identity* | `anchor_id` = hash of offsets; `anchor_exact` entity ids inherit that coupling. |
| Mapping-after-the-fact | True for *lineage* | `build_reading_text_map` is a unique-token string alignment computed after both texts exist. |

So: **identity layer = anchor-derived; lineage layer = mapping-after-the-fact; consumption layer =
genuinely anchor-first.** The consumption discipline is the strongest part of the implementation;
the construction side is the weakest.

## 3. Conceptual model assessment (is the architecture sound?)

**Yes, with one refinement.** The core principle — *views are projections of stable information
units; offsets are view-specific; identity is shared* — is the correct substrate for every stage of
the Golden Path:

- **OCR/Text:** anchors generalize `reading_text_map` + `text_geometry`; ownership by OCR/Text (not
  PII) is right and is respected in code (PII only reads the graph).
- **PII:** binding detections to anchor sets solves duplicate/merge/provenance problems structurally
  (`_merge_observations` merges same-anchor-set observations) and makes cross-view display a
  property of identity, not of per-view string luck.
- **Review:** decisions over stable entities work; today they key on occurrence ids
  (`source_entity_ids`) which is the *safer* choice while anchor ids are still builder-coupled
  (see §10).
- **Pseudonymization:** rendering from accepted entities + view ranges is expressible with the
  current data (§11), so the model supports it; it is not implemented, correctly.
- **Reconstruction:** placeholder → group → entity → anchor → value is expressible; nothing today
  persists any link in that chain, so reconstruction is a pure future (§12).

**The refinement:** the ADR states anchors give identity "stable across re-runs". With offset-minted
ids that is only true when the raw bytes are identical *and the builder version is identical*. A
tokenizer change (exactly what PR #59 was) silently re-mints every anchor id for the same immutable
artifact. That is harmless while nothing durable references anchor ids — and today nothing does —
but it becomes a correctness bug the moment `review_result`, replacement plans, or a reconstruction
map key on them. The conceptual model should therefore say explicitly: **anchor ids are stable per
(text artifact bytes × graph builder version)**, and any persisted reference to an anchor id must
pin both.

## 4. Actual data flow — trace and owner matrix

The order the code actually executes (write path, then read path):

```text
WRITE PATH (per OCR run, ocr_service.py)
  Source document
    → OCR/Text extraction                → text (technical raw), pages[]        [immutable artifact]
    → build_reading_text(...)            → reading_text (uses geometry/blocks)  [same artifact]
    → build_reading_text_map(raw, read)  → unique-token string alignment        [same artifact]
    → quality_evidence                   → metrics only                          [same artifact]

WRITE PATH (per PII run, pii_service.py)
  text artifact
    → build_document_text_package()      → DocumentTextPackageV1                 [derived, not persisted]
    → PiiInputAdapter                    → PiiInputDocumentV1                    [transient]
    → analyzer (raw text only)           → candidates                            [transient]
    → validate_candidates                → validated entities                    [transient]
    → resolve_pii_overlaps               → resolved entities + provenance        [immutable pii_result]
    → project_pii_entities_to_reading_text → projection fields on entities       [same pii_result]

READ PATH (per entity-contract request, pii_entity_contract.py)
  latest pii_result + matching text artifact (id must equal input package id)
    → build_document_text_package()      → package                               [derived]
    → build_document_text_anchor_graph() → Text Anchor Graph v1                  [derived]
    → bind_pii_entities_to_anchors()     → AnchorBoundPiiEntityV1[] + summary    [derived]
    → review overlay (JSONL)             → review state per occurrence           [mutable overlay]
    → PiiEntityContractV1                → view ranges + reason codes            [derived]
    → frontend buildAnchorBoundPiiHighlights → per-view highlight model          [render only]
```

| Step | Owner | Input | Output | Persisted | Mutable | Can break identity | Test coverage | Gap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OCR extraction | OCR/Text | original | `text`, `pages` | yes (artifact) | no | yes — any re-run shifts all offsets → all anchor ids | OCR suites | none new |
| Reading text | OCR/Text | raw + geometry/blocks | `reading_text` | yes | no | indirectly — changes token uniqueness | reading-text suites | discards construction lineage |
| `reading_text_map` | OCR/Text | raw + reading strings | unique-token segments | yes | no | **yes — the load-bearing lineage is a string heuristic** | projection tests, e2e | no construction-time emission; repeated tokens unmappable by design |
| Text package | OCR/Text | text artifact | `DocumentTextPackageV1` | no (derived) | n/a | no (1:1 deterministic) | package tests | none |
| Anchor graph | OCR/Text (anchor layer) | package | `DocumentTextAnchorGraphV1` | no (derived) | n/a | **yes — builder change re-mints all ids** | `test_document_text_anchors.py` | not persisted; ids not builder-versioned |
| PII detection | PII | raw text (via adapter) | candidates | no | n/a | no | PII suites | none |
| Overlap resolution | PII | entities | resolved set + provenance | yes (`pii_result`) | no | no | overlap tests | none |
| Reading projection | PII | entities + map | projection fields | yes (`pii_result`) | no | no, but parallel to anchors (§8.3) | projection tests | second lineage mechanism |
| Anchor binding | PII | entities + graph | anchor-bound entities | no (derived) | n/a | inherits both risks above | `test_pii_anchor_binding.py` | none in logic |
| Entity contract | PII | binding + review overlay | `PiiEntityContractV1` | no (derived) | n/a | no | `test_pii_review_entity_contract.py`, e2e | recomputed per request |
| Review overlay | Review | decisions | JSONL, keyed to `pii_result.id` + occurrence id | yes | append-only | no (keys on occurrence ids, not anchor ids — safe) | review tests | not the formal `review_result` |
| Frontend highlights | UI | contract | per-view segments | no | n/a | no (render-only) | `piiHighlights.test.ts`, `ReviewTextViewer.test.tsx` | silent empty state on contract-fetch failure (§9) |
| Replacement plan / render / reconstruction map | future | — | — | — | — | — | — | not implemented (by design) |

Two structural observations:

1. **The lineage guard works.** `_matching_text_artifact` refuses to bind when the latest text
   artifact id differs from the PII run's input package id — an OCR re-run degrades the contract to
   evidence-only instead of binding to wrong offsets. Tested.
2. **Everything derived is derived deterministically**, so the non-persistence of package/graph/
   contract is currently safe. It stops being safe the moment mutable state references derived ids
   (§10).

## 5. What "anchor-first" means here — ideal vs. v1

**A. Ideal anchor-first:** source word units (with page/row/geometry provenance) are created during
extraction; raw, canonical, and layout are *renderings over those units*, each emission recording
"unit X rendered at view offsets [a,b)". Lineage is a construction fact. Repeated values are
trivially distinguishable because each occurrence is a different unit from a different source
position.

**B. Current v1:** raw/canonical/layout exist first as strings; the anchor graph re-tokenizes raw
and aligns to canonical via the unique-token map. Lineage is a *reconstruction*, and repetition is
unresolvable by design.

**Is v1 acceptable as a staged implementation? Yes**, for three reasons: (a) it fixed the observed
raw/canonical divergence at the model level, with an E2E test that fails without it; (b) it
established the correct *contract shape* (per-view ranges, explicit states, text-free metadata) so
consumers are already coded against the right interface; (c) it did all this without a DB, schema
break, or detection change. The staged plan in ADR-0031 §13 anticipated exactly this.

**What moves it toward true anchor-first:** the reading-text builder already walks positioned rows,
blocks, and geometry when it renders each fragment. Emitting `(raw_span → reading_span)` segments
*at that moment* — instead of discarding the correspondence and re-deriving it by unique-token
matching — converts lineage from heuristic to fact, resolves repeated tokens wherever the builder
knew their source row, and requires **no new dependency and no new OCR capability**. That is the
single highest-leverage change available (Phase recommendation #1, §13).

**Is true anchor-first possible with current OCR inputs?** For PDF text-layer documents:
substantially yes — pypdf positions, L10 `text_geometry`, and L9 blocks already exist at
construction time. For OCR (image) pages: line-level yes (PaddleOCR line polygons), word-level only
partially (would need word boxes / token confidences retained past the transient stage). For DOCX:
no geometry exists; anchor-first there means paragraph/run-level construction lineage from
python-docx structure, which is feasible but different work. **Missing metadata today:** retained
word/row source ids through the reading-text builder, page segmentation on package sources (the
graph's `page_number` is always `None` in v1), and a builder/graph version stamp inside anchor ids
or alongside any persisted reference.

## 6. Guarantee matrix

**Hard guarantees (hold by data structure, today):**

| Guarantee | Mechanism |
| --- | --- |
| A detected entity is never dropped by mapping/binding failure | evidence-only fallback path; schema forbids silent absence (`binding_status` + reasons required) |
| Raw highlight range always valid for the run's raw text | raw offsets are the detection coordinate system; contract validates span/value length |
| Missing/partial/ambiguous is explicit, reason-coded, and machine-readable | `PiiAnchorBindingReason`, `mapping_status`, summary count cross-validation in pydantic |
| Repeated identical strings are never merged into one identity | binding is offset-overlap only; evidence-only ids include the raw span; tested on both layers |
| No document/entity text in anchor or binding metadata | ids/offsets/codes-only models; leak tests assert synthetic values appear nowhere outside `value` |
| Deterministic output for identical inputs (same bytes, same code) | deterministic ids, sort keys, ordered reason codes; order-independence tested |
| Stale-lineage safety | contract binds only when text-artifact id == PII input package id |
| Review continuity across the identity upgrade | decisions key on occurrence ids (`source_entity_ids`), not on anchor ids |

**Soft guarantees (hold when lineage is good):**

| Guarantee | Condition |
| --- | --- |
| Canonical highlight for a raw-detected value | every token of the value is a globally unique token string in both raw and reading text (or raw == reading byte-identically), and the detection span aligns to token boundaries (`exact` binding) |
| Layout highlight | layout text byte-identical to raw (v1 rule — nearly vacuous for real layout renderings) |
| Same `entity_id` across PII re-runs | raw text bytes identical **and** graph-builder code identical |
| `anchor_exact` binding | recognizer span boundaries coincide with tokenizer boundaries (punctuation-swallowing recognizers or aggressive number/identifier token fusion degrade to `partial`, which then loses all canonical/layout display ranges) |

**Impossible/unsafe without geometry, token confidence, or source word ids:**

| Non-guarantee | Why |
| --- | --- |
| Distinguishing repeated values (header/footer company, table-row repeats, address repeats, a name mentioned twice) | string-level lineage cannot pick an occurrence; only positional evidence can. v1 correctly refuses (`repeated_token_ambiguity`) rather than guessing |
| Canonical mapping under reorder **plus** repetition | same as above; reorder alone is fine (unique-token matching is order-independent) |
| Identity stable across OCR re-runs whose raw text changed at all | offsets shift → all anchor ids shift; nothing can fix this except source-unit identity below the string level |
| Ranges in a real (non-byte-aligned) layout view | no layout lineage exists; v1's byte-equality rule is an honest placeholder |
| Redaction-ready geometry | word-level boxes remain L11+ future work |

## 7. Failure mode matrix

| Failure mode | Current behavior | Honest? | Residual risk |
| --- | --- | --- | --- |
| Repeated identical values (both views) | anchor `ambiguous`, entity keeps raw range, `repeated_token_ambiguity` + `canonical_range_missing` | yes (e2e-tested) | none beyond missing display; needs geometry to *solve* |
| Repeated token **inside** an otherwise unique multi-token value (e.g. `ORG "Muster Handels GmbH"` plus a second company ending in the same `GmbH` token) | the repeated token's anchor loses its canonical range → the **whole entity** loses its canonical display range (display refs require all anchors complete), reason-coded | yes, but surprising | common in German business documents; untested (§9); construction-lineage fixes it |
| Reordered text (two-column raw vs. logical reading order) | handled — unique-token map is order-independent; e2e fixture is exactly this case | yes | — |
| Table flattening / pipe-delimited reading rows | inserted `\|` and reformatted cells become canonical-only `inserted` anchors; unique cell values still map; repeated cell values (amounts, units) go `ambiguous` | yes | numeric table columns will rarely map — expected, visible |
| Multi-column OCR with wrong column interleave in raw | anchors follow raw as-is; canonical mapping still works per unique token; binding unaffected | yes | garbage-in preserved (by design: raw is authoritative) |
| Split/merged tokens between views (de-hyphenation, spacing repair) | token strings differ → unmapped → `missing`/`partial` | yes | soft coverage loss; construction lineage fixes |
| OCR noise (confusions, glyph runs) | noise tokens are anchors like any other; noise evidence (L15) is metadata only, not consumed by binding | yes | none structural; quality suite could correlate noise ↔ binding failures |
| Phone/date/id regex overmatching **in the tokenizer** | the `\n`-crossing case is fixed (`[ \t]` only) and regression-guarded (`test_no_anchor_raw_range_crosses_a_line_break`); remaining risk: `_NUMBER_RE`/`_IDENTIFIER_*_RE` can fuse adjacent values on one line (e.g. `12.03.2024/4711` → one identifier token) → detection of the inner value binds `partial` → loses canonical display | yes (reason-coded) | tokenizer grain is now a *load-bearing* product surface; changes re-mint ids (§3) and shift binding outcomes — needs its own regression corpus |
| Line breaks inside values | raw anchors never cross a line break (guarded); a raw-detected value that wraps across lines binds to per-line anchors — exact if boundaries align | yes | — |
| Normalization differences raw↔canonical | mapped only when token strings are equal; whitespace-only gaps bridged; anything else `missing` | yes | conservative-by-string, not by meaning |
| Canonical text reconstruction errors | canonical is never authoritative; wrong reading text degrades display only | yes | — |
| Layout text approximation | non-aligned layout → single-source anchors, `unsupported_source`; no PII ranges | yes | layout view is effectively unhighlightable in practice |
| Missing `reading_text_map` | package warns `missing_mapping`; graph warns; all raw anchors `missing` canonical; contract falls back to stored projection fields | yes | two-mechanism coexistence (§8.3) |
| Partial token overlaps (detection cuts across an anchor) | `partial` binding; identity pins anchor ids **plus** raw span; no display refs | yes | partial entities lose canonical display entirely — could carry per-anchor partial display later |
| Value present in canonical but not raw | canonical-only `inserted` anchors exist, but PII detects on raw only → unreachable today; explicit in graph | yes | fine until a canonical detection source exists (gated anyway) |
| Value in raw omitted from canonical | anchor `missing` canonical; entity keeps raw | yes | — |
| Evidence-only fallback (no/stale graph) | `not_applicable`, explicit contract flags (`anchor_graph_available: false`) | yes | — |
| Ambiguous binding (mutually overlapping candidate anchors) | `ambiguous`, `inferred_span` refs, evidence-only identity | yes | nearly unreachable with the v1 non-overlapping tokenizer; defensive |
| **String search** | backend `text_match` unique-value fallback (labeled) and `reading_text.count(entity.text)` ambiguity probe exist server-side; the **frontend never searches** | labeled, but see §8.3 | the architecture intends to retire string-derived display; v1 still leans on it for coverage |

## 8. Implementation conformance scorecard

Scored against ADR-0031's invariants and the `.ai/quality-gates.md` anchor gates.

| # | Invariant / gate | Status | Notes |
| --- | --- | --- | --- |
| 1 | Anchors owned by OCR/Text, derived from the package; consumers bind, never create | **Conforms** | PII imports the builder read-only; graph endpoint lives on the OCR router |
| 2 | Anchor metadata text-free | **Conforms** | schema + leak tests on graph, binding, contract, e2e |
| 3 | Missing/ambiguous mapping explicit, never guessed; string equality never merges identity | **Conforms** | verified across all three layers |
| 4 | Diagnostics structural only | **Conforms** | counts/codes/ratios only |
| 5 | Anchors are per-line identity units | **Conforms** | fixed by PR #59; regression-guarded |
| 6 | Bound-anchor view ranges reach the contract (E2E conformance) | **Conforms** | real end-to-end test through the HTTP API; fails without the fix |
| 7 | Raw text is the offset authority, never mutated; separation gate intact | **Conforms** | detection is raw-only; anchor work adds no input switch |
| 8 | No DB before the model is proven | **Conforms** | everything derived or file-based |
| 9 | Frontend renders only server ranges; no independent entity derivation; no string search | **Conforms with two footnotes** | (a) legacy `buildHighlightSegments` is dead in production paths but still exported and test-maintained — remove or quarantine; (b) a failed contract fetch yields an *empty* highlight model with no user-visible notice (§9) |
| 10 | One stable anchor identity per unit, stable across re-runs | **Partial** | stable only per (bytes × builder version); acceptable now because nothing durable references anchor ids — must be resolved before Phase F (§10) |
| 11 | Views are projections of shared units (construction-level) | **Not yet** | A first attempt at `anchor-first-text-package-v2` was found, by a contradiction audit, to be a *post-render* projection (it runs after `reading_text.py` already returns a finished string and re-derives correspondence via exact search over that string) rather than builder-emitted lineage — `reading_text.py` itself is unchanged. That mechanism was reclassified and hardened as **Geometry-backed Reading Projection v1** (`ReadingTextGeometryProjectionMap`, `lineage_source: geometry_projection`), a stronger *post-hoc* mechanism preferred over the older `reading_text_map`, with a fixed duplicate-value identity defect (see §8.3 update). Genuine construction-level lineage remains open |

### 8.3 The two-mechanism wart

The contract mixes two lineage mechanisms: (1) anchor display ranges (graph + map), and (2) the
older ADR-0029 projection stored on `pii_result` (`offset_map` / `text_match` unique-value
fallback), used when (1) yields nothing. They can disagree in *coverage*: the `text_match` fallback
will place a value the anchor graph classifies `missing` (unique value, no map segment — the graph
deliberately does no value matching). The result is honest (labeled `projected` /
`projection_method: "text_match"`) but architecturally backwards: display coverage can come from
exactly the string-matching the anchor model exists to retire, and mapping_status `exact` can be
claimed via anchors while another entity's `projected` came from a string search. Recommendation:
keep the fallback for v1 coverage, but (a) surface a distinct reason code when display came from
`text_match`, and (b) plan its retirement when construction-time lineage lands (v2), at which point
the unique-value fallback should become unnecessary.

> **Update (Geometry-backed Reading Projection v1).** A stronger *post-hoc* mechanism now lands as
> the preferred one ahead of `reading_text_map`: the anchor graph consults
> `ReadingTextGeometryProjectionMap` segments — built by searching the *already-completed* canonical
> text for an exact, line-bounded occurrence of each raw geometry line — before the older unique-token
> map, and both the package `lineage_summary` and per-anchor flags (`canonical_geometry_projection` /
> `canonical_map_lineage`) make the source explicit. **This is not construction-time lineage**: a
> contradiction audit of the first attempt found it ran entirely after `reading_text.py` returns and
> reproduced a duplicate-value identity defect (two identical full lines could be bound to inverted
> canonical occurrences, both confidently labeled `exact`, depending only on processing order); the
> hardening pass fixed that by requiring global uniqueness (exact text occurs exactly once among
> source lines *and* exactly once, line-bounded, in canonical text) before ever claiming `exact`,
> declining to an explicit `ambiguous` state otherwise. `reading_text_map` and the ADR-0029
> `text_match` projection remain as labelled fallbacks for legacy/minimal artifacts and for lines the
> geometry projection declines (non-verbatim, no geometry, or genuinely ambiguous). Genuine
> builder-emitted construction-time lineage — the actual retirement condition for `text_match` — is
> still unimplemented.

## 9. Test coverage scorecard

| Area | Verdict | Evidence |
| --- | --- | --- |
| Architecture-level E2E conformance | **Strong** | `test_anchor_bound_pii_e2e_conformance.py`: package→graph→binding→contract over HTTP, reordered two-column fixture, per-class propagation, structural-reason-only absence, layout propagation, leak checks. Fails without the PR #59 fix. |
| Anchor graph unit behavior | **Strong** | creation, canonical attach, partial/missing/ambiguous, single-source, byte-aligned layout, line-break integrity, id determinism, schema rejection, endpoint 404s, legacy artifacts |
| Binding semantics | **Strong** | exact/partial/missing/ambiguous/not-applicable, multi-token sets, provenance merge, cross-type separation, determinism, id derivation, leak checks |
| Contract semantics | **Strong** | anchor-vs-projection interplay, review overlay reflection, byte-compat of old endpoints, reason-coded absence |
| Frontend no-guessing rules | **Strong** | no invented canonical ranges; contract ranges instead of value-based repetition highlighting; rejected-entity suppression across views; no private values in metadata |
| Privacy/no-copy invariants | **Strong** | leak assertions at every layer with synthetic sensitive values |
| **Gaps** | | 1. **Mixed-uniqueness entity**: a multi-token value with one repeated token (the `GmbH`-suffix case) — the most common real-world canonical-loss path — has no test. 2. **Tokenizer grain regression corpus**: no suite pins binding outcomes for adjacent dates/phones/ids on one line (fusion risk) or punctuation-swallowing recognizer spans (partial-binding risk). 3. **Frontend structural-failure honesty**: contract fetch failure (null) renders zero highlights with no notice — untested and arguably a hidden failure state; the UI cannot distinguish "no entities" from "contract unavailable". 4. **Builder-version identity drift**: no test asserts (or documents) that anchor ids change when the tokenizer changes — the risk that matters for future persisted references. 5. **Performance/scale**: graph + binding recomputed per request; no budget test for large documents (acceptable local-first, worth a marker before Review-heavy UI polls the contract). |

## 10. Persistence recommendation (re-grounded in implementation)

Option E (hybrid) remains correct; the implementation adds one new constraint the ADR did not
foresee explicitly:

> **Anchor ids are only as durable as the graph builder.** Because the graph is derived on demand,
> a builder/tokenizer change re-mints every anchor id for unchanged artifacts. Today that is safe
> (review decisions key on occurrence ids; nothing persists anchor ids). It becomes unsafe the
> moment `review_result`, replacement plans, or a reconstruction map store anchor ids.

Grounded recommendations:

- **Stay JSON-artifact + derived-endpoint for now.** The derived package/graph/contract are
  deterministic and cheap at local scale; nothing needs a DB yet.
- **Before any durable state references anchor ids (Phase F/G/H):** either persist the anchor graph
  as an immutable JSON artifact beside `text_result` (pinning ids at run time), or stamp a
  `graph_builder_version` into every persisted anchor-id reference and refuse to resolve across
  versions. Persisting the graph is the simpler, more auditable option and matches "immutable
  artifacts stay JSON".
- **`review_result` v1 should keep keying on occurrence ids** (as the overlay does), carrying
  anchor-derived `entity_id` as *secondary* linkage until graph persistence lands. That preserves
  review continuity under builder upgrades.
- **SQLite enters with replacement plans / reconstruction / audit** — genuinely mutable,
  queryable, cross-document state — exactly as ADR-0031 §8 stages it. Not before.
- **Do not move into SQLite yet:** text layers, packages, graphs, `pii_result`, the entity
  contract. Nothing in the implementation pressures that; per-request derivation cost is the only
  pressure and caching/persisting JSON solves it without a DB.

## 11. Pseudonymization readiness

Trace: anchor-bound entity → review decision → replacement plan → pseudonymized render.

- **Can replacement be rendered from anchors?** From *entities*, yes: every entity always carries an
  authoritative raw range, so a raw-view render (splice placeholder text over entity raw ranges —
  offset-based generation, not blind string replacement) is expressible today from the contract
  alone. A canonical-view render is expressible **only for entities with a canonical display range**
  (exact binding, all anchors mapped). Partial/missing/ambiguous entities have no canonical range —
  a canonical render must therefore either force review, fall back to the raw-view render, or refuse;
  that policy does not exist yet and must be explicit in the replacement-plan design.
- **Are display ranges enough?** For raw: yes. For canonical: no — display ranges cover the value
  itself, but a correct canonical render must also guarantee that *no unreplaced copy* of the value
  survives elsewhere in the view (repeated values are precisely the ones lacking ranges). A
  render-safety check ("every occurrence of every replaced value is covered or the render is
  blocked/flagged") is required; it can be a transient in-memory scan at render time (no stored
  text).
- **Entity spans vs. anchor spans:** keep both, as now. Entity raw span = replacement target;
  anchor set = identity/grouping key. What is missing is the **replacement group** (one placeholder
  per real-world referent): today's `pii_grouping.py` normalized-value grouping is a reasonable
  seed but is value-based; the plan must let a reviewer merge/split groups.
- **Missing data before Phase G:** replacement groups + tokens (`PERSON_001`), a persisted plan
  keyed to `pii_result.id` (+ pinned graph, §10), the partial/missing render policy, and a render
  manifest (which entities, which ranges, which view, which plan) persisted immutably per render.
- **Paint-over avoidance:** satisfied by construction — rendering is generation from decisions +
  offsets over immutable inputs.

**Readiness: structurally ready for raw-view pseudonymization after a replacement-plan model
exists; canonical-view pseudonymization needs the render-safety policy; nothing blocks the design
work.**

## 12. Reconstruction readiness

Trace: external AI output containing `PERSON_001` → replacement group → entity → anchors → original
value representation → policy/audit.

- **What must be stored:** placeholder token, `replacement_group_id`, member `entity_id`s (+
  `pii_result.id` and graph pin), anchor ids, an original value representation, approval/policy
  state, and append-only audit events. This is the access-gated `reconstruction_map` of ADR-0031 §9
  — the only store that may hold original values.
- **Is the current model enough?** The *identity chain* is: deterministic entity ids exist and are
  derivable; anchor sets exist. But **nothing is persisted** — the contract is recomputed per
  request, so today there is no durable object a placeholder could point to. Reconstruction
  requires freezing the chain at render time (render manifest + reconstruction map), which is
  Phase G/H work by design.
- **What is missing before reconstruction:** replacement plan (G), render manifest (G), persistence
  of the pinned identity chain (§10), the access-control/audit model (H, own ADR), and deletion
  semantics (map dies with the document boundary).
- **What must never be reconstructed automatically:** anything without an explicit, audited,
  policy-allowed request; anything whose chain crosses a re-run boundary (stale `pii_result` or
  changed text artifact); and never by fuzzy-matching private text in the AI output — placeholder
  identity is the only lookup key. The current model's determinism makes the safe path natural; no
  implemented code violates it because none exists.

**Readiness: conceptually ready, implementationally absent — correctly so. No gap versus the staged
plan; the §10 pinning constraint is the one prerequisite the ADR should absorb.**

## 13. Recommended next three phases

Grounded in the audit's findings — the biggest structural gap is construction-time lineage, the
biggest safety gap is untested hard cases, and the most-requested product step is review
persistence.

### Phase 1 — `anchor-first-text-package-v2` (construction-time lineage) — **not complete**

> **Status update.** Not delivered — a first attempt on branch `anchor-first-text-package-v2` was
> found by a contradiction audit to be a *post-render projection*, not construction-time lineage:
> `reading_text.py` (the actual builder) was provably unchanged, and the new mechanism ran strictly
> after `build_reading_text(...)` already returned a finished string, re-deriving correspondence via
> exact search over that completed string (`str.find`) — architecturally the same category of
> operation as the pre-existing post-hoc `reading_text_map`, just at full-line granularity instead of
> unique-token granularity. The audit also reproduced a concrete identity defect: two textually
> identical full raw lines could be bound to *inverted* canonical occurrences (both labeled `exact`,
> `confidence=1.0`) depending only on the order geometry lines were processed in — determinism, not
> proof of identity.
>
> The mechanism was **reclassified and hardened, not discarded**, as **Geometry-backed Reading
> Projection v1** (`reading_text_geometry_projection.py`, `ReadingTextGeometryProjectionMap`,
> `lineage_source: geometry_projection`): a source line may now be claimed `exact` only when its
> exact text occurs exactly once among the collected verbatim source lines **and** exactly once,
> line-bounded, in the canonical text; every other candidate occurrence of a non-unique value becomes
> an explicit `ambiguous` segment (no source range, no `confidence=1.0`, reason-coded — never the
> duplicated value itself) instead of being picked by processing order. Verified: the same
> raw/canonical text projected with reversed geometry-line encounter order now yields identical,
> still-ambiguous output rather than two mutually-inverted `exact` claims. The useful case survives —
> two distinct company names sharing a repeated `GmbH` suffix still keep their canonical range,
> because each full line is globally unique — while a genuinely duplicated full-line/label value (or
> the same value repeated across pages) is declined end-to-end through anchor binding, never guessed.
>
> **This remains a stronger *post-hoc* mechanism, preferred over `reading_text_map` when it resolves a
> line unambiguously — it is explicitly not builder-emitted and not authoritative construction
> identity.** `reading_text.py` still discards its own per-fragment source knowledge
> (`ReadingRow`/`ReadingCell` carry no raw offsets). Genuine construction-time lineage — the reading-
> text builder itself emitting `(raw_span → reading_span)` while rendering — remains unimplemented;
> Phase 1 as originally scoped is **not complete**, and a real `anchor-first-text-package-v2` is a
> separate, future branch. No reading-text byte change, no detection change, no DB.
>
> **Status update (2026-07-10).** A genuine, but partial, first slice of this phase is delivered —
> see [ADR-0032](../adr/0032-reading-text-row-construction-lineage-v1.md). `ReadingRow` now carries
> an optional `source_range`, attached once at collection time (exact from L10 geometry; via a
> global-uniqueness row-text match for the primary pypdf-visitor path) and threaded through
> rendering by the builder itself for the plain-paragraph/body path only
> (`_join_continuations_with_flags`); canonical offsets are computed by walking the same block/line
> join arithmetic the text was assembled with, never by searching the finished string. This is
> **real construction-time lineage** for the paths it covers — the goal this phase set out to
> achieve — but it is deliberately **not** the full builder rewrite the goal below describes: party
> columns, table cells/rows, multi-column reconstruction, metadata, and joined post-table prose
> still emit no lineage at all (not even an explicit decline marker). A later narrow additive slice
> permits unchanged post-table total/standalone rows to retain their own pre-attached range; the
> synthetic section heading remains unbound. Cell-level granularity is out of scope.
> Those paths, and a real `anchor-first-text-package-v2` that unifies every rendering path behind
> one contract, remain open — the acceptance criteria below (byte-stability, legacy-artifact safety,
> e2e conformance) hold for the delivered slice, but full-document acceptance does not yet.

- **Goal:** the reading-text builder emits `(raw_span → reading_span)` segments *while rendering*
  each fragment (it already holds the source rows/geometry), replacing dependence on post-hoc
  unique-token matching; the anchor graph consumes builder-emitted segments first and falls back to
  the v1 map for legacy artifacts.
- **Why now:** it is the v1→anchor-first pivot; it fixes the dominant real-world failure (repeated
  tokens, split/merged tokens) at the root; it needs no new dependency, no schema break (additive
  map version), and no detection change; every later phase (render safety, geometry anchors)
  inherits the benefit.
- **Acceptance:** repeated values that the builder placed from distinct source rows map to distinct
  canonical ranges; the `GmbH`-suffix mixed-uniqueness case propagates a full canonical range; the
  `text_match` display fallback becomes unnecessary on new artifacts (retirement plan per §8.3);
  byte-stability of all text layers; legacy artifacts unchanged; e2e conformance suite extended and
  green.
- **Risks:** builder complexity (it has many rendering paths — each must emit or explicitly decline
  lineage); silent wrong lineage is worse than missing lineage, so declined-lineage must stay an
  explicit state.
- **Do not:** change detection input, alter reading-text output bytes, guess segments for
  low-confidence paths, or persist the graph in this phase.

### Phase 2 — `pii-binding-quality-suite`

- **Goal:** a synthetic hard-case regression corpus + metrics gate for binding/coverage quality:
  mixed-uniqueness entities, adjacent same-line dates/phones/ids (tokenizer fusion), punctuation-
  swallowing recognizer spans (partial binding), header/footer repeats, table columns, DOCX/no-
  geometry documents; plus a documented builder-version identity-drift test and the frontend
  contract-fetch-failure notice (a visible "contract unavailable" state instead of silently empty
  highlights).
- **Why now:** the tokenizer and map are now load-bearing product surfaces; Phase 1 will change
  both, and this suite is the safety net that lets it land measurably (before/after coverage
  ratios), not anecdotally.
- **Acceptance:** binding/coverage ratios asserted per fixture class; suite fails on tokenizer
  regressions; frontend failure state tested; no private corpus data.
- **Risks:** over-fitting fixtures to current heuristics — express expectations as invariants
  ("never silent", "reason-coded") plus coverage floors, not exact segment layouts.
- **Do not:** tune recognizers, add detection features, or use private corpus files as fixtures.

> **Status update (2026-07-10).** Delivered — see
> [ADR-0033](../adr/0033-pii-binding-quality-suite.md). Mixed-uniqueness entities and header/footer
> repeats were already covered by `test_anchor_bound_pii_e2e_conformance.py`; the new
> `test_pii_binding_quality_suite.py` adds the remaining named cases (tokenizer fusion,
> punctuation-swallowing partial binding, table columns, DOCX/no-geometry), a builder-version
> identity-drift test, and additive `anchor_bound_ratio`/`exact_bound_ratio` coverage-floor metrics
> on `PiiAnchorBindingSummary`. Scoping the fusion case surfaced a real, previously-untested
> tokenizer edge case (a date directly adjacent to a phone number, no separator, fuses into one raw
> anchor) — left unfixed per the "do not tune recognizers" guardrail and regression-locked instead
> as an honest `partial` degrade. The frontend contract-fetch-failure notice is delivered:
> `fetchPiiEntityContract` returns a discriminated `ok`/`not_found`/`error` result, and
> `DocumentDetailPage.tsx` shows a visible notice on `error` (never on the normal `not_found` 404).
> No recognizer, detection, tokenizer, or binding-algorithm change.

### Phase 3 — `review-result-v1` (Review L8)

- **Goal:** the formal single-artifact-per-run `review_result` over stable entity identity, keyed
  primarily on occurrence ids with anchor-derived `entity_id` as secondary linkage (per §10), with
  an explicit stale flag when the underlying `pii_result` changes.
- **Why now:** it is the long-standing next engine step (state.md), the first consumer that makes
  the persistence question concrete (Phase E/F), and it benefits from landing *after* the identity
  layer stabilized in Phases 1–2.
- **Acceptance:** immutable-per-run review artifact; decisions survive reload and re-runs mark
  staleness explicitly; `pii_result` stays immutable; overlay migration path documented; no DB
  required yet (JSON per run), with the SQLite-ready shape stated.
- **Risks:** identity churn if anchor ids are used as primary keys before graph persistence —
  avoided by the occurrence-id-primary rule.
- **Do not:** introduce SQLite in the same PR, bind decisions to anchor ids without a pinned graph,
  or build replacement planning into the review artifact.

> **Status update (2026-07-10).** Delivered — see
> [ADR-0034](../adr/0034-review-l8-review-result-artifact.md). The immutable-per-run artifact,
> occurrence-id-primary keying, explicit `stale_decision_count`/`has_stale_decisions` signal, and
> documented (not executed) JSONL-to-artifact migration path are all in place, with no SQLite
> introduced. **Not delivered from the literal goal text:** "anchor-derived `entity_id` as secondary
> linkage" — `pii_review_service.py` has no dependency on the anchor-binding pipeline
> (`pii_anchor_binding.py`/`pii_entity_contract.py`) today, and wiring one in to attach a secondary,
> best-effort anchor-derived reference per occurrence was judged a real architectural addition, not
> a same-PR-sized omission; occurrence ids alone (the primary key the acceptance criteria actually
> requires) are sufficient for decisions to survive reload/re-runs correctly. Left open for a future
> PR if a consumer needs it.

*(Geometry-backed anchors — word/row boxes as anchor provenance — remain the right Phase 4: after
construction-time lineage, geometry's marginal value concentrates on OCR-page word grain and
redaction-readiness rather than on canonical mapping, and Phase 1 already reuses the geometry the
builder consumes.)*

## 14. Do-not-do list

- Do **not** persist anchor ids into any mutable state before the graph (or a builder version pin)
  is persisted with them.
- Do **not** let the frontend recover missing ranges by string search — the current discipline is
  correct; also do not leave a failed contract fetch looking like "no entities".
- Do **not** merge repeated identical values by string equality anywhere — grouping stays derived
  and reviewable.
- Do **not** make canonical (or `pii_input_text`) the active detection input — the
  `text_lineage_map` separation gate stands; the anchor graph is a prerequisite, not a bypass.
- Do **not** introduce SQLite before `review_result`/replacement state proves the relational shape.
- Do **not** implement pseudonymization before a replacement-plan model with an explicit
  partial/missing render policy exists; never paint-over.
- Do **not** implement reconstruction before a persisted render manifest + access-gated map exist;
  never fuzzy-match private text.
- Do **not** treat tokenizer changes as internal refactors — they re-mint identity; gate them with
  the quality suite.
- Do **not** copy document text into anchors, bindings, diagnostics, fixtures from private corpus,
  or this documentation.

## 15. Final verdict

**Keep the architecture.** The anchor identity model is the correct substrate for the product's
Golden Path (stabilize → identify → detect → review → replace → render → reconstruct), and no
audited evidence contradicts its feasibility.

**Treat current v1 as a transitional layer — deliberately and openly.** It is anchor-derived, not
anchor-first: identity is offset-minted, lineage is post-hoc string alignment, layout is
byte-equality-only, and a parallel string-match display fallback persists. None of this is hidden;
every degradation is explicit, tested, and reason-coded, which is exactly what makes the
transitional layer safe to build on.

**The target architecture is practically achievable, under four conditions:**

1. **Construction-time lineage lands** (Phase 1) — otherwise canonical identity remains hostage to
   global token uniqueness and the model plateaus at "honest but sparse".
2. **Identity is pinned before it is referenced** — persist the graph (or version-pin ids) before
   review/replacement/reconstruction state stores anchor ids.
3. **Tokenizer/map changes are treated as identity-affecting** and gated by a regression corpus.
4. **Repetition is eventually solved by position, not strings** — geometry/source-unit provenance,
   staged after construction lineage.

**What would make it fail:** quietly re-introducing string-derived display coverage as "good
enough" until it becomes the de facto mechanism; persisting anchor ids without pinning; letting the
UI hide structural failures; or building pseudonymization on display ranges without a render-safety
policy for the entities that structurally cannot have them. All four are avoidable, and the
existing quality gates already forbid three of them.
