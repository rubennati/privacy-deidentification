"""Private local OCR/PII benchmark runner.

Not part of the ``app`` package: this is a standalone, dependency-free (stdlib only) tool that
reads already-computed audit/OCR/PII artifacts from ``volumes/document-store`` and private
benchmark inputs from ``volumes/benchmark`` to produce a safe, PII-free markdown/JSON report.
See ``README.md`` in this directory.
"""
