# ADR-0006: DOCX table-aware extraction and precision-first PII defaults

## Status

Accepted — 2026-07-01

## Context

Two quality gaps surfaced on the real document corpus while the MVP flow
(Upload → Audit → OCR/Text → PII → Review) was otherwise working:

- DOCX extraction used only `document.paragraphs`, which omits paragraphs nested in table
  cells. On the target corpus this dropped roughly three quarters of the text, and Audit and
  OCR/Text computed their DOCX statistics independently, so they could diverge.
- The PII default allowlist included the spaCy NER types PERSON/ORGANIZATION/LOCATION. The small
  German model over-tags these at a fixed ~0.85 score, producing most of the false positives. The
  score threshold cannot separate them from true hits, and raising it would instead drop precise
  structured recognizers (URL sits at 0.5).

## Decision

- Extract DOCX text with a single shared helper (`app/services/docx_extraction.py`) used by both
  Audit and OCR/Text, so the two stations always interpret a DOCX identically. It walks the body
  in document order, emitting paragraphs and tables (rows newline-joined, cells within a row
  tab-joined, horizontally merged cells once) and appends defined section headers/footers. Output
  is a pure function of the bytes, keeping downstream PII offsets stable. Textboxes/shapes, nested
  tables, and layout reconstruction stay out of scope; `python-docx` reads everything present in
  the target corpus, so no new tool (Docling/Mammoth/LibreOffice) is introduced.
- Default the PII allowlist to high-precision, pattern-based recognizers only: EMAIL_ADDRESS,
  PHONE_NUMBER, IBAN_CODE, CREDIT_CARD, IP_ADDRESS, URL. PERSON/ORGANIZATION/LOCATION and DATE_TIME
  remain fully supported but opt-in via `PII_ENTITY_TYPES`. The score threshold stays 0.5.
- Cap the `presidio-analyzer` logger at WARNING to drop its INFO initialization burst while
  preserving genuine warnings/errors. Decision-process logging stays disabled and no source or
  entity text is logged.

## Consequences

- DOCX documents yield substantially more, table-inclusive text, and Audit and OCR/Text agree on
  the character count by construction.
- Out of the box, PII detection favors precision over recall; teams that need name/organization/
  location or date labeling enable them explicitly. This does not add anonymization or redaction.
- Refines, and does not replace, [ADR-0004](0004-ocr-workstation.md) and
  [ADR-0005](0005-pii-workstation.md).
